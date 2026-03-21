from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Set


@dataclass
class AgentContext:
    agent_id: str
    parent_id: Optional[str]
    depth: int
    allowed_tools: Set[str]
    conversation_id: str
    created_at: datetime
    status: str
    result: Optional[str] = None
