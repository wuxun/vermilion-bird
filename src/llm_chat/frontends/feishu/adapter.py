"""FeishuAdapter - Bridge between Feishu webhook events and internal LLM processing."""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, Optional

import httpx

from llm_chat.utils.retry import retry

from llm_chat.app import App
from llm_chat.frontends.base import Message, MessageType
from llm_chat.frontends.feishu.mapper import SessionMapper
from llm_chat.frontends.feishu.models import FeishuEvent, FeishuMessage
from llm_chat.frontends.feishu.security import (
    AccessController,
    MessageDeduplicator,
    RateLimiter,
    SignatureVerifier,
)

logger = logging.getLogger(__name__)


class FeishuAdapterError(Exception):
    """Base exception for FeishuAdapter errors."""

    pass


class SecurityViolationError(FeishuAdapterError):
    """Raised when security checks fail."""

    pass


class RateLimitExceededError(FeishuAdapterError):
    """Raised when rate limit is exceeded."""

    pass


class AccessDeniedError(FeishuAdapterError):
    """Raised when access is denied."""

    pass


class DuplicateEventError(FeishuAdapterError):
    """Raised when a duplicate event is detected."""

    pass


class FeishuAdapter:
    """Adapter for processing Feishu events and integrating with the LLM application.

    Does NOT inherit from BaseFrontend per plan guardrails.

    Features:
    - Thread-safe concurrent request handling
    - Async LLM processing via ThreadPoolExecutor
    - Automatic response delivery back to Feishu
    - Session ID mapping via SessionMapper
    - Conversation persistence via Storage
    """

    FEISHU_API_BASE = "https://open.feishu.cn/open-apis"
    TOKEN_EXPIRY_BUFFER_SECONDS = 300
    DEFAULT_MAX_WORKERS = 4

    def __init__(
        self,
        app: App,
        app_id: str,
        app_secret: str,
        signature_verifier: Optional[SignatureVerifier] = None,
        rate_limiter: Optional[RateLimiter] = None,
        access_controller: Optional[AccessController] = None,
        deduplicator: Optional[MessageDeduplicator] = None,
        http_client: Optional[httpx.Client] = None,
        max_workers: int = DEFAULT_MAX_WORKERS,
        response_callback: Optional[Callable[[str, str, Dict[str, Any]], None]] = None,
    ):
        """Initialize the FeishuAdapter.

        Args:
            app: The App instance for LLM processing
            app_id: Feishu application ID
            app_secret: Feishu application secret
            signature_verifier: Optional signature verifier for security
            rate_limiter: Optional rate limiter
            access_controller: Optional access controller
            deduplicator: Optional message deduplicator
            http_client: Optional HTTP client for Feishu API calls
            max_workers: Maximum number of concurrent LLM workers
            response_callback: Optional callback(response_text, receive_id, content) for custom response handling
        """
        self.app = app
        self.app_id = app_id
        self.app_secret = app_secret
        self.signature_verifier = signature_verifier
        self.rate_limiter = rate_limiter
        self.access_controller = access_controller
        self.deduplicator = deduplicator
        self._http_client = http_client
        self._tenant_access_token: Optional[str] = None
        self._token_expires_at: int = 0

        # Thread-safe components
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="feishu_llm_"
        )
        self._token_lock = threading.Lock()
        self._conversation_locks: Dict[str, threading.Lock] = {}
        self._conversation_locks_lock = threading.Lock()
        self._response_callback = response_callback

        # 记录最近的对话，用于任务通知
        self._recent_chat: Optional[Dict[str, str]] = None

    def set_recent_chat(self, chat_id: str, chat_type: str = "chat_id"):
        """记录最近的对话，用于任务通知。

        Args:
            chat_id: 群聊 ID 或用户 ID
            chat_type: ID 类型，'chat_id' 或 'open_id' 或 'user_id'
        """
        self._recent_chat = {
            "type": "feishu",
            chat_type: chat_id,
        }
        logger.info(f"Recent chat recorded: {chat_type}={chat_id}")

    def get_recent_chat(self) -> Optional[Dict[str, str]]:
        """获取最近的对话。

        Returns:
            最近对话的信息字典，或 None
        """
        return self._recent_chat

    @property
    def http_client(self) -> httpx.Client:
        if self._http_client is None:
            self._http_client = httpx.Client(timeout=30.0)
        return self._http_client

    def _get_conversation_lock(self, conversation_id: str) -> threading.Lock:
        """Get or create a lock for a specific conversation to ensure thread-safety."""
        with self._conversation_locks_lock:
            if conversation_id not in self._conversation_locks:
                self._conversation_locks[conversation_id] = threading.Lock()
            return self._conversation_locks[conversation_id]

    def handle_event(self, event: FeishuEvent) -> Optional[FeishuMessage]:
        """Process a Feishu event synchronously and return a response message.

        For async processing, use handle_event_async instead.

        Args:
            event: The Feishu event to process

        Returns:
            FeishuMessage to send back, or None if no response needed

        Raises:
            DuplicateEventError: If the event is a duplicate
            AccessDeniedError: If access is denied
        """
        if self.deduplicator:
            if self.deduplicator.is_duplicate(event.event_id):
                logger.warning(f"Duplicate event detected: {event.event_id}")
                raise DuplicateEventError(f"Event {event.event_id} already processed")
            self.deduplicator.mark_processed(event.event_id)

        if not event.message:
            logger.warning(f"Event {event.event_id} has no message")
            return None

        message = event.message

        if self.access_controller:
            user_id = message.sender.user_id if message.sender else ""
            chat_id = message.chat.chat_id if message.chat else ""
            if not self.access_controller.is_allowed(user_id, chat_id):
                logger.warning(f"Access denied for user={user_id}, chat={chat_id}")
                raise AccessDeniedError(f"Access denied for user {user_id}")

        internal_message = self._convert_to_internal_message(event)
        chat_type = self._get_chat_type(message)
        original_id = message.chat.chat_id if message.chat else ""
        conversation_id = SessionMapper.to_conversation_id(chat_type, original_id)
        response_text = self._process_with_llm(internal_message, conversation_id)

        if not response_text:
            return None

        return self._convert_to_feishu_message(response_text, message)

    def handle_event_async(self, event: FeishuEvent) -> None:
        """Process a Feishu event asynchronously.

        The LLM response will be sent back to Feishu automatically after processing.
        This method returns immediately after basic validation.

        Args:
            event: The Feishu event to process

        Raises:
            DuplicateEventError: If the event is a duplicate
            AccessDeniedError: If access is denied
        """
        if self.deduplicator:
            if self.deduplicator.is_duplicate(event.event_id):
                logger.warning(f"Duplicate event detected: {event.event_id}")
                raise DuplicateEventError(f"Event {event.event_id} already processed")
            self.deduplicator.mark_processed(event.event_id)

        if not event.message:
            logger.warning(f"Event {event.event_id} has no message")
            return

        message = event.message

        if self.access_controller:
            user_id = message.sender.user_id if message.sender else ""
            chat_id = message.chat.chat_id if message.chat else ""
            if not self.access_controller.is_allowed(user_id, chat_id):
                logger.warning(f"Access denied for user={user_id}, chat={chat_id}")
                raise AccessDeniedError(f"Access denied for user {user_id}")

        self._executor.submit(self._process_event_background, event)

    def _process_event_background(self, event: FeishuEvent) -> None:
        if not event.message:
            return

        message = event.message
        try:
            internal_message = self._convert_to_internal_message(event)
            chat_type = self._get_chat_type(message)
            original_id = message.chat.chat_id if message.chat else ""

            # 记录最近的对话，用于任务通知
            if original_id:
                chat_id_type = "chat_id"
                self.set_recent_chat(original_id, chat_id_type)
                # 同时保存到数据库
                try:
                    from llm_chat.storage import Storage

                    storage = Storage()
                    storage.set_recent_feishu_chat(original_id, chat_id_type)
                except Exception as e:
                    logger.error(f"Failed to save recent chat to database: {e}")

            force_new = SessionMapper.check_new_session_command(
                internal_message.content
            )
            conversation_id = SessionMapper.to_conversation_id(
                chat_type, original_id, force_new_session=force_new
            )

            response_text = self._process_with_llm(internal_message, conversation_id)

            if response_text and message.chat and message.chat.chat_id:
                card = self._build_markdown_card(response_text)
                self.send_message(
                    message.chat.chat_id,
                    "interactive",
                    card,
                    receive_id_type="chat_id",
                )
            else:
                logger.warning("No valid way to send response to Feishu")

        except Exception as e:
            logger.error(f"Failed to send response to Feishu: {e}", exc_info=True)

    def _build_markdown_card(self, markdown_text: str) -> Dict[str, Any]:
        """Build a Feishu interactive card with markdown content.

        Args:
            markdown_text: The markdown text to render

        Returns:
            Card content dictionary for Feishu API
        """
        card = {
            "config": {"wide_screen_mode": True},
            "elements": [
                {
                    "tag": "markdown",
                    "content": markdown_text,
                }
            ],
        }

        return card

    def _convert_to_internal_message(self, event: FeishuEvent) -> Message:
        """Convert a FeishuEvent to internal Message format."""
        message = event.message
        if not message:
            raise FeishuAdapterError("Event has no message")

        content = message.text or ""
        if not content and message.content:
            content = self._extract_text_from_content(message.content)

        metadata = {
            "event_id": event.event_id,
            "event_type": event.event_type,
            "message_id": message.message_id,
            "create_time": message.create_time,
        }

        if message.sender:
            metadata["sender_id"] = message.sender.user_id
            metadata["sender_name"] = message.sender.name

        if message.chat:
            metadata["chat_id"] = message.chat.chat_id
            metadata["chat_type"] = message.chat.type
            metadata["chat_name"] = message.chat.name

        return Message(
            content=content,
            role="user",
            msg_type=MessageType.TEXT,
            metadata=metadata,
        )

    def _extract_text_from_content(self, content: Dict[str, Any]) -> str:
        """Extract text from Feishu message content.

        Handles common text-based message types including text and rich text (post).
        Format: {"zh_cn": {"title": "...", "content": [[{"tag": "text", "text": "..."}]]}}
        """
        if "text" in content:
            return content.get("text", "")

        if "post" in content:
            post = content["post"]
            for lang_content in post.values():
                if isinstance(lang_content, dict) and "content" in lang_content:
                    texts = []
                    for paragraph in lang_content["content"]:
                        for element in paragraph:
                            if (
                                isinstance(element, dict)
                                and element.get("tag") == "text"
                            ):
                                texts.append(element.get("text", ""))
                    return " ".join(texts)

        return ""

    def _convert_to_feishu_message(
        self, response_text: str, original_message: FeishuMessage
    ) -> FeishuMessage:
        """Convert LLM response to FeishuMessage format."""
        return FeishuMessage(
            message_id="",
            chat=original_message.chat,
            text=response_text,
            content={"text": response_text},
        )

    def _get_chat_type(self, message: FeishuMessage) -> str:
        """Determine the chat type from a Feishu message.

        Returns "p2p" for private chats, "group" for group chats.
        """
        if message.chat and message.chat.type:
            chat_type = message.chat.type.lower()
            if chat_type == "p2p":
                return "p2p"
            return "group"
        return "p2p"

    def _process_with_llm(
        self, message: Message, conversation_id: str
    ) -> Optional[str]:
        conv_lock = self._get_conversation_lock(conversation_id)

        logger.info(f"开始处理 LLM 请求: conversation_id={conversation_id}")
        logger.info(f"用户消息长度: {len(message.content)} 字符")
        logger.debug(
            f"用户消息内容: {message.content[:200]}..."
            if len(message.content) > 200
            else f"用户消息内容: {message.content}"
        )

        with conv_lock:
            try:
                # 委托给 ChatCore 统一处理（记忆注入 + 上下文压缩 + LLM 调用 + 记忆提取）
                chat_core = self.app.get_chat_core()
                response = chat_core.send_message(
                    conversation_id=conversation_id,
                    message=message.content,
                )

                logger.info(
                    f"LLM 响应生成完成: conversation_id={conversation_id}, response_length={len(response)}"
                )
                logger.debug(
                    f"响应内容预览: {response[:200]}..."
                    if len(response) > 200
                    else f"响应内容: {response}"
                )
                return response

            except Exception as e:
                logger.error(f"处理 LLM 消息时发生错误: {e}", exc_info=True)
                return f"处理消息时发生错误: {str(e)}"

    @retry(
        max_retries=3,
        retry_delay=1.0,
        backoff_factor=2.0,
        exceptions=(httpx.HTTPError, httpx.TimeoutException),
    )
    def send_message(
        self,
        receive_id: str,
        msg_type: str,
        content: Dict[str, Any],
        receive_id_type: str = "chat_id",
    ) -> Dict[str, Any]:
        """Send a message via Feishu API.

        API Reference: https://open.feishu.cn/document/server-docs/im-v1/message/create

        Args:
            receive_id: The ID of the receiver (chat_id, user_id, or open_id)
            msg_type: Message type (text, post, image, etc.)
            content: Message content dictionary
            receive_id_type: Type of receive_id (chat_id, user_id, open_id, union_id)

        Returns:
            API response dictionary

        Raises:
            FeishuAdapterError: If sending fails
        """
        import json

        token = self._get_tenant_access_token()

        url = f"{self.FEISHU_API_BASE}/im/v1/messages"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        }

        content_str = (
            json.dumps(content, ensure_ascii=False)
            if isinstance(content, dict)
            else str(content)
        )

        payload = {
            "receive_id": receive_id,
            "msg_type": msg_type,
            "content": content_str,
        }

        params = {"receive_id_type": receive_id_type}

        try:
            response = self.http_client.post(
                url, headers=headers, json=payload, params=params
            )
            response.raise_for_status()
            result = response.json()

            if result.get("code") != 0:
                logger.error(f"Feishu API error: {result}")
                raise FeishuAdapterError(
                    f"Feishu API error: {result.get('msg', 'Unknown error')}"
                )

            return result

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error sending Feishu message: {e}")
            if e.response is not None:
                try:
                    error_detail = e.response.json()
                    logger.error(f"Feishu API error response: {error_detail}")
                except:
                    pass
            raise FeishuAdapterError(f"Failed to send message: {e}")

    @retry(
        max_retries=3,
        retry_delay=1.0,
        backoff_factor=2.0,
        exceptions=(httpx.HTTPError, httpx.TimeoutException),
    )
    def reply_to_message(
        self, message_id: str, content: str, msg_type: str = "text"
    ) -> Dict[str, Any]:
        """Reply to a specific message.

        Args:
            message_id: The ID of the message to reply to
            content: Reply content (text or content dict)
            msg_type: Message type (text, post, etc.)

        Returns:
            API response dictionary
        """
        import json

        token = self._get_tenant_access_token()

        url = f"{self.FEISHU_API_BASE}/im/v1/messages/{message_id}/reply"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        }

        content_dict = (
            {"text": content}
            if msg_type == "text"
            else (content if isinstance(content, dict) else {"text": content})
        )

        content_str = json.dumps(content_dict, ensure_ascii=False)

        payload = {
            "msg_type": msg_type,
            "content": content_str,
        }

        try:
            response = self.http_client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            result = response.json()

            if result.get("code") != 0:
                logger.error(f"Feishu API error: {result}")
                raise FeishuAdapterError(
                    f"Feishu API error: {result.get('msg', 'Unknown error')}"
                )

            return result

        except httpx.HTTPError as e:
            logger.error(f"HTTP error replying to Feishu message: {e}")
            raise FeishuAdapterError(f"Failed to reply to message: {e}")

    @retry(
        max_retries=3,
        retry_delay=1.0,
        backoff_factor=2.0,
        exceptions=(httpx.HTTPError, httpx.TimeoutException),
    )
    def _get_tenant_access_token(self) -> str:
        """Get tenant access token for Feishu API calls with caching.

        Thread-safe: Uses lock to prevent concurrent token requests.
        """
        with self._token_lock:
            if self._tenant_access_token and time.time() < self._token_expires_at:
                return self._tenant_access_token

            url = f"{self.FEISHU_API_BASE}/auth/v3/tenant_access_token/internal"
            payload = {
                "app_id": self.app_id,
                "app_secret": self.app_secret,
            }

            try:
                response = self.http_client.post(url, json=payload)
                response.raise_for_status()
                result = response.json()

                if result.get("code") != 0:
                    logger.error(f"Failed to get tenant access token: {result}")
                    raise FeishuAdapterError(
                        f"Auth failed: {result.get('msg', 'Unknown error')}"
                    )

                token = result["tenant_access_token"]
                self._tenant_access_token = token
                self._token_expires_at = (
                    int(time.time())
                    + result.get("expire", 7200)
                    - self.TOKEN_EXPIRY_BUFFER_SECONDS
                )

                logger.info("Successfully obtained Feishu tenant access token")
                return token

            except httpx.HTTPError as e:
                logger.error(f"HTTP error getting Feishu token: {e}")
                raise FeishuAdapterError(f"Failed to get access token: {e}")

    def close(self):
        """Close the HTTP client, thread pool, and clean up resources."""
        self._executor.shutdown(wait=True)
        if self._http_client:
            self._http_client.close()
            self._http_client = None
