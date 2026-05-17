"""
PipelineStage ABC and PipelineContext dataclass.

PipelineStage follows the project's ABC pattern from BaseTool (tools/base.py:6):
    - @property @abstractmethod for abstract properties
    - @abstractmethod for abstract methods
    - Optional non-abstract methods with sensible defaults

PipelineContext modeled after RoutingDecision (intent/types.py:27):
    - @dataclass with field(default_factory=list/dict) for mutable defaults
    - Optional fields for nullable state
"""

from __future__ import annotations

import logging
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from llm_chat.intent.types import RoutingDecision
    from llm_chat.decision.schema import DecisionCard
    from llm_chat.context.types import CompressionResult

logger = logging.getLogger(__name__)


# ── PipelineStage ABC ──


class PipelineStage(ABC):
    """异步管道阶段的抽象基类。

    每个阶段代表对话处理管道中的一个步骤。
    生命周期: setup(ctx) → process(ctx) → teardown(ctx)

    PipelineRunner 保证 teardown() 始终执行（通过 try/finally），
    即使 process() 抛出异常。
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """阶段名称，用于日志、指标和 insert_stage/remove_stage 定位。"""
        pass

    async def setup(self, ctx: PipelineContext) -> None:
        """阶段前置钩子（可选）。

        在 process() 之前调用。默认 no-op。

        Args:
            ctx: 管道上下文
        """
        pass

    @abstractmethod
    async def process(self, ctx: PipelineContext) -> PipelineContext:
        """执行阶段主逻辑。

        必须实现。PipelineRunner 在每个阶段间检查 ctx.should_short_circuit。

        Args:
            ctx: 管道上下文（可原地修改）

        Returns:
            管道上下文（通常返回同一个 ctx 对象）
        """
        pass

    async def teardown(self, ctx: PipelineContext) -> None:
        """阶段后置钩子（可选）。

        始终被 PipelineRunner 调用（通过 try/finally），即使 process() 抛出异常。
        默认 no-op。

        Args:
            ctx: 管道上下文
        """
        pass

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r}>"


# ── MutableStrHolder ──


class MutableStrHolder:
    """跨请求可变字符串值的薄包装。

    用于 ChatCore 中跨请求可变的实例状态：
    - _prompt_skills_context（App 初始化时设置一次）
    - _current_style（用户 /style 时修改）

    实例由 ChatCore 持有，构造时注入到需要读写的 Stage。
    """

    def __init__(self, value: str = "") -> None:
        self._value = value

    def get(self) -> str:
        """获取当前值。"""
        return self._value

    def set(self, value: str) -> None:
        """设置新值。"""
        self._value = value

    def __repr__(self) -> str:
        preview = self._value[:50] + "..." if len(self._value) > 50 else self._value
        return f"MutableStrHolder({preview!r})"


# ── PipelineContext ──


@dataclass
class PipelineContext:
    """管道全状态 dataclass。

    承载一次对话请求的完整状态，在各阶段间传递。
    阶段通过 ctx 读写共享状态，无需修改 PipelineContext schema。

    Attributes:
        conversation_id: 会话 ID
        user_message: 用户原始输入（永不修改）
        effective_message: 意图覆盖后的消息（由 IntentStage 设置）
        routing_decision: 意图路由决策（由 IntentStage 设置）
        should_short_circuit: 短路标志（ShortcutStage 设置，PipelineRunner 检查）
        system_context: 注入的系统上下文（由 SystemContextStage 构建）
        processed_history: 压缩/处理后的对话历史
        processed_message: 压缩后的当前消息
        params: 模型参数（温度、模型名等）
        response: LLM 生成的响应文本
        cancel_event: 流式取消信号
        status: 管道状态 ("running" | "completed" | "error")
        error: 错误消息（仅在错误状态下）
        pending_card: 待推送的决策卡片
        compression_result: 上下文压缩结果
        metadata: 扩展槽 — 跨阶段通信的键值袋
    """

    # ── 核心标识 ──
    conversation_id: str
    user_message: str
    effective_message: str = ""

    # ── 意图 & 路由 ──
    routing_decision: Optional[RoutingDecision] = None
    should_short_circuit: bool = False

    # ── 系统上下文 ──
    system_context: Optional[str] = None

    # ── 对话历史 (处理后) ──
    processed_history: List[Dict[str, Any]] = field(default_factory=list)
    processed_message: str = ""

    # ── 模型参数 ──
    params: Dict[str, Any] = field(default_factory=dict)

    # ── LLM 响应 ──
    response: str = ""

    # ── 取消信号 ──
    cancel_event: Optional[threading.Event] = None

    # ── 管道状态 ──
    status: str = "running"          # running | completed | error
    error: Optional[str] = None

    # ── 决策卡片 ──
    pending_card: Optional[DecisionCard] = None

    # ── 压缩结果 ──
    compression_result: Optional[CompressionResult] = None

    # ── 流式回调 (仅 LLMCallStage 使用) ──
    on_chunk: Optional[Callable[[str], None]] = None
    on_tool_start: Optional[Callable[[str, str], None]] = None
    on_tool_end: Optional[Callable[[str, str, str], None]] = None
    on_context_update: Optional[Callable[[int, int], None]] = None
    on_card: Optional[Callable[..., None]] = None

    # ── 扩展槽 ──
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """初始化 effective_message 为 user_message（若未覆盖）。"""
        if not self.effective_message:
            self.effective_message = self.user_message

    # ── 便捷方法 ──

    def mark_completed(self) -> None:
        """标记管道成功完成。"""
        self.status = "completed"

    def mark_error(self, error_msg: str) -> None:
        """标记管道错误。"""
        self.status = "error"
        self.error = error_msg
