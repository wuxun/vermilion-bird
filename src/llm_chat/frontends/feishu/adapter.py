"""FeishuAdapter - Bridge between Feishu webhook events and internal LLM processing."""

import logging
import time
from typing import Any, Dict, Optional

import httpx

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
    """

    FEISHU_API_BASE = "https://open.feishu.cn/open-apis"
    TOKEN_EXPIRY_BUFFER_SECONDS = 300

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
    ):
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

    @property
    def http_client(self) -> httpx.Client:
        if self._http_client is None:
            self._http_client = httpx.Client(timeout=30.0)
        return self._http_client

    def handle_event(self, event: FeishuEvent) -> Optional[FeishuMessage]:
        """Process a Feishu event and return a response message.

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
        """Process a message through the LLM using App's conversation manager."""
        try:
            conversation = self.app.get_conversation(conversation_id)

            if self.app.config.enable_tools and self.app.has_tools_available():
                tools = self.app.get_available_tools()
                if tools:
                    response = self.app.client.chat_with_tools(
                        message.content, tools, history=conversation.get_history()
                    )
                else:
                    response = conversation.send_message(message.content)
            else:
                response = conversation.send_message(message.content)

            return response

        except Exception as e:
            logger.error(f"Error processing message with LLM: {e}", exc_info=True)
            return f"处理消息时发生错误: {str(e)}"

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
        token = self._get_tenant_access_token()

        url = f"{self.FEISHU_API_BASE}/im/v1/messages"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        }

        payload = {
            "receive_id": receive_id,
            "receive_id_type": receive_id_type,
            "msg_type": msg_type,
            "content": content,
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
            logger.error(f"HTTP error sending Feishu message: {e}")
            raise FeishuAdapterError(f"Failed to send message: {e}")

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

        payload = {
            "msg_type": msg_type,
            "content": content_dict,
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

    def _get_tenant_access_token(self) -> str:
        """Get tenant access token for Feishu API calls with caching."""
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
        """Close the HTTP client and clean up resources."""
        if self._http_client:
            self._http_client.close()
            self._http_client = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
