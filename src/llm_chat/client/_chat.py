"""LLMClient 同步/流式聊天方法"""

import json
import logging
from typing import List, Dict, Any, Optional, Generator

import requests

from llm_chat.exceptions import LLMError, ContentModerationError
from llm_chat.client._logging import log_request_details

logger = logging.getLogger(__name__)


class LLMClientChatMixin:
    """同步 + 流式聊天 mixin

    依赖 LLMClientBase 提供的:
    - self.config, self.session, self.protocol
    """

    # ------------------------------------------------------------------
    # 同步聊天
    # ------------------------------------------------------------------

    def chat(
        self,
        message: str,
        history: Optional[List[Dict[str, str]]] = None,
        system_context: Optional[str] = None,
        **kwargs,
    ) -> str:
        if history is None:
            history = []

        messages = []

        if system_context:
            messages.append({"role": "system", "content": system_context})
            logger.debug(f"添加系统上下文: {len(system_context)} 字符")

        messages.extend(history)
        messages.append({"role": "user", "content": message})

        logger.info(
            f"发送聊天请求: message_length={len(message)}, "
            f"history_count={len(history)}, "
            f"has_system_context={system_context is not None}"
        )

        return self._send_chat_request(messages, **kwargs)

    def _send_chat_request(
        self, messages: List[Dict[str, str]], **kwargs
    ) -> str:
        url = self.protocol.get_chat_url()
        headers = self.protocol.get_headers()
        data = self.protocol.build_chat_request(messages, **kwargs)

        log_request_details(url, data, messages, kwargs)

        try:
            result = self._http_post_json_with_retry(url, data, headers, label="chat")
        except ContentModerationError as e:
            def build_request():
                u = self.protocol.get_chat_url()
                h = self.protocol.get_headers()
                d = self.protocol.build_chat_request(messages, **kwargs)
                return u, d, h
            result = self._handle_content_moderation_fallback(e, build_request, "chat")

        response_text = self.protocol.parse_chat_response(result)
        logger.info(f"聊天响应: length={len(response_text)}")
        return response_text

    # ------------------------------------------------------------------
    # 流式聊天
    # ------------------------------------------------------------------

    def chat_stream(
        self,
        message: str,
        history: Optional[List[Dict[str, str]]] = None,
        system_context: Optional[str] = None,
        **kwargs,
    ) -> Generator[str, None, None]:
        if history is None:
            history = []

        messages = []

        if system_context:
            messages.append({"role": "system", "content": system_context})
            logger.debug(f"添加系统上下文: {len(system_context)} 字符")

        messages.extend(history)
        messages.append({"role": "user", "content": message})

        logger.info(
            f"发送流式聊天请求: message_length={len(message)}, "
            f"history_count={len(history)}, "
            f"has_system_context={system_context is not None}"
        )

        yield from self._send_chat_request_stream(messages, **kwargs)

    def _send_chat_request_stream(
        self, messages: List[Dict[str, str]], **kwargs
    ) -> Generator[str, None, None]:
        url = self.protocol.get_chat_url()
        headers = self.protocol.get_headers()
        data = self.protocol.build_chat_request(messages, stream=True, **kwargs)

        log_request_details(url, data, messages, kwargs)
        logger.info("(流式请求)")

        stream_usage = None  # API 返回的真实 usage（最后 chunk）
        total_output_chars = 0

        try:
            response = self.session.post(
                url, json=data, headers=headers, stream=True
            )
            response.raise_for_status()

            logger.debug(f"流式响应开始: status_code={response.status_code}")

            chunk_count = 0
            for line in response.iter_lines():
                if not line:
                    continue

                line_text = line.decode("utf-8")

                if line_text.startswith("data: "):
                    data_str = line_text[6:]

                    if data_str == "[DONE]":
                        logger.info(f"流式响应完成: chunks={chunk_count}")
                        break

                    try:
                        chunk = json.loads(data_str)
                        # 捕获 API 返回的真实 usage
                        if "usage" in chunk and chunk["usage"]:
                            stream_usage = chunk["usage"]
                        content = self.protocol.parse_stream_chunk(chunk)
                        if content:
                            chunk_count += 1
                            total_output_chars += len(content)
                            yield content
                    except json.JSONDecodeError:
                        continue

            # 流式完成：记录 token 消耗
            self._record_stream_tokens(stream_usage, total_output_chars, messages)

        except requests.RequestException as e:
            error_msg = str(e)
            if hasattr(e, "response") and e.response is not None:
                try:
                    error_detail = e.response.json()
                    error_msg = f"{error_msg}\n详情: {error_detail}"
                except Exception:
                    error_msg = f"{error_msg}\n响应内容: {e.response.text}"
            logger.error(f"流式请求失败: {error_msg}")
            raise LLMError(f"API 请求失败: {error_msg}")

    def _record_stream_tokens(
        self, stream_usage: Optional[dict], total_output_chars: int,
        messages: List[Dict[str, str]]
    ) -> None:
        """记录流式 token 消耗，优先使用 API 返回的真实 usage。"""
        try:
            from llm_chat.utils.observability import get_observability
            from llm_chat.utils.token_counter import count_messages_tokens
            obs = get_observability()
            if stream_usage and isinstance(stream_usage, dict):
                prompt_tokens = stream_usage.get("prompt_tokens", 0)
                completion_tokens = stream_usage.get("completion_tokens", 0)
                total_tokens = stream_usage.get("total_tokens", prompt_tokens + completion_tokens)
                logger.debug(
                    f"使用 API 返回的真实 usage: prompt={prompt_tokens} "
                    f"completion={completion_tokens} total={total_tokens}"
                )
            else:
                prompt_tokens = count_messages_tokens(messages, self.config.llm.model)
                completion_tokens = max(total_output_chars // 2, 1)
                total_tokens = prompt_tokens + completion_tokens
                logger.debug(
                    f"使用估算 usage: prompt={prompt_tokens} "
                    f"completion={completion_tokens} (chars={total_output_chars})"
                )
            obs.increment("tokens.prompt", prompt_tokens)
            obs.increment("tokens.completion", completion_tokens)
            obs.increment("tokens.total", total_tokens)
            obs.increment(f"tokens.{self.config.llm.model}", total_tokens)
        except Exception:
            logger.debug("token observability increment failed", exc_info=True)
