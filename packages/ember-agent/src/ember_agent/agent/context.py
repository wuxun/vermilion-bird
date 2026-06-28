"""AgentContext — runtime state for a single agent.

Pure dataclass with cooperative cancellation via threading.Event.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Set


@dataclass
class AgentContext:
    """Runtime context for a single agent instance.

    _cancelled is a threading.Event for cooperative cancellation:
    call cancel() to set it; the executing thread checks it at key
    points and aborts if set.
    """

    agent_id: str
    parent_id: Optional[str]
    depth: int
    allowed_tools: Set[str]
    conversation_id: str
    created_at: datetime
    status: str
    task: str = ""                        # Task description for GUI display
    result: Optional[str] = None
    result_var: str = ""                   # Alias for downstream agents to reference
    work_dir: Optional[str] = None
    # Execution metadata — for GUI display
    model: str = ""
    protocol: str = ""
    tool_calls_log: list = field(default_factory=list)
    _cancelled: threading.Event = field(
        default_factory=threading.Event, init=False, repr=False
    )
    # Dead agent detection
    started_at: float = 0.0   # time.time() when execution began
    deadline: float = 0.0     # time.time() after which agent is considered dead


def make_agent_context(
    agent_id: str,
    parent_id: Optional[str],
    depth: int,
    allowed_tools: Set[str],
    conversation_id: str,
    task: str = "",
    work_dir: str = os.path.expanduser("~/.ember-agent/work"),
    timeout: int = 300,
) -> AgentContext:
    """Create an AgentContext with sensible defaults.

    Shared factory used by both SpawnSubagentTool and WorkflowExecutor
    to avoid context creation duplication.
    """
    now = time.time()
    return AgentContext(
        agent_id=agent_id,
        parent_id=parent_id,
        depth=depth,
        allowed_tools=allowed_tools,
        conversation_id=conversation_id,
        created_at=datetime.now(timezone.utc),
        status="running",
        task=task,
        work_dir=work_dir,
        started_at=now,
        deadline=now + max(timeout, 60) + 120,
    )
