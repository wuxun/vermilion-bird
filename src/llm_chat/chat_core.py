"""
ChatCore - 核心对话引擎

封装完整的 LLM 对话处理管道：
  意图识别 → 短路处理 → 记忆注入 → 上下文压缩 → LLM 调用 → 工具调用循环 → 响应持久化 → 记忆提取

所有前端（CLI / GUI / 飞书）统一通过此类进行对话处理，
不再各自重复实现 LLM 调用逻辑。

Phase 7: PipelineStage abstraction — 委托给 PipelineRunner 执行 10 阶段异步管道。
"""

import asyncio
import logging
import threading
from typing import List, Dict, Any, Optional, Callable

from llm_chat.config import Config
from llm_chat.client import LLMClient
from llm_chat.conversation import ConversationManager
from llm_chat.utils.observability import observe
from llm_chat.pipeline import PipelineRunner, PipelineContext, MutableStrHolder
from llm_chat.pipeline.stages import (
    IntentStage, ShortcutStage,
    PersistUserStage, SystemContextStage, HistoryStage,
    ModelRouteStage, CompressStage,
    LLMCallStage,
    PersistAssistantStage, MemoryExtractStage, KnowledgeExtractStage,
    TokenRecordStage,
)

logger = logging.getLogger(__name__)

# 流式回调类型
StreamCallback = Callable[[str], None]  # 收到文本 chunk
ToolCallStartCallback = Callable[[str, str], None]  # 工具调用开始 (name, args_json)
ToolCallEndCallback = Callable[[str, str, str], None]  # 工具调用结束 (name, args, result_preview)

# 决策卡片回调: 当 LLM 输出中包含决策卡片时调用
CardCallback = Callable[['DecisionCard'], None]  # noqa: F821


class ChatCore:
    """核心对话引擎 — Phase 7: PipelineStage abstraction.

    委托给 PipelineRunner 执行 10 阶段异步管道。
    ChatCore 退化为薄包装层，负责：
    - 组装阶段列表 + 创建 PipelineContext + asyncio.run(runner.run(ctx))
    - 暴露 insert_stage/remove_stage API
    - 暴露 get_system_context/cancel_generation 等便捷方法
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
        self._prompt_skills_holder = MutableStrHolder("")
        self._style_holder = MutableStrHolder("default")

        # 意图识别
        from llm_chat.intent import IntentClassifier
        self.intent_classifier = IntentClassifier(
            enable_layer1=config.tools.enable_intent
            if hasattr(config.tools, 'enable_intent') else True
        )

        # 组装 11 阶段管道
        stages = [
            IntentStage(self.intent_classifier),
            ShortcutStage(self.conversation_manager, self._style_holder),
            PersistUserStage(self.conversation_manager),
            SystemContextStage(self.conversation_manager, self._prompt_skills_holder, self._style_holder),
            HistoryStage(self.conversation_manager),
            ModelRouteStage(self.config),
            CompressStage(self.conversation_manager),
            LLMCallStage(self.client, self.config),
            PersistAssistantStage(self.conversation_manager),
            MemoryExtractStage(self.conversation_manager),
            KnowledgeExtractStage(self.conversation_manager),
            TokenRecordStage(self.config),
        ]
        self._runner = PipelineRunner(stages)
        logger.info(f"ChatCore initialized (PipelineStage abstraction, {len(stages)} stages)")

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
        """同步发送消息，返回完整回复文本。"""
        ctx = PipelineContext(
            conversation_id=conversation_id,
            user_message=message,
            on_card=on_card,
            params=model_params,
        )
        try:
            ctx = asyncio.run(self._runner.run(ctx))
        except Exception as e:
            logger.error(f"send_message pipeline failed: {e}", exc_info=True)
            return f"处理消息时发生错误: {str(e)}"
        return ctx.response

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
        """流式发送消息，通过回调逐步返回内容。"""
        self._cancel_event = threading.Event()
        ctx = PipelineContext(
            conversation_id=conversation_id,
            user_message=message,
            on_chunk=on_chunk,
            on_tool_start=on_tool_start,
            on_tool_end=on_tool_end,
            on_context_update=on_context_update,
            on_card=on_card,
            cancel_event=self._cancel_event,
            params=model_params,
        )
        try:
            ctx = asyncio.run(self._runner.run(ctx))
        except Exception as e:
            logger.error(f"send_message_stream pipeline failed: {e}", exc_info=True)
            return f"处理消息时发生错误: {str(e)}"
        return ctx.response

    # ------------------------------------------------------------------
    # 上下文 & 工具
    # ------------------------------------------------------------------

    def get_system_context(self, conversation_id: str) -> Optional[str]:
        """获取指定会话的系统上下文（记忆注入），供外部预览使用。"""
        stage = SystemContextStage(
            self.conversation_manager,
            self._prompt_skills_holder,
            self._style_holder,
        )
        ctx = PipelineContext(conversation_id=conversation_id, user_message="", effective_message="")
        asyncio.run(stage.process(ctx))
        return ctx.system_context

    def get_available_tools(self) -> List[Dict[str, Any]]:
        """获取所有可用工具（内置 + MCP），供 GUI/CLI 展示。"""
        return self.client.get_builtin_tools()

    def has_tools_available(self) -> bool:
        """是否有可用的工具。"""
        return self.client.has_builtin_tools()

    # ------------------------------------------------------------------
    # Stage management API
    # ------------------------------------------------------------------

    def insert_stage(self, after_name: str, stage) -> None:
        """在指定名称的阶段之后插入新阶段。"""
        self._runner.insert_stage(after_name, stage)

    def remove_stage(self, name: str) -> bool:
        """移除指定名称的阶段。"""
        return self._runner.remove_stage(name)

    def list_stages(self) -> List[str]:
        """返回当前阶段名称列表。"""
        return self._runner.list_stages()

    # ------------------------------------------------------------------
    # Prompt skills context injection (by App)
    # ------------------------------------------------------------------

    def set_prompt_skills_context(self, context: str) -> None:
        """由 App 注入 prompt skills 上下文（SkillManager 构建后调用）。"""
        self._prompt_skills_holder.set(context)
