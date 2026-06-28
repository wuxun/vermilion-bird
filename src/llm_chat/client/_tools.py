"""LLMClient 同步工具调用方法"""

import json
import logging
from typing import List, Dict, Any, Optional, Generator

from llm_chat.exceptions import ContentModerationError
from llm_chat.utils.observability import observe, get_observability, llm_call_completed

logger = logging.getLogger(__name__)


class LLMClientToolsMixin:
    """同步工具调用 + chat_stream_with_tools mixin

    依赖 LLMClientBase 提供的:
    - self.config, self.session, self.protocol
    - self._tool_registry, self._tool_executor_instance
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
        system_context: Optional[str] = None,
        **kwargs,
    ) -> str:
        if history is None:
            history = []

        messages = []
        if system_context:
            messages.append({"role": "system", "content": system_context})
        messages.extend(history)
        messages.append({"role": "user", "content": message})

        logger.info(
            f"发送带工具的聊天请求: tools={[t['function']['name'] for t in tools]}"
        )

        return self._send_chat_request_with_tools(messages, tools, **kwargs)

    def chat_single_with_tools(
        self,
        message: str,
        tools: List[Dict[str, Any]],
        history: Optional[List[Dict[str, Any]]] = None,
        system_context: Optional[str] = None,
        messages_override: Optional[List[Dict[str, Any]]] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Make a single LLM call with tools, return raw result.

        Unlike chat_with_tools(), this does NOT loop for tool execution.
        Returns {"text": str | None, "tool_calls": list | None, "raw": dict}.

        This enables StateGraph-level tool loops where each iteration
        is a separate graph node execution.

        Args:
            messages_override: If provided, use these messages directly
                (for re-entrant calls after tool execution).
        """
        if messages_override:
            messages = messages_override
        else:
            if history is None:
                history = []
            messages = []
            if system_context:
                messages.append({"role": "system", "content": system_context})
            messages.extend(history)
            messages.append({"role": "user", "content": message})

        if not self.protocol.supports_tools():
            url = self.protocol.get_chat_url()
            headers = self.protocol.get_headers()
            data = self.protocol.build_chat_request(messages, **kwargs)
            result = self._http_post_json_with_retry(url, data, headers)
            return {"text": self.protocol.parse_chat_response(result), "tool_calls": None}

        url = self.protocol.get_chat_url()
        headers = self.protocol.get_headers()
        data = self.protocol.build_chat_request_with_tools(messages, tools, **kwargs)

        try:
            result = self._http_post_json_with_retry(url, data, headers, label="tools single")
        except ContentModerationError as e:
            def _build_req():
                u = self.protocol.get_chat_url()
                h = self.protocol.get_headers()
                d = self.protocol.build_chat_request_with_tools(messages, tools, **kwargs)
                return u, d, h
            result = self._handle_content_moderation_fallback(e, _build_req, "tools single")

        if not self.protocol.has_tool_calls(result):
            return {"text": self.protocol.parse_chat_response(result), "tool_calls": None}

        tool_calls = self.protocol.parse_tool_calls(result)
        assistant_message = self.protocol.get_assistant_message_from_response(result)

        return {
            "text": None,
            "tool_calls": tool_calls,
            "assistant_message": assistant_message,
        }

    @observe("llm.chat_with_tools_request")
    def _send_chat_request_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        max_iterations: int = 10,
        **kwargs,
    ) -> str:
        if not self.protocol.supports_tools():
            logger.warning("当前协议不支持工具调用，使用普通聊天")
            return self._send_chat_request(messages, **kwargs)

        url = self.protocol.get_chat_url()
        headers = self.protocol.get_headers()

        current_messages = messages.copy()

        empty_call_streak = 0  # 连续空参数调用计数

        logger.info(f"开始带工具的聊天迭代: max_iterations={max_iterations}")

        for iteration in range(max_iterations):
            data = self.protocol.build_chat_request_with_tools(
                current_messages, tools, **kwargs
            )

            logger.debug(f"迭代 {iteration + 1}: 发送请求")

            try:
                result = self._http_post_json_with_retry(
                    url, data, headers, label=f"tools iter {iteration+1}"
                )
            except ContentModerationError as e:
                def _build_req():
                    u = self.protocol.get_chat_url()
                    h = self.protocol.get_headers()
                    d = self.protocol.build_chat_request_with_tools(
                        current_messages, tools, **kwargs
                    )
                    return u, d, h
                result = self._handle_content_moderation_fallback(
                    e, _build_req, f"tools iter {iteration+1}"
                )

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

            # ── 卡死检测：同一工具连续空参数调用 ≥3 次 → 终止 ──
            all_empty = all(
                not (isinstance(tc.arguments, dict) and tc.arguments)
                for tc in tool_calls
            )
            if all_empty and len(tool_calls) == 1:
                empty_call_streak += 1
                if empty_call_streak >= 3:
                    logger.warning(
                        f"工具调用卡死：{tool_calls[0].name} 连续 {empty_call_streak} 次空参数，终止循环"
                    )
                    current_messages.append({
                        "role": "tool",
                        "tool_call_id": getattr(tool_calls[0], 'id', f"tc_{tool_calls[0].name}"),
                        "content": (
                            f"你已连续 {empty_call_streak} 次调用 {tool_calls[0].name} 但未提供任何参数。"
                            f"请直接用文字回复，不要再调用工具。"
                        ),
                    })
                    # 最后再给 LLM 一次机会输出文字
                    data = self.protocol.build_chat_request_with_tools(
                        current_messages, tools, **kwargs
                    )
                    try:
                        result = self._http_post_json_with_retry(
                            url, data, headers, label=f"tools stuck recovery"
                        )
                    except ContentModerationError as e:
                        def _build_recovery_req():
                            u = self.protocol.get_chat_url()
                            h = self.protocol.get_headers()
                            d = self.protocol.build_chat_request_with_tools(
                                current_messages, tools, **kwargs
                            )
                            return u, d, h
                        result = self._handle_content_moderation_fallback(
                            e, _build_recovery_req, "tools stuck recovery"
                        )
                    return self.protocol.parse_chat_response(result)
            else:
                empty_call_streak = 0  # 有参数或不同工具 → 重置

            # ── 处理工具调用 ──
            # submit_decision_card 成功后设置此标志，终止迭代循环
            card_submitted = False

            for tool_call in tool_calls:
                logger.info(
                    f"工具调用: {tool_call.name}, "
                    f"参数: {json.dumps(tool_call.arguments, ensure_ascii=False)[:100]}..."
                )

                # 从 submit_decision_card 参数直接构建卡片
                if tool_call.name == "submit_decision_card":
                    tool_call_id = tool_call.id if hasattr(tool_call, 'id') else f"tc_{tool_call.name}"
                    try:
                        args_dict = tool_call.arguments if isinstance(tool_call.arguments, dict) else {}
                        if args_dict.get("title") and args_dict.get("options"):
                            from llm_chat.decision.schema import DecisionCard, DecisionOption
                            import llm_chat.decision.submit_tool as st
                            option_ids = ["A", "B", "C", "D"]
                            rec = args_dict.get("recommendation")
                            opts = [DecisionOption(
                                id=o.get("id") or (option_ids[i] if i < len(option_ids) else f"O{i+1}"),
                                label=o.get("label", ""),
                                description=o.get("description"),
                                confidence=0.85 if rec and (o.get("id") or option_ids[i]) == rec else 0.7,
                            ) for i, o in enumerate(args_dict["options"])]
                            card = DecisionCard(
                                title=args_dict["title"],
                                context=args_dict.get("context") or None,
                                options=opts,
                                recommendation=args_dict.get("recommendation") or None,
                                sources=args_dict.get("sources", []),
                            )
                            st.submit_card(card)
                            tool_result_text = f"卡片已提交: {card.title}"
                            card_submitted = True
                        else:
                            missing = []
                            if not args_dict.get("title"):
                                missing.append("title")
                            if not args_dict.get("options"):
                                missing.append("options")
                            if missing:
                                tool_result_text = (
                                    f"卡片参数不完整，缺少: {', '.join(missing)}。"
                                    f"\n\n正确的参数格式：\n"
                                    f'{{"title": "🎯 卡片标题", "context": "背景说明", '
                                    f'"options": [{{"label": "选项A", "description": "说明"}}, '
                                    f'{{"label": "选项B", "description": "说明"}}]}}'
                                    f"\n\n每个选项只需要 label（必填）和 description（可选）。"
                                    f"id 自动分配为 A/B/C。请严格按照此格式重新调用 submit_decision_card。"
                                )
                            else:
                                tool_result_text = (
                                    f"卡片参数格式有误。正确的参数格式：\n"
                                    f'{{"title": "🎯 卡片标题", "context": "背景说明", '
                                    f'"options": [{{"label": "选项A"}}, {{"label": "选项B"}}]}}'
                                )
                    except Exception as e:
                        logger.warning(f"从 submit_decision_card 参数构建卡片失败(同步): {e}")
                        tool_result_text = (
                            f"卡片构建失败: {e}。"
                            f"请重新调用 submit_decision_card 并确保参数格式正确。"
                        )
                    # 将结果反馈给 LLM
                    current_messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "content": tool_result_text,
                    })
                    continue

                tool_result = None
                # 使用 ToolExecutor 统一执行（含重试+超时），与流式路径一致
                tool_call_id = tool_call.id if hasattr(tool_call, 'id') else f"tc_{tool_call.name}"
                args_dict = tool_call.arguments if isinstance(tool_call.arguments, dict) else {}
                result = self._tool_executor_instance.execute_single_tool(
                    tool_call.name, args_dict, tool_call_id
                )
                tool_result = result.get("content", "")
                is_error = result.get("is_error", False)

                if is_error:
                    logger.error(f"工具 {tool_call.name} 执行失败: {tool_result}")
                else:
                    if tool_result is None:
                        tool_result = "工具执行返回空结果"
                        logger.warning(f"工具 {tool_call.name} 返回 None")
                    else:
                        logger.info(
                            f"工具 {tool_call.name} 执行成功, "
                            f"结果长度: {len(str(tool_result))}"
                        )

                # Fire tool_call_hook for observability (sub-agent panel etc.)
                if self._tool_call_hook:
                    try:
                        args_safe = tool_call.arguments if isinstance(tool_call.arguments, dict) else {}
                        self._tool_call_hook(tool_call.name, args_safe, tool_result or "")
                    except Exception:
                        logger.debug("tool_call_hook failed", exc_info=True)

                tool_message = self.protocol.build_tool_result_message(
                    tool_call, tool_result, is_error
                )
                current_messages.append(tool_message)

            # submit_decision_card 提交成功后终止迭代，避免 LLM 继续空调用
            if card_submitted:
                logger.info(f"卡片已提交，终止工具循环 (迭代 {iteration + 1})")
                return self.protocol.parse_chat_response(result)

        logger.warning(f"达到最大迭代次数 {max_iterations}")
        return self.protocol.parse_chat_response(result)
