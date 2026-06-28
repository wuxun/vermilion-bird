"""PipelineRunner — sequential stage executor.

Executes PipelineStage instances in order, enforcing:
    - setup(ctx) → process(ctx) → teardown(ctx) lifecycle per stage
    - teardown() always runs (try/finally around each stage)
    - Optional short-circuit hook after each stage
    - Snapshot of stage list at run() entry (thread-safe)

Modeled after WorkflowExecutor but for linear pipelines.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, List, Optional

from ember_core.pipeline.stage import PipelineStage

logger = logging.getLogger(__name__)


class PipelineRunner:
    """Sequential pipeline executor.

    Runs a list of PipelineStage instances in order.
    Each stage follows: setup → process → teardown.
    Supports dynamic stage insertion/removal between runs.
    Supports a custom should_short_circuit hook.

    Usage:
        runner = PipelineRunner(stages=[StageA(), StageB()])
        ctx = await runner.run(my_context)

        # With short-circuit
        runner = PipelineRunner(
            stages=[...],
            should_short_circuit=lambda ctx: ctx.done,
        )
    """

    def __init__(
        self,
        stages: Optional[List[PipelineStage]] = None,
        should_short_circuit: Optional[Callable[[Any], bool]] = None,
    ) -> None:
        self._stages: List[PipelineStage] = list(stages) if stages else []
        self._should_short_circuit = should_short_circuit

    # ── Stage management ────────────────────────────────────

    def insert_stage(
        self, index: int, stage: PipelineStage
    ) -> None:
        """Insert a stage at a specific position."""
        self._stages.insert(index, stage)

    def append_stage(self, stage: PipelineStage) -> None:
        """Append a stage to the end."""
        self._stages.append(stage)

    def remove_stage(self, name: str) -> bool:
        """Remove a stage by name. Returns True if found."""
        for i, stage in enumerate(self._stages):
            if stage.name == name:
                self._stages.pop(i)
                return True
        return False

    def get_stage(self, name: str) -> Optional[PipelineStage]:
        """Get a stage by name."""
        for stage in self._stages:
            if stage.name == name:
                return stage
        return None

    @property
    def stages(self) -> List[PipelineStage]:
        return list(self._stages)

    # ── Execution ───────────────────────────────────────────

    async def run(self, ctx: Any) -> Any:
        """Execute all stages sequentially. Returns the final context.

        Args:
            ctx: Context object passed through all stages.

        Returns:
            The context after all stages have run.
        """
        stages_snapshot = list(self._stages)
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
                raise
            finally:
                try:
                    await stage.teardown(ctx)
                except Exception as e:
                    logger.warning(
                        f"Stage[{stage.name}] teardown failed: {e}", exc_info=True
                    )
                logger.debug(f"  Stage[{stage.name}]: done")

            # Short-circuit check after each stage
            if self._should_short_circuit and self._should_short_circuit(ctx):
                logger.info(
                    f"PipelineRunner: short-circuit after stage '{stage.name}'"
                )
                break

        return ctx
