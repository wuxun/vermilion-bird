"""
PipelineRunner — async sequential stage executor.

Executes PipelineStage instances in order, enforcing:
    - setup(ctx) → process(ctx) → teardown(ctx) lifecycle
    - teardown() always runs (try/finally around each stage)
    - should_short_circuit check after each stage
    - Shallow copy of stage list at run() entry (thread-safe against concurrent insert/remove)

Modeled after WorkflowExecutor (skills/task_delegator/workflow.py:230-460):
    - Sequential execution with per-node dispatch
    - State tracking (status, error)
"""

from __future__ import annotations

import logging
from typing import List, Optional, TYPE_CHECKING

from llm_chat.pipeline.stage import PipelineStage, PipelineContext

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class PipelineRunner:
    """异步管道运行器 — 按顺序执行 PipelineStage 列表。

    职责：
    - 维护阶段列表（支持 insert_stage / remove_stage）
    - 在 run() 入口浅拷贝阶段列表（避免执行中被外部修改）
    - 对每个阶段执行 setup → process → teardown 生命周期
    - 阶段间检查 ctx.should_short_circuit 标志
    - teardown() 始终通过 try/finally 执行

    使用方式：
        runner = PipelineRunner(stages=[IntentStage(), ...])
        ctx = PipelineContext(conversation_id="x", user_message="hi")
        ctx = await runner.run(ctx)
        print(ctx.response)
    """

    def __init__(self, stages: Optional[List[PipelineStage]] = None) -> None:
        """初始化 PipelineRunner。

        Args:
            stages: 初始阶段列表。若为 None 则为空列表。
        """
        self._stages: List[PipelineStage] = list(stages) if stages else []

    # ── Public API ──

    async def run(self, ctx: PipelineContext) -> PipelineContext:
        """按顺序执行所有阶段，返回最终上下文。

        生命周期保证：
        - 每个阶段的 teardown() 始终执行（即使在 process() 中抛出异常）
        - 异常会传播到调用方（ChatCore 捕获并处理）
        - should_short_circuit 标志在阶段间检查，设置后立即停止

        Args:
            ctx: 管道上下文（含 conversation_id, user_message 等）

        Returns:
            更新后的管道上下文（含 response, status 等）
        """
        stages_snapshot = list(self._stages)  # 浅拷贝，避免并发修改
        logger.debug(f"PipelineRunner.run: {len(stages_snapshot)} stages")

        for stage in stages_snapshot:
            logger.debug(f"  Stage[{stage.name}]: setup...")
            try:
                await stage.setup(ctx)
                await stage.process(ctx)
            except Exception as e:
                logger.warning(
                    f"Stage[{stage.name}] process failed: {e}", exc_info=True
                )
                ctx.mark_error(str(e))
                raise
            finally:
                try:
                    await stage.teardown(ctx)
                except Exception as te:
                    logger.warning(
                        f"Stage[{stage.name}] teardown failed: {te}", exc_info=True
                    )
                    # teardown 错误不覆盖 process 错误
                    if ctx.error is None:
                        ctx.mark_error(f"teardown[{stage.name}]: {te}")

            # 短路检查
            if ctx.should_short_circuit:
                logger.info(f"PipelineRunner: short-circuit at stage [{stage.name}]")
                break

        if ctx.status == "running":
            ctx.mark_completed()

        logger.debug(
            f"PipelineRunner.run done: status={ctx.status}, "
            f"response_len={len(ctx.response)}"
        )
        return ctx

    # ── Stage list management ──

    def insert_stage(self, after_name: str, stage: PipelineStage) -> None:
        """在指定名称的阶段之后插入新阶段。

        Args:
            after_name: 目标阶段名称（新阶段插入其后）
            stage: 要插入的阶段实例

        Raises:
            ValueError: 若 after_name 不在阶段列表中
        """
        for i, s in enumerate(self._stages):
            if s.name == after_name:
                self._stages.insert(i + 1, stage)
                logger.info(
                    f"Stage [{stage.name}] inserted after [{after_name}] "
                    f"(now {len(self._stages)} stages)"
                )
                return
        raise ValueError(
            f"Stage not found: {after_name!r}. "
            f"Available: {[s.name for s in self._stages]}"
        )

    def remove_stage(self, name: str) -> bool:
        """移除指定名称的阶段。

        Args:
            name: 要移除的阶段名称

        Returns:
            True 若找到并移除，False 若未找到
        """
        for i, s in enumerate(self._stages):
            if s.name == name:
                removed = self._stages.pop(i)
                logger.info(
                    f"Stage [{removed.name}] removed (now {len(self._stages)} stages)"
                )
                return True
        logger.warning(f"remove_stage: stage [{name}] not found")
        return False

    def get_stage(self, name: str) -> Optional[PipelineStage]:
        """按名称查找阶段。

        Args:
            name: 阶段名称

        Returns:
            PipelineStage 实例，若未找到返回 None
        """
        for s in self._stages:
            if s.name == name:
                return s
        return None

    def list_stages(self) -> List[str]:
        """返回当前阶段名称列表（按执行顺序）。

        Returns:
            阶段名称列表
        """
        return [s.name for s in self._stages]

    def __len__(self) -> int:
        return len(self._stages)

    def __repr__(self) -> str:
        names = self.list_stages()
        return f"<PipelineRunner stages={names}>"
