import logging
import threading
from typing import Dict, List, Optional

from llm_chat.skills.task_delegator.context import AgentContext


class SubAgentRegistry:
    """Thread-safe registry for tracking sub-agents (Task Delegator).

    Stores AgentContext objects keyed by their agent_id and provides
    helper methods to spawn, get, cancel and list active sub-agents, as well
    as cleanup of completed/failed/cancelled agents.
    """

    def __init__(self, logger: Optional[logging.Logger] = None) -> None:
        # Internal storage for sub-agents
        self._agents: Dict[str, AgentContext] = {}
        # Lock to ensure thread-safety for registry mutations
        self._lock = threading.Lock()
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

        Returns the number of removed agents.
        """
        to_remove: List[str] = []
        with self._lock:
            for aid, ctx in list(self._agents.items()):
                if ctx.status in ("completed", "failed", "cancelled"):
                    to_remove.append(aid)
            for aid in to_remove:
                del self._agents[aid]
        if to_remove:
            self.logger.info(
                "Cleared %d completed/failed/cancelled sub-agents", len(to_remove)
            )
        return len(to_remove)
