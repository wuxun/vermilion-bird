import logging
import threading
from concurrent.futures import ThreadPoolExecutor, Future
from typing import Any, Dict, List, Optional, Callable

from llm_chat.skills.task_delegator.context import AgentContext

#: 状态变更回调: (agent_id, status, task, result, extra)
StatusCallback = Callable[[str, str, str, Optional[str], Dict[str, Any]], None]


class SubAgentRegistry:
    """Thread-safe registry for tracking sub-agents (Task Delegator).

    Stores AgentContext objects keyed by their agent_id and provides
    helper methods to spawn, get, cancel and list active sub-agents, as well
    as cleanup of completed/failed/cancelled agents.

    Supports asynchronous execution via ThreadPoolExecutor — spawn() returns
    immediately and _execute_task() runs in a background thread.
    """

    def __init__(
        self,
        max_workers: int = 8,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        # Internal storage for sub-agents
        self._agents: Dict[str, AgentContext] = {}
        # Future tracking for async sub-agent tasks
        self._futures: Dict[str, Future] = {}
        # Lock to ensure thread-safety for registry mutations
        self._lock = threading.Lock()
        # Thread pool for running sub-agent tasks asynchronously
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        # Status change callbacks (e.g. GUI panels). Thread-safe append/iterate.
        self._callbacks: List[StatusCallback] = []
        # Cancel callbacks: called when any agent is cancelled (e.g. WorkflowExecutor).
        self._cancel_callbacks: List[Callable[[str], None]] = []
        # Logger for observability
        self.logger = logger or logging.getLogger(__name__)

    def spawn(self, agent_id: str, context: AgentContext) -> None:
        """Register a new sub-agent context under the given agent_id."""
        with self._lock:
            self._agents[agent_id] = context
        self.logger.info(
            "Spawned sub-agent '%s' at depth %d with status '%s'",
            agent_id,
            context.depth,
            context.status,
        )
        self._notify_status_change(agent_id)

    def get(self, agent_id: str) -> Optional[AgentContext]:
        """Return the AgentContext for the given agent_id, or None if missing."""
        with self._lock:
            return self._agents.get(agent_id)

    def cancel(self, agent_id: str) -> bool:
        """Cancel a sub-agent by setting its status to 'cancelled'.

        Signals the agent's cancellation event, which the background executor
        checks at key points.  Also marks status so immediate status queries
        reflect the cancellation.

        Returns True if the agent existed and was cancelled, False otherwise.
        """
        with self._lock:
            ctx = self._agents.get(agent_id)
            if ctx is None:
                return False
            ctx.status = "cancelled"
            ctx._cancelled.set()
            ctx.result = "Cancelled"
        self.logger.info("Cancelled sub-agent '%s'", agent_id)
        self._notify_status_change(agent_id)
        # Fire cancel callbacks (e.g. WorkflowExecutor)
        for cb in self._cancel_callbacks:
            try:
                cb(agent_id)
            except Exception:
                self.logger.exception("Cancel callback error for %s", agent_id)
        return True

    def list_active(self) -> List[AgentContext]:
        """List all sub-agents currently in status 'running'."""
        with self._lock:
            return [ctx for ctx in self._agents.values() if ctx.status == "running"]

    def clear_completed(self) -> int:
        """Remove all sub-agents whose status is in [completed, failed, cancelled].

        Also removes associated futures. Returns the number of removed agents.
        """
        to_remove: List[str] = []
        with self._lock:
            for aid, ctx in list(self._agents.items()):
                if ctx.status in ("completed", "failed", "cancelled"):
                    to_remove.append(aid)
            for aid in to_remove:
                del self._agents[aid]
                self._futures.pop(aid, None)
        if to_remove:
            self.logger.info(
                "Cleared %d completed/failed/cancelled sub-agents", len(to_remove)
            )
        return len(to_remove)

    # ------------------------------------------------------------------
    # Async execution (Future tracking)
    # ------------------------------------------------------------------

    def submit(
        self,
        agent_id: str,
        task_fn,
        *args,
        **kwargs,
    ) -> Future:
        """Submit a sub-agent task for asynchronous execution.

        The task_fn(*args, **kwargs) will run in the thread pool.
        On completion, the agent's status and result are updated automatically.

        Args:
            agent_id: The sub-agent ID (must already be registered via spawn).
            task_fn: Callable to execute in background.
            *args, **kwargs: Arguments passed to task_fn.

        Returns:
            The Future representing the pending task.
        """
        future = self._executor.submit(task_fn, *args, **kwargs)
        with self._lock:
            self._futures[agent_id] = future
        future.add_done_callback(
            lambda f: self._on_complete(agent_id, f)
        )
        return future

    def _on_complete(self, agent_id: str, future: Future):
        """Callback invoked when a sub-agent Future completes.

        Updates the AgentContext with completion status and result,
        or marks it as failed if an exception occurred.
        """
        with self._lock:
            ctx = self._agents.get(agent_id)
            if ctx is None:
                return

            if future.cancelled():
                ctx.status = "cancelled"
                ctx.result = "Cancelled"
            elif future.exception():
                ctx.status = "failed"
                ctx.result = str(future.exception())
            else:
                # _execute_async already set status; respect cancellation signal
                try:
                    result = future.result()
                    if ctx._cancelled.is_set():
                        # cancelled during execution — keep cancelled status
                        if ctx.status == "running":
                            ctx.status = "cancelled"
                        ctx.result = ctx.result or "Cancelled"
                    elif ctx.status == "running":
                        ctx.status = "completed"
                        ctx.result = result
                except Exception as e:
                    ctx.status = "failed"
                    ctx.result = str(e)

            status_snapshot = ctx.status

        self.logger.info(
            "Sub-agent '%s' finished: status=%s", agent_id, status_snapshot
        )
        # Notify outside lock to avoid deadlock with callback → registry calls
        self._notify_status_change(agent_id)

    def list_all(self) -> List[Dict]:
        """List all sub-agents with their status, suitable for LLM consumption."""
        with self._lock:
            return [
                {
                    "agent_id": ctx.agent_id,
                    "parent_id": ctx.parent_id,
                    "depth": ctx.depth,
                    "status": ctx.status,
                    "created_at": ctx.created_at.isoformat(),
                    "result": (
                        ctx.result[:200] + "..."
                        if ctx.result and len(ctx.result) > 200
                        else ctx.result
                    ),
                }
                for ctx in self._agents.values()
            ]

    def count_running(self) -> int:
        """返回正在运行的子 agent 数量（并发控制用）。"""
        with self._lock:
            return sum(1 for ctx in self._agents.values() if ctx.status == "running")

    def cancel_all_running(self) -> int:
        """Cancel all running sub-agents. Returns count of cancelled."""
        with self._lock:
            running = [
                agent_id for agent_id, ctx in self._agents.items()
                if ctx.status == "running"
            ]
        count = 0
        for agent_id in running:
            if self.cancel(agent_id):
                count += 1
        return count

    # ------------------------------------------------------------------
    # Status change callbacks (push notifications to GUI / logs / metrics)
    # ------------------------------------------------------------------

    def on_agent_status_change(self, cb: StatusCallback) -> None:
        """注册子 agent 状态变更回调。

        回调签名: (agent_id, status, task, result).
        回调在任意后台线程触发，接收者需自行处理线程安全。
        """
        with self._lock:
            if cb not in self._callbacks:
                self._callbacks.append(cb)

    def remove_callback(self, cb: StatusCallback) -> None:
        """移除已注册的回调（Widget 销毁时调用，防止悬垂引用）。"""
        with self._lock:
            try:
                self._callbacks.remove(cb)
            except ValueError:
                pass

    def _notify_status_change(self, agent_id: str) -> None:
        """通知所有已注册的回调：指定 agent 的状态已变更。

        在 spawn / cancel / _on_complete 后调用。
        提取 agent 的快照数据，逐个调用回调（回调在调用线程执行）。
        """
        # 快照：在锁内提取数据，锁外调用回调
        with self._lock:
            ctx = self._agents.get(agent_id)
            if ctx is None:
                return
            extra = {
                "model": ctx.model,
                "protocol": ctx.protocol,
                "allowed_tools": list(ctx.allowed_tools),
                "tool_calls_log": list(ctx.tool_calls_log),
                "depth": ctx.depth,
                "parent_id": ctx.parent_id,
            }
            snapshot = (ctx.agent_id, ctx.status, ctx.task, ctx.result, extra)
            cbs = list(self._callbacks)

        for cb in cbs:
            try:
                cb(*snapshot)
            except Exception:
                self.logger.debug(
                    "Status callback error for agent '%s'", agent_id, exc_info=True
                )

    def wait_for(self, agent_id: str, timeout: Optional[float] = None) -> Optional[str]:
        """Block until a sub-agent completes, return its result or None on timeout/error."""
        with self._lock:
            future = self._futures.get(agent_id)
        if future is None:
            return None
        try:
            return future.result(timeout=timeout)
        except Exception:
            return None

    def shutdown(self, wait: bool = True):
        """Shut down the thread pool, optionally waiting for running tasks."""
        self._executor.shutdown(wait=wait)

    def add_cancel_callback(self, callback: Callable[[str], None]) -> None:
        """Register a callback invoked whenever any agent is cancelled."""
        if callback not in self._cancel_callbacks:
            self._cancel_callbacks.append(callback)

    def remove_cancel_callback(self, callback: Callable[[str], None]) -> None:
        """Unregister a previously-added cancel callback."""
        try:
            self._cancel_callbacks.remove(callback)
        except ValueError:
            pass

    def cleanup(self) -> int:
        """Remove all non-running sub-agents and reset state.

        Returns the number of removed agents."""
        removed = self.clear_completed()
        self._cancel_callbacks.clear()
        return removed

    @property
    def active_count(self) -> int:
        """Number of currently running sub-agents."""
        with self._lock:
            return sum(1 for ctx in self._agents.values() if ctx.status == "running")
