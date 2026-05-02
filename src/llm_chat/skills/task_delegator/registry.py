import logging
import threading
from concurrent.futures import ThreadPoolExecutor, Future
from typing import Dict, List, Optional

from llm_chat.skills.task_delegator.context import AgentContext


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

    def get(self, agent_id: str) -> Optional[AgentContext]:
        """Return the AgentContext for the given agent_id, or None if missing."""
        with self._lock:
            return self._agents.get(agent_id)

    def cancel(self, agent_id: str) -> bool:
        """Cancel a sub-agent by setting its status to 'cancelled'.

        Returns True if the agent existed and was cancelled, False otherwise.
        """
        with self._lock:
            ctx = self._agents.get(agent_id)
            if ctx is None:
                return False
            # Mark as cancelled; keep existing object reference
            ctx.status = "cancelled"
            ctx.result = None
        self.logger.info("Cancelled sub-agent '%s'", agent_id)
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
                # Already set by _execute_task, but ensure consistency
                try:
                    result = future.result()
                    if ctx.status == "running":
                        ctx.status = "completed"
                        ctx.result = result
                except Exception as e:
                    ctx.status = "failed"
                    ctx.result = str(e)

            self.logger.info(
                "Sub-agent '%s' finished: status=%s", agent_id, ctx.status
            )

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

    def shutdown(self, wait: bool = True):
        """Shut down the thread pool, optionally waiting for running tasks."""
        self._executor.shutdown(wait=wait)

    @property
    def active_count(self) -> int:
        """Number of currently running sub-agents."""
        with self._lock:
            return sum(1 for ctx in self._agents.values() if ctx.status == "running")
