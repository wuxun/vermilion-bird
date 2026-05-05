"""
ChatCore - 核心对话引擎

封装完整的 LLM 对话处理管道：
  记忆注入 → 上下文压缩 → LLM 调用 → 工具调用循环 → 响应持久化 → 记忆提取

所有前端（CLI / GUI / 飞书）统一通过此类进行对话处理，
不再各自重复实现 LLM 调用逻辑。
"""

import logging
import threading
from typing import List, Dict, Any, Optional, Callable, Generator

from llm_chat.config import Config
from llm_chat.client import LLMClient
from llm_chat.conversation import ConversationManager
from llm_chat.intent.types import Intent
from llm_chat.utils.token_counter import count_tokens
from llm_chat.utils.observability import observe

logger = logging.getLogger(__name__)

# 流式回调类型
StreamCallback = Callable[[str], None]  # 收到文本 chunk
ToolCallStartCallback = Callable[[str, str], None]  # 工具调用开始 (name, args_json)
ToolCallEndCallback = Callable[[str, str, str], None]  # 工具调用结束 (name, args, result_preview)

# 决策卡片回调: 当 LLM 输出中包含决策卡片时调用
CardCallback = Callable[['DecisionCard'], None]  # noqa: F821

# ── 决策卡片系统提示 ──
_DECISION_CARD_PROMPT = '''
## 决策卡片能力
当你认为用户面临一个需要多选一的场景（选择方案、决定方向、审批请求），
使用 submit_decision_card 工具提交结构化决策卡片，而不是在文本中嵌入 JSON。

### 何时使用
- 用户问该选哪个方案
- 用户让你给几个方案对比一下
- 用户说要不要做 X
- 你发现用户有多个可选路径
- 简单问答无需卡片
- 用户明确要求文字回答
- 闲聊

### 复杂分析任务：并行子Agent + 决策卡片模式

当用户的任务需要对同一对象进行多维度分析时（如代码审查、方案评估、
文档审核、数据分析），使用以下模式：

1. **拆分维度**：根据任务性质，自主决定分析维度。例如：
   - 代码审查 → 安全 + 性能 + 代码质量
   - 方案评估 → 技术可行性 + 成本 + 风险
   - 文档审核 → 准确性 + 完整性 + 可读性
   - 用户也可以指定维度："从安全和性能角度审查这段代码"

2. **并行启动子Agent**：对每个维度调用 spawn_subagent 工具，设置 wait=true。
   在同一轮回复中发出所有 spawn_subagent 调用，系统会并行执行。

3. **汇总为决策卡片**：收到所有子Agent结果后，调用 submit_decision_card 工具
   提交决策卡片。卡片参数包含 title、context、options、recommendation、sources。

### 注意事项
- 选项 id 依次为 A, B, C...
- recommendation 指向 confidence 最高的选项
- 每个选项必须给出 confidence (0.0~1.0)
- sources 列出信息来源（如子 agent 名称）
'''


class ChatCore:
    """核心对话引擎

    职责边界：
    - 管理完整的对话处理管道
    - 协调记忆、上下文、LLM 调用、工具执行
    - 提供统一的同步 & 流式接口

    NOT 负责：
    - 前端渲染（由 GUI/CLI/飞书各自处理）
    - 会话列表管理（由 ConversationManager 处理）
    - MCP 连接管理（由 App 处理，通过 ToolRegistry 注册 MCPToolAdapter）
    """

    def __init__(
        self,
        client: LLMClient,
        conversation_manager: ConversationManager,
        config: Config,
    ):
        self.client = client
        self.conversation_manager = conversation_manager
        self.config = config
        self._cancel_event: Optional[threading.Event] = None
        self._prompt_skills_context: str = ""  # 由 App.set_prompt_skills_context() 注入
        self._current_style: str = "default"  # 当前对话风格预设

        # 意图识别 (减少不必要的 LLM 调用)
        from llm_chat.intent import IntentClassifier

        self.intent_classifier = IntentClassifier(
            enable_layer1=config.tools.enable_intent
            if hasattr(config.tools, 'enable_intent') else True
        )
        logger.info("IntentClassifier 已初始化")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @observe("chat_core.send_message")
    def send_message(
        self,
        conversation_id: str,
        message: str,
        on_card: Optional[CardCallback] = None,
        **model_params,
    ) -> str:
        """同步发送消息，返回完整回复文本。

        适用场景：CLI 非流式模式、飞书消息回复、定时任务等。

        Args:
            conversation_id: 会话 ID
            message: 用户消息
            on_card: 可选回调，当 LLM 输出决策卡片时调用。
            **model_params: 覆盖默认模型参数 (temperature, max_tokens 等)

        Returns:
            AI 回复的完整文本（已移除决策卡片 JSON 块）
        """

        # 延迟导入避免循环
        conv = self.conversation_manager.get_conversation(conversation_id)

        # ── 0. 意图识别 ──
        decision = self.intent_classifier.classify(message)
        logger.debug(
            f"[INTENT] {decision.intent.value} (conf={decision.confidence:.2f}, "
            f"skip_llm={decision.skip_llm}, model={decision.suggested_model})"
        )

        # 0a. 短路：跳过 LLM 直接返回
        if decision.skip_llm:
            conv.add_user_message(message)

            # /style 特殊处理：切换对话风格
            if decision.override_message and decision.override_message.startswith("__style__:"):
                style_name = decision.override_message.split(":", 1)[1]
                response = self._apply_style(style_name)
                conv.add_assistant_message(response)
                logger.info(f"[INTENT] 风格切换: {style_name}")
                return response

            # /remember 特殊处理：直接存储到长期记忆
            if decision.override_message and decision.override_message.startswith("__remember__:"):
                content = decision.override_message.split(":", 1)[1]
                if content:
                    memory_manager = getattr(conv, "_memory_manager", None)
                    if memory_manager:
                        memory_manager.consolidate_to_long_term([content], is_user_told=True)
                        response = f"已记住 ✓: {content}"
                    else:
                        response = f"已记录（无记忆管理器）: {content}"
                    logger.info(f"[INTENT] 记住事实: {content[:80]}...")
                else:
                    response = "请提供要记住的内容，例如：/记住 我最常用的 Python 版本是 3.11"
                conv.add_assistant_message(response)
                return response

            # /new 特殊处理：创建新会话
            if decision.override_message == "__new_conversation__":
                # 从消息中提取标题 (如 /new 项目讨论 → 项目讨论)
                title = message[4:].strip() if len(message) > 4 else None
                new_conv = self.conversation_manager.create_conversation(title=title)
                response = f"已创建新会话: {new_conv.conversation_id}"
                if title:
                    response = f"已创建新会话「{title}」: {new_conv.conversation_id}"
                conv.add_assistant_message(response)
                logger.info(f"[INTENT] 新建会话: {new_conv.conversation_id}")
                return response

            # /clear 特殊处理：清空对话
            elif decision.intent == Intent.SHORTCUT and decision.direct_response:
                conv.clear_history()

            conv.add_assistant_message(decision.direct_response)
            logger.info(f"[INTENT] 快速回复 (跳过 LLM): {decision.intent.value}")
            return decision.direct_response

        # 0b. 覆盖消息内容（如 /search xxx → xxx）
        effective_message = decision.override_message or message

        # 1. 持久化用户消息
        conv.add_user_message(message)

        # 2. 构建系统上下文（记忆注入）
        system_context = self._build_system_context(conv, effective_message)

        # 3. 获取对话历史（不含刚添加的用户消息）
        history = conv.get_history()
        history = history[:-1] if history else []

        # 4. 上下文压缩（如果有 ContextManager）
        processed_history, processed_message = self._compress_context(
            conv, history, effective_message, system_context
        )

        # 5. 合并模型参数（意图推荐的模型优先于会话默认）
        params = conv.get_model_params()
        if decision.suggested_model:
            from llm_chat.intent.classifier import IntentClassifier
            model_hint = IntentClassifier.get_model_hint(decision.intent)
            # 如果配置了 intent_model_map，则映射到具体模型名
            if hasattr(self.config, 'tools') and hasattr(self.config.tools, 'intent_model_map'):
                model_map = getattr(self.config.tools, 'intent_model_map', {})
                suggested = model_map.get(model_hint)
                if suggested:
                    params["model"] = suggested
                    logger.info(
                        f"[INTENT] 模型路由: {decision.intent.value} → {suggested} (hint={model_hint})"
                    )
        params.update(model_params)

        # 6. 调用 LLM（带工具或无工具）
        response = self._call_llm(
            processed_message, processed_history, system_context, params
        )

        # 7. 提取决策卡片（仅 tool-call 路径）
        self._extract_pending_card(conversation_id, on_card)

        # 8. 持久化助手回复

        # 9. 异步记忆提取
        self._extract_memory_async(conv, message, response)

        # 9. 记录 token 消耗
        self._record_tokens(
            message=processed_message,
            history=processed_history,
            system_context=system_context,
            response=response,
        )

        return response

    def cancel_generation(self) -> None:
        """取消当前正在进行的流式生成。"""
        if self._cancel_event:
            self._cancel_event.set()

    @observe("chat_core.send_message_stream")
    def send_message_stream(
        self,
        conversation_id: str,
        message: str,
        on_chunk: Optional[StreamCallback] = None,
        on_tool_start: Optional[ToolCallStartCallback] = None,
        on_tool_end: Optional[ToolCallEndCallback] = None,
        on_context_update: Optional[Callable[[int, int], None]] = None,
        on_card: Optional[CardCallback] = None,
        **model_params,
    ) -> str:
        """流式发送消息，通过回调逐步返回内容。

        适用场景：GUI 实时显示、CLI 流式输出。

        Args:
            conversation_id: 会话 ID
            message: 用户消息
            on_chunk: 收到文本 chunk 时的回调
            on_tool_start: 工具调用开始回调 (tool_name, args_json)
            on_tool_end: 工具调用结束回调 (tool_name, args_json, result_preview)
            on_context_update: 上下文更新回调 (used_tokens, limit)
            **model_params: 覆盖默认模型参数

        Returns:
            AI 回复的完整文本（在所有 chunk 发送完毕后）
        """
        # ── 0. 意图识别 (只在短路时起作用) ──
        decision = self.intent_classifier.classify(message)

        if decision.skip_llm:
            conv = self.conversation_manager.get_conversation(conversation_id)
            conv.add_user_message(message)

            # /style 特殊处理：切换对话风格
            if decision.override_message and decision.override_message.startswith("__style__:"):
                style_name = decision.override_message.split(":", 1)[1]
                response = self._apply_style(style_name)
                conv.add_assistant_message(response)
                if on_chunk:
                    on_chunk(response)
                logger.info(f"[INTENT] 风格切换: {style_name}")
                return response

            # /remember 特殊处理：直接存储到长期记忆
            if decision.override_message and decision.override_message.startswith("__remember__:"):
                content = decision.override_message.split(":", 1)[1]
                if content:
                    memory_manager = getattr(conv, "_memory_manager", None)
                    if memory_manager:
                        memory_manager.consolidate_to_long_term([content], is_user_told=True)
                        response = f"已记住 ✓: {content}"
                    else:
                        response = f"已记录（无记忆管理器）: {content}"
                    logger.info(f"[INTENT] 记住事实: {content[:80]}...")
                else:
                    response = "请提供要记住的内容，例如：/记住 我最常用的 Python 版本是 3.11"
                conv.add_assistant_message(response)
                if on_chunk:
                    on_chunk(response)
                return response

            # /new 特殊处理：新建会话
            if decision.override_message == "__new_conversation__":
                title = message[4:].strip() if len(message) > 4 else None
                new_conv = self.conversation_manager.create_conversation(title=title)
                response = f"已创建新会话: {new_conv.conversation_id}"
                if title:
                    response = f"已创建新会话「{title}」: {new_conv.conversation_id}"
                conv.add_assistant_message(response)
                if on_chunk:
                    on_chunk(response)
                logger.info(f"[INTENT] 新建会话: {new_conv.conversation_id}")
                return response

            # /clear 特殊处理：清空对话
            if decision.intent == Intent.SHORTCUT and decision.direct_response:
                conv.clear_history()

            conv.add_assistant_message(decision.direct_response)
            # 通过回调发送完整文本作为 single chunk
            if on_chunk:
                on_chunk(decision.direct_response)
            logger.info(f"[INTENT] 快速回复 (跳过 LLM): {decision.intent.value}")
            return decision.direct_response

        effective_message = decision.override_message or message

        conv = self.conversation_manager.get_conversation(conversation_id)

        # 1. 持久化用户消息
        conv.add_user_message(message)

        # 2. 构建系统上下文（记忆注入）
        system_context = self._build_system_context(conv, effective_message)

        # 3. 获取对话历史
        history = conv.get_history()
        history = history[:-1] if history else []

        # 4. 上下文压缩
        processed_history, processed_message = self._compress_context(
            conv, history, effective_message, system_context
        )

        # 5. 合并模型参数
        params = {**conv.get_model_params(), **model_params}

        # 6. 检查是否需要工具调用 (模型不支持 tools 则跳过)
        has_tools = self.client.has_builtin_tools()
        model_supports_tools = self._current_model_supports_tools()

        full_text = ""
        self._cancel_event = threading.Event()  # 创建本次生成的取消事件

        if has_tools and self.config.enable_tools and model_supports_tools:
            # 获取可用工具
            tools = self.client.get_builtin_tools()
            if not tools:
                tools = []

            logger.info(f"[ChatCore] 流式工具调用: tools={[t.get('function', {}).get('name', '?') for t in tools]}")

            for chunk in self.client.chat_stream_with_tools(
                processed_message,
                tools,
                history=processed_history,
                system_context=system_context,
                cancel_event=self._cancel_event,
                **params,
            ):
                if self._cancel_event.is_set():
                    logger.info("[ChatCore] Stream cancelled by user")
                    break
                if isinstance(chunk, tuple):
                    kind = chunk[0]
                    if kind == "tool_call_start" and on_tool_start:
                        on_tool_start(chunk[1], chunk[2])
                    elif kind == "tool_call_end" and on_tool_end:
                        on_tool_end(chunk[1], chunk[2], chunk[3])
                    elif kind == "context_update" and on_context_update:
                        on_context_update(chunk[1], chunk[2])
                elif isinstance(chunk, str):
                    full_text += chunk
                    if on_chunk:
                        on_chunk(chunk)
        else:
            # 无工具流式聊天
            logger.info("[ChatCore] 流式聊天 (无工具)")
            for chunk in self.client.chat_stream(
                processed_message,
                history=processed_history,
                system_context=system_context,
                **params,
            ):
                if self._cancel_event.is_set():
                    logger.info("[ChatCore] Stream cancelled by user")
                    break
                full_text += chunk
                if on_chunk:
                    on_chunk(chunk)

        # 7. 持久化助手回复
        conv.add_assistant_message(full_text)

        # 8. 提取 tool call 提交的决策卡片
        self._extract_pending_card(conversation_id, on_card)

        # 9. 异步记忆提取
        self._extract_memory_async(conv, message, full_text)

        # 9. 记录 token 消耗
        self._record_tokens(
            message=processed_message,
            history=processed_history,
            system_context=system_context,
            response=full_text,
        )

        return full_text

    # ------------------------------------------------------------------
    # 上下文 & 工具
    # ------------------------------------------------------------------

    def get_system_context(self, conversation_id: str) -> Optional[str]:
        """获取指定会话的系统上下文（记忆注入），供外部预览使用。"""
        conv = self.conversation_manager.get_conversation(conversation_id)
        return self._build_system_context(conv)

    def get_available_tools(self) -> List[Dict[str, Any]]:
        """获取所有可用工具（内置 + MCP），供 GUI/CLI 展示。"""
        return self.client.get_builtin_tools()

    def has_tools_available(self) -> bool:
        """是否有可用的工具。"""
        return self.client.has_builtin_tools()

    # ------------------------------------------------------------------
    # Tool executor override (由 App 注入 MCP)
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------

    def _build_system_context(self, conv, user_message: str = None) -> Optional[str]:
        """从 Conversation 的记忆管理器构建系统上下文。

        注入顺序：记忆 → 相关对话搜索(FTS5) → prompt skills
        """
        memory_manager = getattr(conv, "_memory_manager", None)
        parts = []

        # 0. 决策卡片能力提示
        parts.append(_DECISION_CARD_PROMPT)

        # 1. 记忆系统
        if memory_manager is not None:
            try:
                mem_prompt = memory_manager.build_system_prompt()
                if mem_prompt:
                    parts.append(mem_prompt)
            except Exception as e:
                logger.warning(f"构建系统上下文失败: {e}")

        # 2. 相关历史对话搜索 (FTS5)
        if user_message and self.conversation_manager:
            try:
                search_results = self.conversation_manager.search_messages(
                    user_message, limit=5
                )
                if search_results:
                    # 过滤掉太短的匹配（通常无关）
                    relevant = [
                        m for m in search_results
                        if len(m.get("content", "")) > 20
                    ]
                    if relevant:
                        ctx = "## 相关历史对话\n以下是与当前问题相关的历史对话片段，可作为回答参考：\n"
                        for i, r in enumerate(relevant[:3], 1):
                            role = r.get("role", "unknown")
                            content = r.get("content", "")[:300]
                            ctx += f"{i}. [{role}]: {content}\n"
                        parts.append(ctx)
            except Exception:
                pass  # FTS 不可用时静默跳过

        # 3. Prompt skills (Agent Skills 标准 — 由 App 注入)
        if self._prompt_skills_context:
            parts.append(self._prompt_skills_context)

        # 4. 当前对话风格 (非 default 时注入)
        style_ctx = self._get_style_context()
        if style_ctx:
            parts.append(style_ctx)

        if not parts:
            return None
        return "\n\n---\n\n".join(parts)

    def set_prompt_skills_context(self, context: str) -> None:
        """由 App 注入 prompt skills 上下文（SkillManager 构建后调用）。"""
        self._prompt_skills_context = context

    def _apply_style(self, style_name: str) -> str:
        """切换对话风格预设。

        Args:
            style_name: 风格名称 (default/academic/casual/concise/coach/architect)

        Returns:
            确认消息
        """
        from llm_chat.memory.templates import SOUL_STYLE_PRESETS

        available = list(SOUL_STYLE_PRESETS.keys())
        if style_name not in available:
            return (
                f"未知风格「{style_name}」。可用风格: {', '.join(available)}\n"
                f"用法: /style <风格名>"
            )

        self._current_style = style_name
        description = SOUL_STYLE_PRESETS[style_name]
        if style_name == "default":
            desc_preview = "直接、有用、不啰嗦"
        else:
            desc_preview = description.split("\n")[1].lstrip("- ") if "\n" in description else description[:60]

        logger.info(f"Style switched to: {style_name}")
        return f"✅ 已切换为 **{style_name}** 风格 ({desc_preview})"

    def _get_style_context(self) -> Optional[str]:
        """获取当前风格的 system prompt 注入片段。"""
        if self._current_style == "default":
            return None

        from llm_chat.memory.templates import SOUL_STYLE_PRESETS

        return SOUL_STYLE_PRESETS.get(self._current_style)

    def _compress_context(
        self,
        conv,
        history: List[Dict[str, Any]],
        message: str,
        system_context: Optional[str],
    ) -> tuple:
        """使用 ContextManager 压缩上下文。

        Returns:
            (processed_history, processed_message) - history 不含当前消息
        """
        context_manager = getattr(conv, "_context_manager", None)
        if context_manager is None:
            return history, message

        try:
            from llm_chat.context import ContextMessage

            context_messages = []
            if system_context:
                context_messages.append(ContextMessage(role="system", content=system_context))

            for msg in history:
                context_messages.append(
                    ContextMessage(
                        role=msg["role"],
                        content=msg["content"],
                        metadata=msg.get("metadata"),
                        timestamp=msg.get("timestamp"),
                    )
                )

            context_messages.append(ContextMessage(role="user", content=message))

            result = context_manager.process_context(
                conversation_id=conv.conversation_id, messages=context_messages
            )

            total_sent_tokens = sum(count_tokens(m.content) for m in result.messages)
            logger.info(
                f"[ChatCore] 上下文压缩完成: token={total_sent_tokens}, "
                f"级别={result.level.name}, 节省={result.saved_tokens}"
            )

            # 分离系统提示和对话历史
            system_prompt = None
            processed_history = []
            for msg in result.messages:
                if msg.role == "system" and system_prompt is None:
                    system_prompt = msg.content
                else:
                    processed_history.append({"role": msg.role, "content": msg.content})

            # 最后一个 user 消息是当前消息
            if processed_history and processed_history[-1]["role"] == "user":
                processed_message = processed_history[-1]["content"]
                processed_history = processed_history[:-1]
            else:
                processed_message = message

            return processed_history, processed_message

        except Exception as e:
            logger.warning(f"上下文压缩失败，使用原始历史: {e}")
            return history, message

    def _call_llm(
        self,
        message: str,
        history: List[Dict[str, Any]],
        system_context: Optional[str],
        params: Dict[str, Any],
    ) -> str:
        """同步调用 LLM，自动选择工具调用或普通聊天路径。"""
        has_tools = self.client.has_builtin_tools()
        model_supports_tools = self._current_model_supports_tools()

        if has_tools and self.config.enable_tools and model_supports_tools:
            tools = self.client.get_builtin_tools()
            if tools:
                logger.info(
                    f"[ChatCore] 同步工具调用: tools={[t.get('function', {}).get('name', '?') for t in tools]}"
                )
                return self.client.chat_with_tools(
                    message, tools, history=history, system_context=system_context, **params
                )

        logger.info("[ChatCore] 同步聊天 (无工具)")
        return self.client.chat(
            message, history=history, system_context=system_context, **params
        )

    def _extract_pending_card(self, conversation_id: str, on_card: Optional[CardCallback] = None):
        """提取 thread-local 中的待推送决策卡片。

        由 send_message 和 send_message_stream 在 LLM 调用完成后调用。
        """
        if on_card is None:
            return
        from llm_chat.decision.submit_tool import get_pending_card
        card = get_pending_card()
        if card:
            card.conversation_id = conversation_id
            on_card(card)
            logger.info(f"决策卡片已提取: {card.id} -> {card.title}")

    def _extract_memory_async(self, conv, user_message: str, assistant_response: str):
        """异步提取记忆到记忆系统。"""
        memory_manager = getattr(conv, "_memory_manager", None)
        if memory_manager is None:
            return
        try:
            messages = [
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": assistant_response},
            ]
            memory_manager.schedule_extraction(messages)
            memory_manager.process_pending_extractions()
        except Exception as e:
            logger.warning(f"记忆提取失败: {e}")

    def _current_model_supports_tools(self) -> bool:
        """检查当前模型是否支持 function calling / tools。

        优先检查 available_models 中该模型的 supports_tools 字段；
        若模型不在列表中则默认返回 True（向后兼容）。
        """
        available = getattr(self.config.llm, "available_models", [])
        current_model = self.config.llm.model
        for mi in available:
            model_id = mi.id if hasattr(mi, "id") else mi.get("id", "")
            if model_id == current_model:
                if hasattr(mi, "supports_tools"):
                    return bool(mi.supports_tools)
                if hasattr(mi, "get"):
                    return bool(mi.get("supports_tools", True))
                break
        return True  # 不在列表中，默认支持（兼容旧配置）

    def _record_tokens(
        self,
        message: str,
        history: List[Dict[str, Any]],
        system_context: Optional[str],
        response: str,
    ):
        """记录本轮对话的 token 消耗 (prompt + completion)，供仪表盘使用。"""
        from llm_chat.utils.observability import get_observability
        from llm_chat.utils.token_counter import count_tokens

        obs = get_observability()

        # 估算 prompt tokens
        prompt_text = ""
        if system_context:
            prompt_text += system_context + "\n"
        for h in history:
            prompt_text += h.get("content", "") + "\n"
        prompt_text += message
        prompt_tokens = count_tokens(prompt_text)

        # 估算 completion tokens
        completion_tokens = count_tokens(response)

        model = self.config.llm.model if hasattr(self.config, 'llm') else "unknown"

        obs.increment("tokens.prompt", prompt_tokens)
        obs.increment("tokens.completion", completion_tokens)
        obs.increment(f"tokens.total", prompt_tokens + completion_tokens)
        obs.increment(f"tokens.{model}", prompt_tokens + completion_tokens)

        logger.debug(
            "Token recorded: prompt=%d, completion=%d, model=%s",
            prompt_tokens, completion_tokens, model,
        )
