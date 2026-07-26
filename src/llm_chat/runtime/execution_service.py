"""将产品级 Run 生命周期与框架级 Graph checkpoint 对齐。"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from .graph_runtime import GraphExecutionResult, GraphRuntime
from .manager import RunManager
from .models import RecoveryPolicy, Run, RunStatus, RunType

logger = logging.getLogger(__name__)


class GraphExecutionService:
    """GraphRuntime 的应用服务。

    外层 Run 保存身份、审计、租约和恢复策略；图的完整状态只保存在
    GraphRuntime checkpointer 中，Run checkpoint 仅保存稳定指针。
    """

    RUNTIME_NAME = "langgraph"

    def __init__(
        self,
        *,
        run_manager: RunManager,
        graph_runtime: GraphRuntime,
        lease_seconds: int = 120,
    ):
        self.run_manager = run_manager
        self.graph_runtime = graph_runtime
        self.lease_seconds = lease_seconds

    def start(
        self,
        graph_name: str,
        *,
        run_type: RunType,
        inputs: Dict[str, Any],
        conversation_id: Optional[str] = None,
        parent_run_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        max_attempts: int = 2,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Run:
        run_metadata = dict(metadata or {})
        run_metadata.update(
            {
                "graph_runtime": self.RUNTIME_NAME,
                "graph_name": graph_name,
            }
        )
        run_metadata.setdefault("run_handler", "graph")
        run = self.run_manager.start(
            run_type,
            conversation_id=conversation_id,
            parent_run_id=parent_run_id,
            input=inputs,
            metadata=run_metadata,
            idempotency_key=idempotency_key,
            recovery_policy=RecoveryPolicy.RESUME,
            max_attempts=max_attempts,
        )

        # 相同 idempotency key 再次进入时，已有 checkpoint 就是事实来源，
        # 不能把初始输入重新提交给已执行过的 thread。
        existing_state = self.graph_runtime.get_state(
            graph_name,
            thread_id=run.id,
        )
        if existing_state is not None:
            return self._sync_existing(run, existing_state)

        self._claim_or_raise(run.id)
        self.run_manager.emit(
            run.id,
            "graph.started",
            {"graph_name": graph_name},
        )
        return self._execute(
            run.id,
            lambda: self.graph_runtime.invoke(
                graph_name,
                thread_id=run.id,
                inputs=inputs,
            ),
        )

    def resume(self, run_id: str, value: Any) -> Run:
        run = self._require_graph_run(run_id)
        if run.status != RunStatus.PAUSED:
            raise ValueError(f"Run {run_id} is not paused")
        self.run_manager.resume(run_id)
        self._claim_or_raise(run_id)
        self.run_manager.emit(run_id, "graph.resume_requested")
        graph_name = str(run.metadata["graph_name"])
        return self._execute(
            run_id,
            lambda: self.graph_runtime.resume(
                graph_name,
                thread_id=run_id,
                value=value,
            ),
        )

    def retry(self, run_id: str) -> Run:
        run = self._require_graph_run(run_id)
        if not run.can_retry:
            raise ValueError(f"Run {run_id} cannot be retried")
        self.run_manager.retry(run_id)
        self._claim_or_raise(run_id)
        graph_name = str(run.metadata["graph_name"])
        snapshot = self.graph_runtime.get_state(graph_name, thread_id=run_id)
        self.run_manager.emit(
            run_id,
            "graph.retry_requested",
            {"attempt": run.attempt + 1},
        )
        if snapshot is not None and snapshot.next_nodes:

            def execute():
                return self.graph_runtime.continue_run(
                    graph_name,
                    thread_id=run_id,
                )

        else:

            def execute():
                return self.graph_runtime.invoke(
                    graph_name,
                    thread_id=run_id,
                    inputs=run.input,
                )

        return self._execute(run_id, execute)

    def replay(self, run_id: str) -> Run:
        source = self._require_graph_run(run_id)
        replay = self.run_manager.replay(run_id)
        self._claim_or_raise(replay.id)
        graph_name = str(source.metadata["graph_name"])
        self.run_manager.emit(
            replay.id,
            "graph.replay_started",
            {"source_run_id": source.id},
        )
        return self._execute(
            replay.id,
            lambda: self.graph_runtime.invoke(
                graph_name,
                thread_id=replay.id,
                inputs=replay.input,
            ),
        )

    def _execute(self, run_id: str, operation) -> Run:
        try:
            result = operation()
            return self._reconcile(run_id, result)
        except Exception as exc:
            logger.exception("Graph execution failed for run %s", run_id)
            self.run_manager.emit(
                run_id,
                "graph.failed",
                {"error": str(exc)},
            )
            return self.run_manager.fail(run_id, str(exc))

    def _reconcile(
        self,
        run_id: str,
        result: GraphExecutionResult,
    ) -> Run:
        run = self._require_graph_run(run_id)
        graph_name = str(run.metadata["graph_name"])
        snapshot = result.snapshot
        next_nodes = tuple(snapshot.next_nodes) if snapshot else ()
        cursor = ",".join(next_nodes) if next_nodes else "__end__"
        checkpoint_state = {
            "graph_runtime": self.RUNTIME_NAME,
            "graph_name": graph_name,
            "thread_id": run_id,
            "checkpoint_id": snapshot.checkpoint_id if snapshot else None,
        }
        self.run_manager.checkpoint(
            run_id,
            cursor=cursor,
            state=checkpoint_state,
        )

        if result.interrupted:
            interrupts = [{"id": item.id, "value": item.value} for item in result.interrupts]
            self.run_manager.emit(
                run_id,
                "graph.interrupted",
                {"interrupts": interrupts, "next_nodes": list(next_nodes)},
            )
            return self.run_manager.pause(run_id, reason="graph_interrupt")

        self.run_manager.emit(
            run_id,
            "graph.completed",
            {"checkpoint_id": checkpoint_state["checkpoint_id"]},
        )
        return self.run_manager.complete(run_id, result.values)

    def _sync_existing(self, run: Run, snapshot) -> Run:
        if run.status.terminal or run.status == RunStatus.PAUSED:
            return run
        # 进程可能在 LangGraph 写完 checkpoint、外层 Run 落盘前退出。
        synthetic = GraphExecutionResult(
            values=dict(snapshot.values),
            interrupts=tuple(snapshot.interrupts),
            snapshot=snapshot,
        )
        return self._reconcile(run.id, synthetic)

    def _claim_or_raise(self, run_id: str) -> None:
        if not self.run_manager.claim(
            run_id,
            lease_seconds=self.lease_seconds,
        ):
            raise RuntimeError(f"Run {run_id} is already executing in another worker")

    def _require_graph_run(self, run_id: str) -> Run:
        run = self.run_manager.get(run_id)
        if run is None:
            raise KeyError(f"Unknown run: {run_id}")
        if run.metadata.get("graph_runtime") != self.RUNTIME_NAME:
            raise ValueError(f"Run {run_id} is not managed by {self.RUNTIME_NAME}")
        if not run.metadata.get("graph_name"):
            raise ValueError(f"Run {run_id} has no graph name")
        return run
