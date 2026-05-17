"""
Pipeline stage implementations — 10 stages extracted from ChatCore methods.

Imports are grouped by stage to minimize cross-stage import issues.
All stages in one file per research recommendation (import hygiene).
"""

from __future__ import annotations

import logging
from typing import Optional, TYPE_CHECKING

from llm_chat.pipeline.stage import PipelineStage, PipelineContext, MutableStrHolder
from llm_chat.intent.types import Intent

if TYPE_CHECKING:
    from llm_chat.intent import IntentClassifier

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# Stage 0: IntentStage — 意图分类
# ═══════════════════════════════════════════════════════════════════


class IntentStage(PipelineStage):
    """意图分类阶段。

    调用 IntentClassifier.classify() 分类用户消息，
    设置 ctx.routing_decision 和 ctx.effective_message。
    """

    name = "Intent"

    def __init__(self, classifier: IntentClassifier) -> None:
        """初始化 IntentStage。

        Args:
            classifier: IntentClassifier 实例（由 ChatCore 注入）
        """
        self._classifier = classifier

    async def process(self, ctx: PipelineContext) -> PipelineContext:
        """分类用户消息，设置路由决策和有效消息。

        Args:
            ctx: 管道上下文（含 user_message）

        Returns:
            更新后的 ctx（含 routing_decision + effective_message）
        """
        decision = self._classifier.classify(ctx.user_message)
        ctx.routing_decision = decision

        # 设置 effective_message：覆盖消息优先，否则保持 user_message（__post_init__ 已设置）
        if decision.override_message:
            ctx.effective_message = decision.override_message

        logger.debug(
            f"[IntentStage] intent={decision.intent.value}, "
            f"conf={decision.confidence:.2f}, skip_llm={decision.skip_llm}, "
            f"model={decision.suggested_model}"
        )
        return ctx


# ═══════════════════════════════════════════════════════════════════
# Stage 0a: ShortcutStage — 短路处理（统一入口）
# ═══════════════════════════════════════════════════════════════════


class ShortcutStage(PipelineStage):
    """短路处理阶段。

    处理 5 种 LLM 短路指令：
    1. /style — 切换对话风格
    2. /remember /记住 — 存储到长期记忆
    3. /new — 创建新会话
    4. /clear /reset /清空/重置 — 清空对话历史
    5. /help /帮助 — 显示帮助

    仅在 routing_decision.skip_llm == True 时执行。
    处理成功后设置 ctx.should_short_circuit = True 和 ctx.response。
    """

    name = "Shortcut"

    def __init__(
        self,
        conversation_manager,
        style_holder: MutableStrHolder,
    ) -> None:
        """初始化 ShortcutStage。

        Args:
            conversation_manager: ConversationManager 实例（由 ChatCore 注入）
            style_holder: 跨请求风格可变状态（由 ChatCore 注入）
        """
        # Import here to avoid circular dependency at module level
        from llm_chat.conversation import ConversationManager as CM

        self._conversation_manager: CM = conversation_manager
        self._style_holder = style_holder

    async def process(self, ctx: PipelineContext) -> PipelineContext:
        """处理短路指令。

        仅在 ctx.routing_decision.skip_llm == True 时执行。

        Args:
            ctx: 管道上下文

        Returns:
            更新后的 ctx（可能设置了 should_short_circuit 和 response）
        """
        decision = ctx.routing_decision
        if decision is None or not decision.skip_llm:
            return ctx  # 非短路，透传

        conv = self._conversation_manager.get_conversation(ctx.conversation_id)

        # 持久化用户消息（使用原始输入）
        conv.add_user_message(ctx.user_message)

        override = decision.override_message

        # 1. /style — 切换对话风格
        if override and override.startswith("__style__:"):
            style_name = override.split(":", 1)[1]
            response = self._apply_style(style_name)
            conv.add_assistant_message(response)
            if ctx.on_chunk:
                ctx.on_chunk(response)
            logger.info(f"[ShortcutStage] 风格切换: {style_name}")
            ctx.response = response
            ctx.should_short_circuit = True
            return ctx

        # 2. /remember /记住 — 存储到长期记忆
        if override and override.startswith("__remember__:"):
            content = override.split(":", 1)[1]
            if content:
                memory_manager = getattr(conv, "_memory_manager", None)
                if memory_manager:
                    memory_manager.consolidate_to_long_term(
                        [content], is_user_told=True
                    )
                    response = f"已记住 ✓: {content}"
                else:
                    response = f"已记录（无记忆管理器）: {content}"
                logger.info(f"[ShortcutStage] 记住事实: {content[:80]}...")
            else:
                response = "请提供要记住的内容，例如：/记住 我最常用的 Python 版本是 3.11"
            conv.add_assistant_message(response)
            if ctx.on_chunk:
                ctx.on_chunk(response)
            ctx.response = response
            ctx.should_short_circuit = True
            return ctx

        # 3. /new — 创建新会话
        if override == "__new_conversation__":
            if conv.conversation_id.startswith("feishu_"):
                response = "已开始新会话 ✓"
                conv.add_assistant_message(response)
                if ctx.on_chunk:
                    ctx.on_chunk(response)
                logger.info(
                    f"[ShortcutStage] 飞书新建会话: {conv.conversation_id}"
                )
                ctx.response = response
                ctx.should_short_circuit = True
                return ctx

            title = (
                ctx.user_message[4:].strip()
                if len(ctx.user_message) > 4
                else None
            )
            new_conv = self._conversation_manager.create_conversation(title=title)
            response = f"已创建新会话: {new_conv.conversation_id}"
            if title:
                response = (
                    f"已创建新会话「{title}」: {new_conv.conversation_id}"
                )
            conv.add_assistant_message(response)
            if ctx.on_chunk:
                ctx.on_chunk(response)
            logger.info(
                f"[ShortcutStage] 新建会话: {new_conv.conversation_id}"
            )
            ctx.response = response
            ctx.should_short_circuit = True
            return ctx

        # 4. /clear /reset /help 等 — 直接回复
        # 注意：严格匹配 Intent.SHORTCUT，保持与原始 _handle_shortcut (chat_core.py:379) 一致
        if decision.intent == Intent.SHORTCUT and decision.direct_response:
            if (
                decision.direct_response == "对话已清空。开始新的对话吧！"
            ):
                conv.clear_history()

            conv.add_assistant_message(decision.direct_response)
            if ctx.on_chunk:
                ctx.on_chunk(decision.direct_response)
            logger.info(
                f"[ShortcutStage] 快速回复 (跳过 LLM): {decision.intent.value}"
            )
            ctx.response = decision.direct_response
            ctx.should_short_circuit = True
            return ctx

        # 不是任何已知的短路类型 — 透传给 LLM 管道
        return ctx

    # ── 私有辅助 ──

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

        self._style_holder.set(style_name)
        description = SOUL_STYLE_PRESETS[style_name]
        if style_name == "default":
            desc_preview = "直接、有用、不啰嗦"
        else:
            desc_preview = (
                description.split("\n")[1].lstrip("- ")
                if "\n" in description
                else description[:60]
            )

        logger.info(f"Style switched to: {style_name}")
        return f"✅ 已切换为 **{style_name}** 风格 ({desc_preview})"


# ── 系统提示常量（从 chat_core.py 迁移）──

_DECISION_CARD_PROMPT = '''
## 决策卡片能力

决策卡片是帮助用户在多个方案中做选择的工具。成本高（占用UI、打断阅读），只在真正需要时使用。

### 默认不用卡片
- 回答可以用一段话讲清楚 → 直接文本回复
- 用户在问事实/知识/解释 → 直接文本回复
- 用户让你做一件事 → 直接做，做完文字反馈
- 只有一个显然正确的方向 → 直接说明
- 闲聊、问候 → 直接文本回复

### 使用条件（全部满足才用）
1. 存在 2-3 个实质不同的路径，各有优劣
2. 需要用户做出判断（不是信息告知）
3. 用户没有明确说"直接给我答案"
4. 结构化卡片确实比一段 Markdown 列表好

### 何时使用
- 用户明确要求对比多个方案
- 多维度分析后不同维度结论冲突
- 利弊不显然需要展示正反两面

### 注意事项
- 选项 id: A, B, C...每个选项必须给 confidence (0.0~1.0)
- 只有 1 个实质选项 → 不要硬凑，用文字回复
- recommendation 指向 confidence 最高的选项
'''

_SOCRATIC_PROMPT = '''
## 苏格拉底式对话 — 先理解再行动

当面对可执行的请求（写代码、操作文件、搜索、定时任务）时，遵循：

### 判断是否需要澄清
- **请求足够具体**（含语言/平台/约束/输入输出格式）→ 直接执行，不弹卡
- **请求模糊**（如"帮我写个脚本"、"处理数据"、"优化一下"、"查一下"）
  → 不要急于动手！先调用 submit_decision_card 提交澄清卡片
- **执行结果只有一种合理方式** → 直接做，文字告知结果，不弹卡

### 澄清卡片要求
- **引导需求层次**（快速原型 vs 生产级 vs 探索性），不是问技术参数（"你要 Python 还是 Rust？"）
- 选项间有区分度，不要同质化
- 最后一个选项 id 固定为"让我说更多"的逃生选项（用户可能想说明更多背景）
- **弹卡时文本回复严格保持 1 句话**：只说明为什么需要确认，不要同时输出大段分析或预测。
  文字回复和卡片内容不应重复

### 示例
用户："帮我写个爬虫"
→ 卡：A.快速原型(一次性, requests+bs4) / B.生产级(代理轮换+重试+持久化) / C.让我说更多
→ 文本回复："爬虫的实现方式取决于你的目标，我列了几个方向："

用户："用 Python 3.11 和 aiohttp 写一个抓取 Hacker News 首页标题的脚本"
→ 足够具体，直接写代码，不要弹卡

用户："帮我写个 hello world"
→ 足够简单明确，直接写代码，不要弹卡

用户："优化这段代码"
→ 卡：A.可读性优化 / B.性能优化 / C.全面优化 / D.让我说更多

用户："帮我查一下"
→ 卡：A.技术最新动态 / B.社区生态 / C.生产实践经验 / D.让我说更多

用户："帮我查一下 Rust 最新版本"
→ 足够具体，直接搜索后文字回复，不要弹卡

用户："Python 和 Rust 哪个更适合写 CLI 工具"
→ 这是明确要求对比，可以用卡片展示各方优劣
'''

# 需要注入苏格拉底提示的意图类型
_SOCRATIC_INTENTS = {Intent.CODE, Intent.FILE_OP, Intent.SEARCH, Intent.SCHEDULE}


# ═══════════════════════════════════════════════════════════════════
# Stage 1: PersistUserStage — 持久化用户消息
# ═══════════════════════════════════════════════════════════════════


class PersistUserStage(PipelineStage):
    """持久化用户消息到 SQLite。

    必须在 HistoryStage 之前执行（HistoryStage 读取历史并剥离刚写入的消息）。
    """

    name = "PersistUser"

    def __init__(self, conversation_manager) -> None:
        from llm_chat.conversation import ConversationManager as CM
        self._conversation_manager: CM = conversation_manager

    async def process(self, ctx: PipelineContext) -> PipelineContext:
        conv = self._conversation_manager.get_conversation(ctx.conversation_id)
        # 使用 user_message（原始输入），非 effective_message
        conv.add_user_message(ctx.user_message)
        logger.debug(f"[PersistUserStage] persisted user message for {ctx.conversation_id}")
        return ctx


# ═══════════════════════════════════════════════════════════════════
# Stage 2: SystemContextStage — 构建系统上下文
# ═══════════════════════════════════════════════════════════════════


class SystemContextStage(PipelineStage):
    """构建系统上下文（记忆 + FTS5 搜索 + prompt skills + 风格）。

    注入顺序：决策卡片提示 → 苏格拉底提示(条件) → 记忆 → FTS5 搜索 → prompt skills → 风格
    """

    name = "SystemContext"

    def __init__(
        self,
        conversation_manager,
        prompt_skills_holder: MutableStrHolder,
        style_holder: MutableStrHolder,
    ) -> None:
        from llm_chat.conversation import ConversationManager as CM
        self._conversation_manager: CM = conversation_manager
        self._prompt_skills_holder = prompt_skills_holder
        self._style_holder = style_holder

    async def process(self, ctx: PipelineContext) -> PipelineContext:
        conv = self._conversation_manager.get_conversation(ctx.conversation_id)
        memory_manager = getattr(conv, "_memory_manager", None)
        parts = []

        # 0. 决策卡片能力提示
        parts.append(_DECISION_CARD_PROMPT)

        # 0a. 苏格拉底式对话 (仅对可执行意图注入)
        intent = ctx.routing_decision.intent if ctx.routing_decision else None
        if intent in _SOCRATIC_INTENTS:
            parts.append(_SOCRATIC_PROMPT)
            logger.debug(f"[SystemContextStage] 注入苏格拉底提示 (intent={intent.value})")

        # 1. 记忆系统
        if memory_manager is not None:
            try:
                mem_prompt = memory_manager.build_system_prompt()
                if mem_prompt:
                    parts.append(mem_prompt)
            except Exception as e:
                logger.warning(f"构建系统上下文失败: {e}")

        # 2. 相关历史对话搜索 (FTS5)
        if ctx.effective_message and self._conversation_manager:
            try:
                search_results = self._conversation_manager.search_messages(
                    ctx.effective_message, limit=5
                )
                if search_results:
                    relevant = [
                        m for m in search_results
                        if len(m.get("content", "")) > 20
                    ]
                    if relevant:
                        fts5_ctx = "## 相关历史对话\n以下是与当前问题相关的历史对话片段，可作为回答参考：\n"
                        for i, r in enumerate(relevant[:3], 1):
                            role = r.get("role", "unknown")
                            content = r.get("content", "")[:300]
                            fts5_ctx += f"{i}. [{role}]: {content}\n"
                        parts.append(fts5_ctx)
            except Exception:
                pass  # FTS 不可用时静默跳过

        # 3. Prompt skills (Agent Skills 标准 — 由 App 注入)
        prompt_skills = self._prompt_skills_holder.get()
        if prompt_skills:
            parts.append(prompt_skills)

        # 4. 当前对话风格 (非 default 时注入)
        style_context = self._get_style_context()
        if style_context:
            parts.append(style_context)

        if not parts:
            ctx.system_context = None
        else:
            ctx.system_context = "\n\n---\n\n".join(parts)

        logger.debug(
            f"[SystemContextStage] system_context built: "
            f"{len(ctx.system_context) if ctx.system_context else 0} chars"
        )
        return ctx

    # ── 私有辅助 ──

    def _get_style_context(self) -> Optional[str]:
        """获取当前风格的 system prompt 注入片段。"""
        current_style = self._style_holder.get()
        if current_style == "default":
            return None

        from llm_chat.memory.templates import SOUL_STYLE_PRESETS
        return SOUL_STYLE_PRESETS.get(current_style)


# ═══════════════════════════════════════════════════════════════════
# Stage 3: HistoryStage — 获取对话历史
# ═══════════════════════════════════════════════════════════════════


class HistoryStage(PipelineStage):
    """获取对话历史并剥离当前消息。

    必须在 PersistUserStage 之后执行（新增的消息已写入 SQLite）。
    剥离 history[:-1] 以排除刚持久化的当前消息。
    """

    name = "History"

    def __init__(self, conversation_manager) -> None:
        from llm_chat.conversation import ConversationManager as CM
        self._conversation_manager: CM = conversation_manager

    async def process(self, ctx: PipelineContext) -> PipelineContext:
        conv = self._conversation_manager.get_conversation(ctx.conversation_id)
        history = conv.get_history()

        # 剥离刚写入的用户消息（PersistUserStage 写入）
        # 保留 history[:-1] — 当前消息在 CompressStage 单独加入
        ctx.processed_history = history[:-1] if history else []

        logger.debug(
            f"[HistoryStage] loaded {len(history)} messages, "
            f"stripped to {len(ctx.processed_history)}"
        )
        return ctx


# ═══════════════════════════════════════════════════════════════════
# Stage 4: ModelRouteStage — 模型路由
# ═══════════════════════════════════════════════════════════════════


class ModelRouteStage(PipelineStage):
    """模型路由阶段。根据意图分类结果确定最终使用的模型名称。
    必须在 CompressStage 之前执行（压缩需要最终模型名做 token 上限校验）。"""

    name = "ModelRoute"

    def __init__(self, config) -> None:
        self._config = config

    async def process(self, ctx: PipelineContext) -> PipelineContext:
        decision = ctx.routing_decision
        if decision is None:
            return ctx
        if decision.suggested_model:
            from llm_chat.intent.classifier import IntentClassifier
            model_hint = IntentClassifier.get_model_hint(decision.intent)
            if hasattr(self._config, 'tools') and hasattr(self._config.tools, 'intent_model_map'):
                model_map = getattr(self._config.tools, 'intent_model_map', {})
                suggested = model_map.get(model_hint)
                if suggested:
                    ctx.params["model"] = suggested
                    logger.info(
                        f"[ModelRoute] {decision.intent.value} → {suggested} (hint={model_hint})"
                    )
                    return ctx
        if "model" not in ctx.params:
            ctx.params["model"] = self._config.llm.model
        return ctx


# ═══════════════════════════════════════════════════════════════════
# Stage 5: CompressStage — 上下文压缩
# ═══════════════════════════════════════════════════════════════════


class CompressStage(PipelineStage):
    """上下文压缩阶段。必须在 ModelRouteStage 之后执行。
    重压缩回退：>90% model_limit → MANUAL 级别重压缩。"""

    name = "Compress"

    def __init__(self, conversation_manager) -> None:
        from llm_chat.conversation import ConversationManager as CM
        self._conversation_manager: CM = conversation_manager

    async def process(self, ctx: PipelineContext) -> PipelineContext:
        conv = self._conversation_manager.get_conversation(ctx.conversation_id)
        context_manager = getattr(conv, "_context_manager", None)
        if context_manager is None:
            ctx.processed_message = ctx.effective_message
            return ctx
        try:
            from llm_chat.context import ContextMessage, CompressionLevel
            from llm_chat.utils.token_counter import count_tokens, get_context_limit

            context_messages = []
            if ctx.system_context:
                context_messages.append(ContextMessage(role="system", content=ctx.system_context))
            for msg in ctx.processed_history:
                context_messages.append(ContextMessage(
                    role=msg["role"], content=msg["content"],
                    metadata=msg.get("metadata"), timestamp=msg.get("timestamp"),
                ))
            context_messages.append(ContextMessage(role="user", content=ctx.effective_message))

            result = context_manager.process_context(
                conversation_id=conv.conversation_id, messages=context_messages,
            )

            total_sent_tokens = sum(count_tokens(m.content) for m in result.messages)
            final_model = ctx.params.get("model", "")
            actual_limit = get_context_limit(final_model) if final_model else context_manager.max_model_tokens

            if total_sent_tokens > actual_limit * 0.9:
                logger.warning(
                    f"[CompressStage] 压缩后仍超限 ({total_sent_tokens}/{actual_limit}), "
                    f"强制 MANUAL 重压缩"
                )
                result = context_manager.process_context(
                    conversation_id=conv.conversation_id, messages=context_messages,
                    target_level=CompressionLevel.MANUAL, force_recompress=True,
                )
                ctx.metadata["was_recompressed"] = True

            ctx.compression_result = result

            processed_history, processed_message = [], ctx.effective_message
            for msg in result.messages:
                if msg.role != "system":
                    processed_history.append({"role": msg.role, "content": msg.content})
            if processed_history and processed_history[-1]["role"] == "user":
                processed_message = processed_history[-1]["content"]
                processed_history = processed_history[:-1]
            ctx.processed_history = processed_history
            ctx.processed_message = processed_message

        except Exception as e:
            logger.warning(f"[CompressStage] failed: {e}")
            ctx.processed_message = ctx.effective_message

        return ctx


# ═══════════════════════════════════════════════════════════════════
# Stage 6: LLMCallStage — LLM 调用
# ═══════════════════════════════════════════════════════════════════


class LLMCallStage(PipelineStage):
    """LLM 调用阶段。setup: init_card_context, process: LLM call (sync/stream), teardown: extract card + clear."""

    name = "LLMCall"

    def __init__(self, client, config) -> None:
        self._client = client
        self._config = config

    async def setup(self, ctx: PipelineContext) -> None:
        from llm_chat.decision.submit_tool import init_card_context
        init_card_context()

    async def process(self, ctx: PipelineContext) -> PipelineContext:
        if ctx.on_chunk is not None:
            ctx.response = await self._call_llm_stream(ctx)
        else:
            ctx.response = await self._call_llm_sync(ctx)
        return ctx

    async def teardown(self, ctx: PipelineContext) -> None:
        from llm_chat.decision.submit_tool import get_pending_card, clear_card_context
        try:
            card = get_pending_card()
            if card and ctx.on_card:
                card.conversation_id = ctx.conversation_id
                ctx.on_card(card)
        except Exception as e:
            logger.warning(f"[LLMCallStage] card extraction failed: {e}")
        finally:
            clear_card_context()

    def _should_use_tools(self) -> bool:
        if not self._client.has_builtin_tools():
            return False
        if not self._config.enable_tools:
            return False
        return self._model_supports_tools()

    def _model_supports_tools(self) -> bool:
        available = getattr(self._config.llm, "available_models", [])
        current_model = self._config.llm.model
        for mi in available:
            model_id = mi.id if hasattr(mi, "id") else mi.get("id", "")
            if model_id == current_model:
                if hasattr(mi, "supports_tools"):
                    return bool(mi.supports_tools)
                if hasattr(mi, "get"):
                    return bool(mi.get("supports_tools", True))
                break
        return True

    async def _call_llm_sync(self, ctx: PipelineContext) -> str:
        history = ctx.processed_history
        message = ctx.processed_message
        system_context = ctx.system_context
        params = {**ctx.params}

        if self._should_use_tools():
            tools = self._client.get_builtin_tools()
            if tools:
                return self._client.chat_with_tools(
                    message, tools, history=history,
                    system_context=system_context, **params
                )
        return self._client.chat(
            message, history=history,
            system_context=system_context, **params
        )

    async def _call_llm_stream(self, ctx: PipelineContext) -> str:
        history = ctx.processed_history
        message = ctx.processed_message
        system_context = ctx.system_context
        params = {**ctx.params}
        full_text = ""

        if self._should_use_tools():
            tools = self._client.get_builtin_tools() or []
            for chunk in self._client.chat_stream_with_tools(
                message, tools, history=history,
                system_context=system_context,
                cancel_event=ctx.cancel_event, **params,
            ):
                if ctx.cancel_event and ctx.cancel_event.is_set():
                    break
                if isinstance(chunk, tuple):
                    kind = chunk[0]
                    if kind == "tool_call_start" and ctx.on_tool_start:
                        ctx.on_tool_start(chunk[1], chunk[2])
                    elif kind == "tool_call_end" and ctx.on_tool_end:
                        ctx.on_tool_end(chunk[1], chunk[2], chunk[3])
                    elif kind == "context_update" and ctx.on_context_update:
                        ctx.on_context_update(chunk[1], chunk[2])
                elif isinstance(chunk, str):
                    full_text += chunk
                    if ctx.on_chunk:
                        ctx.on_chunk(chunk)
        else:
            for chunk in self._client.chat_stream(
                message, history=history,
                system_context=system_context, **params,
            ):
                if ctx.cancel_event and ctx.cancel_event.is_set():
                    break
                full_text += chunk
                if ctx.on_chunk:
                    ctx.on_chunk(chunk)
        return full_text


# ═══════════════════════════════════════════════════════════════════
# Stage 7: PersistAssistantStage — 持久化助手回复
# ═══════════════════════════════════════════════════════════════════


class PersistAssistantStage(PipelineStage):
    """持久化助手回复到 SQLite。"""
    name = "PersistAssistant"

    def __init__(self, conversation_manager) -> None:
        from llm_chat.conversation import ConversationManager as CM
        self._conversation_manager: CM = conversation_manager

    async def process(self, ctx: PipelineContext) -> PipelineContext:
        conv = self._conversation_manager.get_conversation(ctx.conversation_id)
        conv.add_assistant_message(ctx.response)
        return ctx


# ═══════════════════════════════════════════════════════════════════
# Stage 8: MemoryExtractStage — 记忆提取
# ═══════════════════════════════════════════════════════════════════


class MemoryExtractStage(PipelineStage):
    """异步提取记忆到记忆系统。"""
    name = "MemoryExtract"

    def __init__(self, conversation_manager) -> None:
        from llm_chat.conversation import ConversationManager as CM
        self._conversation_manager: CM = conversation_manager

    async def process(self, ctx: PipelineContext) -> PipelineContext:
        conv = self._conversation_manager.get_conversation(ctx.conversation_id)
        memory_manager = getattr(conv, "_memory_manager", None)
        if memory_manager is None:
            return ctx
        try:
            messages = [
                {"role": "user", "content": ctx.user_message},
                {"role": "assistant", "content": ctx.response},
            ]
            memory_manager.schedule_extraction(messages)
            memory_manager.process_pending_extractions()
        except Exception as e:
            logger.warning(f"[MemoryExtractStage] failed: {e}")
        return ctx


# ═══════════════════════════════════════════════════════════════════
# Stage 9: TokenRecordStage — Token 记录
# ═══════════════════════════════════════════════════════════════════


class TokenRecordStage(PipelineStage):
    """记录本轮对话的 token 消耗。"""
    name = "TokenRecord"

    def __init__(self, config) -> None:
        self._config = config

    async def process(self, ctx: PipelineContext) -> PipelineContext:
        from llm_chat.utils.observability import get_observability
        from llm_chat.utils.token_counter import count_tokens

        obs = get_observability()

        prompt_text = ""
        if ctx.system_context:
            prompt_text += ctx.system_context + "\n"
        for h in ctx.processed_history:
            prompt_text += h.get("content", "") + "\n"
        prompt_text += ctx.processed_message
        prompt_tokens = count_tokens(prompt_text)
        completion_tokens = count_tokens(ctx.response)

        model = self._config.llm.model if hasattr(self._config, 'llm') else "unknown"

        obs.increment("tokens.prompt", prompt_tokens)
        obs.increment("tokens.completion", completion_tokens)
        obs.increment("tokens.total", prompt_tokens + completion_tokens)
        obs.increment(f"tokens.{model}", prompt_tokens + completion_tokens)

        logger.debug(
            "Token recorded: prompt=%d, completion=%d, model=%s",
            prompt_tokens, completion_tokens, model,
        )
        return ctx
