"""LLMClient 同步/流式聊天方法"""

import json
import logging
import time
from typing import List, Dict, Any, Optional, Generator

import requests

from llm_chat.exceptions import LLMError
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

        for i in range(self.config.llm.max_retries):
            try:
                response = self.session.post(url, json=data, headers=headers)
                response.raise_for_status()
                result = response.json()

                # Track token usage via observability
                usage = result.get("usage", {})
                if usage:
                    from llm_chat.utils.observability import get_observability
                    obs = get_observability()
                    obs.increment("tokens.prompt", usage.get("prompt_tokens", 0))
                    obs.increment("tokens.completion", usage.get("completion_tokens", 0))
                    obs.increment("tokens.total", usage.get("total_tokens", 0))
                    model = self.config.llm.model
                    obs.increment(f"tokens.{model}", usage.get("total_tokens", 0))

                response_text = self.protocol.parse_chat_response(result)
                logger.info(f"聊天响应: length={len(response_text)}")

                return response_text
            except requests.RequestException as e:
                if i == self.config.llm.max_retries - 1:
                    error_msg = str(e)
                    if hasattr(e, "response") and e.response is not None:
                        try:
                            error_detail = e.response.json()
                            error_msg = f"{error_msg}\n详情: {error_detail}"
                        except Exception:
                            error_msg = f"{error_msg}\n响应内容: {e.response.text}"
                    logger.error(
                        f"API 请求失败(重试 {i + 1}/{self.config.llm.max_retries}): "
                        f"{error_msg}"
                    )
                    raise LLMError(f"API 请求失败: {error_msg}")
                logger.warning(f"请求失败，{i + 1}秒后重试: {e}")
                time.sleep(1)

        return ""

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
                        content = self.protocol.parse_stream_chunk(chunk)
                        if content:
                            chunk_count += 1
                            yield content
                    except json.JSONDecodeError:
                        continue

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
