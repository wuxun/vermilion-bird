"""LLMClient 同步工具调用方法"""

import json
import logging
import time
from typing import List, Dict, Any, Optional, Generator

import requests

from llm_chat.exceptions import LLMError
from llm_chat.utils.observability import observe, get_observability, llm_call_completed

logger = logging.getLogger(__name__)


class LLMClientToolsMixin:
    """同步工具调用 + chat_stream_with_tools mixin

    依赖 LLMClientBase 提供的:
    - self.config, self.session, self.protocol
    - self._tool_registry, self._tool_executor, self._tool_executor_instance
    - self.execute_builtin_tool()
    """

    # ------------------------------------------------------------------
    # 同步工具调用
    # ------------------------------------------------------------------

    @observe("llm.chat_with_tools")
    def chat_with_tools(
        self,
        message: str,
        tools: List[Dict[str, Any]],
        history: Optional[List[Dict[str, Any]]] = None,
        **kwargs,
    ) -> str:
        if history is None:
            history = []

        messages = history.copy()
        messages.append({"role": "user", "content": message})

        logger.info(
            f"发送带工具的聊天请求: tools={[t['function']['name'] for t in tools]}"
        )

        return self._send_chat_request_with_tools(messages, tools, **kwargs)

    @observe("llm.chat_with_tools_request")
    def _send_chat_request_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        max_iterations: int = 100,
        **kwargs,
    ) -> str:
        if not self.protocol.supports_tools():
            logger.warning("当前协议不支持工具调用，使用普通聊天")
            return self._send_chat_request(messages, **kwargs)

        url = self.protocol.get_chat_url()
        headers = self.protocol.get_headers()

        current_messages = messages.copy()

        logger.info(f"开始带工具的聊天迭代: max_iterations={max_iterations}")

        for iteration in range(max_iterations):
            data = self.protocol.build_chat_request_with_tools(
                current_messages, tools, **kwargs
            )

            logger.debug(f"迭代 {iteration + 1}: 发送请求")

            for i in range(self.config.llm.max_retries):
                try:
                    response = self.session.post(url, json=data, headers=headers)
                    response.raise_for_status()
                    result = response.json()
                    # 记录 token 消耗
                    usage = result.get("usage", {})
                    if usage:
                        obs = get_observability()
                        obs.increment("tokens.prompt", usage.get("prompt_tokens", 0))
                        obs.increment("tokens.completion", usage.get("completion_tokens", 0))
                        obs.increment("tokens.total", usage.get("total_tokens", 0))
                    break
                except requests.RequestException as e:
                    if i == self.config.llm.max_retries - 1:
                        logger.error(f"请求失败(重试耗尽): {e}")
                        raise LLMError(f"API 请求失败: {e}")
                    logger.warning(f"请求失败，{i + 1}秒后重试: {e}")
                    time.sleep(1)
            else:
                continue

            if not self.protocol.has_tool_calls(result):
                response_text = self.protocol.parse_chat_response(result)
                logger.info(
                    f"聊天完成: iterations={iteration + 1}, "
                    f"response_length={len(response_text)}"
                )
                return response_text

            assistant_message = (
                self.protocol.get_assistant_message_from_response(result)
            )
            current_messages.append(assistant_message)

            tool_calls = self.protocol.parse_tool_calls(result)

            logger.info(
                f"迭代 {iteration + 1}: 检测到 {len(tool_calls)} 个工具调用"
            )

            for tool_call in tool_calls:
                logger.info(
                    f"工具调用: {tool_call.name}, "
                    f"参数: {json.dumps(tool_call.arguments, ensure_ascii=False)[:100]}..."
                )

                tool_result = None
                is_error = False

                if self._tool_registry.has_tool(tool_call.name):
                    try:
                        tool_result = self.execute_builtin_tool(
                            tool_call.name, tool_call.arguments
                        )
                        is_error = False
                        if tool_result is None:
                            tool_result = "工具执行返回空结果"
                            logger.warning(f"工具 {tool_call.name} 返回 None")
                        else:
                            logger.info(
                                f"工具 {tool_call.name} 执行成功, "
                                f"结果长度: {len(tool_result)}"
                            )
                    except Exception as e:
                        tool_result = str(e)
                        is_error = True
                        logger.error(f"工具 {tool_call.name} 执行失败: {e}")
                elif self._tool_executor:
                    try:
                        tool_result = self._tool_executor(
                            tool_call.name, tool_call.arguments
                        )
                        is_error = False
                        if tool_result is None:
                            tool_result = "工具执行返回空结果"
                            logger.warning(f"工具 {tool_call.name} 返回 None")
                        else:
                            logger.info(
                                f"工具 {tool_call.name} 执行成功(外部执行器)"
                            )
                    except Exception as e:
                        tool_result = str(e)
                        is_error = True
                        logger.error(
                            f"工具 {tool_call.name} 执行失败(外部执行器): {e}"
                        )
                else:
                    tool_result = (
                        f"Error: No tool executor configured for {tool_call.name}"
                    )
                    is_error = True
                    logger.error(f"没有找到工具 {tool_call.name} 的执行器")

                # Fire tool_call_hook for observability (sub-agent panel etc.)
                if self._tool_call_hook:
                    try:
                        args_safe = tool_call.arguments if isinstance(tool_call.arguments, dict) else {}
                        self._tool_call_hook(tool_call.name, args_safe, tool_result or "")
                    except Exception:
                        pass

                tool_message = self.protocol.build_tool_result_message(
                    tool_call, tool_result, is_error
                )
                current_messages.append(tool_message)

        logger.warning(f"达到最大迭代次数 {max_iterations}")
        return self.protocol.parse_chat_response(result)
