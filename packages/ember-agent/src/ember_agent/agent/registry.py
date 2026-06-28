"""AgentRegistry — thread-safe agent lifecycle management.

Tracks AgentContext objects, manages a ThreadPoolExecutor for async
execution, and provides status change callbacks for GUI integration.
"""

import logging
import threading
import time as _time
from concurrent.futures import ThreadPoolExecutor, Future
from typing import Any, Dict, List, Optional, Callable

from ember_agent.agent.context import AgentContext

#: Status change callback: (agent_id, status, task, result, extra)
StatusCallback = Callable[[str, str, str, Optional[str], Dict[str, Any]], None]


class AgentRegistry:
    """Thread-safe registry for agent lifecycle management.

    Features:
    - spawn / get / cancel / list agent contexts
    - async execution via ThreadPoolExecutor with Future tracking
    - status change callbacks for GUI push notifications
    - cancel callback cascade for workflow integration
    - dead agent detection (deadline-based)
    """

    def __init__(
        self,
        max_workers: int = 8,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._agents: Dict[str, AgentContext] = {}
        self._futures: Dict[str, Future] = {}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._callbacks: List[StatusCallback] = []
        self._cancel_callbacks: List[Callable[[str], None]] = []
        self.logger = logger or logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def spawn(self, agent_id: str, context: AgentContext) -> None:
        """Register a new agent context."""
        with self._lock:
            self._agents[agent_id] = context
        self.logger.info(
            "Spawned agent '%s' at depth %d with status '%s'",
            agent_id, context.depth, context.status,
        )
        self._notify_status_change(agent_id)

    def get(self, agent_id: str) -> Optional[AgentContext]:
        """Return AgentContext for agent_id, or None."""
        with self._lock:
            return self._agents.get(agent_id)

    def cancel(self, agent_id: str) -> bool:
        """Cancel an agent by setting its cancelled event and status.

        Returns True if agent existed and was cancelled.
        """
        with self._lock:
            ctx = self._agents.get(agent_id)
            if ctx is None:
                return False
            ctx.status = "cancelled"
            ctx._cancelled.set()
            ctx.result = "Cancelled"
        self.logger.info("Cancelled agent '%s'", agent_id)
        self._notify_status_change(agent_id)
        for cb in self._cancel_callbacks:
            try:
                cb(agent_id)
            except Exception:
                self.logger.exception("Cancel callback error for %s", agent_id)
        return True

    def list_active(self) -> List[AgentContext]:
        """List all agents with status 'running'."""
        with self._lock:
            return [
                ctx for ctx in self._agents.values()
                if ctx.status == "running"
            ]

    def clear_completed(self) -> int:
        """Remove agents with terminal status. Returns count removed."""
        to_remove: List[str] = []
        with self._lock:
            for aid, ctx in list(self._agents.items()):
                if ctx.status in ("completed", "failed", "cancelled"):
                    to_remove.append(aid)
            for aid in to_remove:
                del self._agents[aid]
                self._futures.pop(aid, None)
        if to_remove:
            self.logger.info("Cleared %d completed/failed/cancelled agents", len(to_remove))
        return len(to_remove)

    # ------------------------------------------------------------------
    # Async execution
    # ------------------------------------------------------------------

    def submit(
        self, agent_id: str, task_fn, *args, **kwargs
    ) -> Future:
        """Submit a task for async execution.

        Args:
            agent_id: Must already be registered via spawn().
            task_fn: Callable executed in background thread.
            *args, **kwargs: Passed to task_fn.

        Returns:
            Future representing the pending task.
        """
        future = self._executor.submit(task_fn, *args, **kwargs)
        with self._lock:
            self._futures[agent_id] = future
        future.add_done_callback(lambda f: self._on_complete(agent_id, f))
        return future

    def _on_complete(self, agent_id: str, future: Future) -> None:
        """Callback when a Future completes — updates agent status/result."""
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
                try:
                    result = future.result()
                    if ctx._cancelled.is_set():
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

        self.logger.info("Agent '%s' finished: status=%s", agent_id, status_snapshot)
        self._notify_status_change(agent_id)

    def list_all(self) -> List[Dict]:
        """List all agents with status summaries (for LLM consumption)."""
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
        """Number of currently running agents (for concurrency control)."""
        with self._lock:
            return sum(
                1 for ctx in self._agents.values() if ctx.status == "running"
            )

    def cancel_all_running(self) -> int:
        """Cancel all running agents. Returns count cancelled."""
        with self._lock:
            running = [
                aid for aid, ctx in self._agents.items()
                if ctx.status == "running"
            ]
        count = 0
        for agent_id in running:
            if self.cancel(agent_id):
                count += 1
        return count

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def on_agent_status_change(self, cb: StatusCallback) -> None:
        """Register a status change callback.

        Callback signature: (agent_id, status, task, result, extra).
        Called on arbitrary background threads — receivers must handle
        thread safety.
        """
        with self._lock:
            if cb not in self._callbacks:
                self._callbacks.append(cb)

    def remove_callback(self, cb: StatusCallback) -> None:
        """Remove a previously registered callback."""
        with self._lock:
            try:
                self._callbacks.remove(cb)
            except ValueError:
                pass

    def _notify_status_change(self, agent_id: str) -> None:
        """Notify all registered callbacks of an agent status change."""
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

    def wait_for(
        self, agent_id: str, timeout: Optional[float] = None
    ) -> Optional[str]:
        """Block until agent completes. Returns result or None.

        If agent exceeds deadline while waiting, auto-cancels.
        """
        with self._lock:
            future = self._futures.get(agent_id)
        if future is None:
            return None
        try:
            return future.result(timeout=timeout)
        except Exception:
            with self._lock:
                ctx = self._agents.get(agent_id)
                if ctx and ctx.status == "running":
                    if ctx.deadline > 0 and _time.time() > ctx.deadline:
                        ctx._cancelled.set()
                        ctx.status = "timeout"
                        ctx.result = "Agent timed out"
            return None

    # ------------------------------------------------------------------
    # Cancel cascade & cleanup
    # ------------------------------------------------------------------

    def add_cancel_callback(self, callback: Callable[[str], None]) -> None:
        """Register a callback invoked when any agent is cancelled.

        Used by WorkflowExecutor to cascade cancellation to workflows.
        """
        if callback not in self._cancel_callbacks:
            self._cancel_callbacks.append(callback)

    def remove_cancel_callback(self, callback: Callable[[str], None]) -> None:
        """Remove a previously registered cancel callback."""
        try:
            self._cancel_callbacks.remove(callback)
        except ValueError:
            pass

    def shutdown(self, wait: bool = True) -> None:
        """Shut down the thread pool."""
        self._executor.shutdown(wait=wait)

    def cleanup(self) -> int:
        """Remove all non-running agents and reset callbacks."""
        removed = self.clear_completed()
        self._cancel_callbacks.clear()
        return removed

    @property
    def active_count(self) -> int:
        """Number of currently running agents."""
        with self._lock:
            return sum(
                1 for ctx in self._agents.values() if ctx.status == "running"
            )
