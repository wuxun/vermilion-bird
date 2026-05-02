"""LLMClient 流式工具调用方法"""

import json
import logging
from typing import List, Dict, Any, Optional, Generator

import requests

from llm_chat.exceptions import LLMError
from llm_chat.utils.token_counter import count_messages_tokens, get_context_limit
from llm_chat.client._logging import log_request_details

logger = logging.getLogger(__name__)


class LLMClientStreamToolsMixin:
    """流式工具调用 mixin

    依赖 LLMClientBase 提供的:
    - self.config, self.session, self.protocol
    - self._tool_registry, self._tool_executor_instance
    - self.execute_builtin_tool()
    """

    # ------------------------------------------------------------------
    # 流式工具聊天
    # ------------------------------------------------------------------

    def chat_stream_with_tools(
        self,
        message: str,
        tools: List[Dict[str, Any]],
        history: Optional[List[Dict[str, Any]]] = None,
        system_context: Optional[str] = None,
        max_iterations: int = 100,
        **kwargs,
    ) -> Generator[Any, None, None]:
        if not self.protocol.supports_tools():
            logger.warning("当前协议不支持工具调用，使用普通流式聊天")
            yield from self.chat_stream(
                message, history, system_context=system_context, **kwargs
            )
            return

        if history is None:
            history = []

        current_messages = []

        if system_context:
            current_messages.append({"role": "system", "content": system_context})

        current_messages.extend(history)
        current_messages.append({"role": "user", "content": message})

        logger.info(
            f"开始带工具的流式聊天: "
            f"tools={[t['function']['name'] for t in tools]}, "
            f"max_iterations={max_iterations}"
        )

        total_output_chars = 0  # 累计输出字符数，用于 token 估算

        for iteration in range(max_iterations):
            url = self.protocol.get_chat_url()
            headers = self.protocol.get_headers()
            data = self.protocol.build_chat_request_with_tools(
                current_messages, tools, stream=True, **kwargs
            )

            log_request_details(url, data, current_messages, kwargs)
            logger.info(f"(流式请求, 迭代 {iteration + 1})")

            full_text = ""
            reasoning_text = ""  # DeepSeek R1 / OpenAI o1 思考内容
            tool_calls_data = []

            try:
                response = self.session.post(
                    url, json=data, headers=headers, stream=True
                )
                response.raise_for_status()

                logger.debug(f"响应状态码: {response.status_code}")

                for line in response.iter_lines():
                    if not line:
                        continue

                    line_text = line.decode("utf-8")

                    if line_text.startswith("data: "):
                        data_str = line_text[6:]

                        if data_str == "[DONE]":
                            logger.debug("流式响应结束")
                            break

                        try:
                            chunk = json.loads(data_str)
                            content = self.protocol.parse_stream_chunk(chunk)
                            if content:
                                full_text += content
                                yield content

                            # 收集推理内容 (DeepSeek R1 / OpenAI o1)
                            if hasattr(self.protocol, "parse_stream_reasoning_content"):
                                rc = self.protocol.parse_stream_reasoning_content(chunk)
                                if rc:
                                    reasoning_text += rc

                            chunk_tool_calls = self._parse_stream_tool_calls(chunk)
                            if chunk_tool_calls:
                                tool_calls_data.extend(chunk_tool_calls)

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
                logger.error(f"API 请求失败: {error_msg}")
                raise LLMError(f"API 请求失败: {error_msg}")

            if not tool_calls_data:
                logger.info(f"流式聊天完成: response_length={len(full_text)}")
                total_output_chars += len(full_text)
                return

            tool_calls = self._merge_tool_calls(tool_calls_data)

            # 验证流式拼接的工具调用参数是否为合法 JSON
            for tc in tool_calls:
                args_str = tc["function"].get("arguments", "{}")
                try:
                    json.loads(args_str)
                except json.JSONDecodeError:
                    logger.warning(
                        f"流式工具调用参数不完整，尝试修复: {args_str[:100]}..."
                    )
                    tc["function"]["arguments"] = "{}"

            logger.info(f"检测到 {len(tool_calls)} 个工具调用")

            assistant_message = {
                "role": "assistant",
                "content": full_text if full_text else "",
            }
            # 保留推理内容 — DeepSeek R1 要求 reasoning_content 必须传回
            if reasoning_text:
                assistant_message["reasoning_content"] = reasoning_text
            if tool_calls:
                assistant_message["tool_calls"] = tool_calls
            current_messages.append(assistant_message)

            for tc in tool_calls:
                tool_name = tc["function"]["name"]
                tool_args = tc["function"].get("arguments", "{}")
                yield ("tool_call_start", tool_name, tool_args)

            tool_results = self._tool_executor_instance.execute_tools_parallel(
                tool_calls
            )
            logger.info(f"工具执行结果数量: {len(tool_results)}")

            for result in tool_results:
                logger.info(
                    f"处理工具结果: tool_call_id={result.get('tool_call_id')}, "
                    f"content_type={type(result.get('content'))}, "
                    f"content_is_none={result.get('content') is None}"
                )

                tool_name = "unknown"
                tool_args = "{}"
                for tc in tool_calls:
                    if tc["id"] == result["tool_call_id"]:
                        tool_name = tc["function"]["name"]
                        tool_args = tc["function"].get("arguments", "{}")
                        break

                content = result.get("content")
                if content is None:
                    content = "工具返回空结果"
                    logger.warning(f"工具 {tool_name} 返回 content 为 None")

                tool_message = {
                    "role": "tool",
                    "tool_call_id": result["tool_call_id"],
                    "content": content,
                }
                current_messages.append(tool_message)

                yield ("tool_call_end", tool_name, tool_args, str(content)[:500])

            current_tokens = count_messages_tokens(
                current_messages, self.config.llm.model
            )
            context_limit = get_context_limit(self.config.llm.model)
            yield ("context_update", current_tokens, context_limit)

        # 流式完成：估算并记录 token 消耗
        try:
            from llm_chat.utils.observability import get_observability
            obs = get_observability()
            input_tokens = count_messages_tokens(current_messages, self.config.llm.model)
            output_est = max(total_output_chars // 2, 1)
            obs.increment("tokens.prompt", input_tokens)
            obs.increment("tokens.completion", output_est)
            obs.increment("tokens.total", input_tokens + output_est)
            obs.increment(f"tokens.{self.config.llm.model}", input_tokens + output_est)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 流式工具调用解析 helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_stream_tool_calls(
        chunk: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        choices = chunk.get("choices", [])
        if not choices:
            return []

        delta = choices[0].get("delta", {})
        tool_calls = delta.get("tool_calls", [])

        return tool_calls

    @staticmethod
    def _merge_tool_calls(
        tool_calls_data: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        merged = {}

        for tc in tool_calls_data:
            idx = tc.get("index", 0)
            if idx not in merged:
                merged[idx] = {
                    "id": tc.get("id", ""),
                    "type": tc.get("type", "function"),
                    "function": {"name": "", "arguments": ""},
                }

            if tc.get("id"):
                merged[idx]["id"] = tc["id"]

            func = tc.get("function", {})
            if func.get("name"):
                merged[idx]["function"]["name"] = func["name"]
            if func.get("arguments"):
                merged[idx]["function"]["arguments"] += func["arguments"]

        return list(merged.values())
