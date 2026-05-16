"""LLMClient 流式工具调用方法"""

import json
import logging
import re
from typing import List, Dict, Any, Optional, Generator

import requests

from llm_chat.exceptions import LLMError
from llm_chat.utils.token_counter import count_messages_tokens, get_context_limit
from llm_chat.client._logging import log_request_details

logger = logging.getLogger(__name__)


def _repair_json(args_str: str) -> str:
    """修复流式响应中被截断的 JSON 参数。

    流式 tool call 的 arguments 按 chunk 拼接，但可能因 max_tokens
    限制而被截断。此函数尝试修复常见的截断模式。

    返回修复后的 JSON 字符串，若无法修复则返回 '{}'。
    """
    if not args_str or not args_str.strip():
        return "{}"

    original = args_str.strip()

    # ── 策略 1：补全括号和引号 ──
    repaired = original

    # 计数未闭合的字符串（奇数个引号意味着有未闭合字符串）
    # 简化：计算 " 的奇偶性
    in_string = False
    escaped = False
    for ch in repaired:
        if escaped:
            escaped = False
            continue
        if ch == '\\':
            escaped = True
            continue
        if ch == '"':
            in_string = not in_string

    # 如果卡在字符串中间，闭合它
    if in_string:
        repaired += '"'

    # 补全缺失的 ] 和 }
    open_brackets = repaired.count('[') - repaired.count(']')
    open_braces = repaired.count('{') - repaired.count('}')

    # 先闭合数组，再闭合对象
    repaired += ']' * max(0, open_brackets)
    repaired += '}' * max(0, open_braces)

    try:
        json.loads(repaired)
        return repaired
    except json.JSONDecodeError:
        pass

    # ── 策略 2：截断到最后完整键值对 ──
    # 找到最后一个完整的 ", 对
    # 正则匹配: "key": value (value 可以是字符串/数字/对象/数组)
    last_complete = None
    # 简单方法：从后往前找最后一个 "key": 后面跟合法 JSON 值的模式
    # 更稳健：找最后一个后面跟着完整 JSON 值的 :
    idx = len(original)
    while idx > 0:
        idx = original.rfind(',', 0, idx)
        if idx == -1:
            break
        # 看从开头到 idx 的部分，加上闭合括号
        candidate = original[:idx]
        # 补括号
        c_open_brackets = candidate.count('[') - candidate.count(']')
        c_open_braces = candidate.count('{') - candidate.count('}')
        candidate += ']' * max(0, c_open_brackets)
        candidate += '}' * max(0, c_open_braces)
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            continue

    # ── 策略 3：只保留第一个完整键值对（对 submit_decision_card 至少保留 title） ──
    # 找第一个 , 处截断
    first_comma = original.find(',')
    if first_comma > 0:
        candidate = original[:first_comma]
        c_open_brackets = candidate.count('[') - candidate.count(']')
        c_open_braces = candidate.count('{') - candidate.count('}')
        candidate += ']' * max(0, c_open_brackets)
        candidate += '}' * max(0, c_open_braces)
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            pass

    return "{}"


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
        cancel_event=None,
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
        stream_usage = None  # 从流式最后 chunk 提取的真实 usage（优先）

        for iteration in range(max_iterations):
            if cancel_event and cancel_event.is_set():
                logger.info("Stream cancelled during tool iteration")
                return

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

                for line in response.iter_lines():
                    if cancel_event and cancel_event.is_set():
                        logger.info("Stream cancelled mid-response")
                        return

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
                            # 捕获 API 返回的真实 usage（通常出现在最后 chunk）
                            if "usage" in chunk and chunk["usage"]:
                                stream_usage = chunk["usage"]
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
                    repaired = _repair_json(args_str)
                    if repaired != "{}":
                        logger.info(
                            f"流式工具调用 JSON 已修复: "
                            f"{args_str[:80]}... → {repaired[:80]}..."
                        )
                    else:
                        logger.warning(
                            f"流式工具调用参数不完整，无法修复: {args_str[:100]}..."
                        )
                    tc["function"]["arguments"] = repaired

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
                # submit_decision_card 不走正常 tool execute，由卡片构建逻辑处理
                if tool_name != "submit_decision_card":
                    yield ("tool_call_start", tool_name, tool_args)

            tool_results = self._tool_executor_instance.execute_tools_parallel(
                [tc for tc in tool_calls if tc["function"]["name"] != "submit_decision_card"]
            )
            logger.info(f"工具执行结果数量: {len(tool_results)}")

            # 从 submit_decision_card 的调用参数直接构建卡片
            # （不依赖 tool execute，避免被 MCP 同名工具覆盖）
            card_submitted = False
            for tc in tool_calls:
                if tc["function"]["name"] == "submit_decision_card":
                    try:
                        args = json.loads(tc["function"]["arguments"])
                        if args.get("title") and args.get("options"):
                            from llm_chat.decision.schema import DecisionCard, DecisionOption
                            import llm_chat.decision.submit_tool as st
                            opts = [DecisionOption(
                                id=o.get("id", ""),
                                label=o.get("label", ""),
                                description=o.get("description"),
                                expected_effect=o.get("expected_effect"),
                                risk=o.get("risk"),
                                confidence=float(o.get("confidence", 0.5)),
                            ) for o in args["options"]]
                            card = DecisionCard(
                                title=args["title"],
                                context=args.get("context") or None,
                                options=opts,
                                recommendation=args.get("recommendation") or None,
                                sources=args.get("sources", []),
                            )
                            st.submit_card(card)
                            tool_result_text = f"卡片已提交: {card.title}"
                            card_submitted = True
                        else:
                            missing = []
                            if not args.get("title"):
                                missing.append("title")
                            if not args.get("options"):
                                missing.append("options")
                            tool_result_text = (
                                f"卡片参数不完整，缺少: {', '.join(missing)}。"
                                f"请重新调用 submit_decision_card 并填写完整的 title 和 options 参数。"
                                f"options 至少需要 2 个选项，每个选项需包含 id, label, confidence 字段。"
                            )
                    except Exception as e:
                        logger.warning(f"从 submit_decision_card 参数构建卡片失败: {e}")
                        tool_result_text = (
                            f"卡片构建失败: {e}。"
                            f"请重新调用 submit_decision_card 并确保参数格式正确。"
                        )
                    # 将结果反馈给 LLM
                    current_messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "content": tool_result_text,
                    })

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

            # submit_decision_card 提交成功后终止迭代
            if card_submitted:
                logger.info(f"卡片已提交，终止工具循环 (迭代 {iteration + 1})")
                break

        # 流式完成：记录 token 消耗（委托给共享 helper）
        self._record_stream_tokens(stream_usage, total_output_chars, current_messages)

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
