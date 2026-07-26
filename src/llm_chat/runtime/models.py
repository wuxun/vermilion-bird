"""Domain models for a single auditable execution."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class RunType(str, Enum):
    CHAT = "chat"
    TOOL = "tool"
    WORKFLOW = "workflow"
    SCHEDULED = "scheduled"
    WEBHOOK = "webhook"
    PROACTIVE = "proactive"


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def terminal(self) -> bool:
        return self in {
            RunStatus.COMPLETED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
        }


class RunEvent(BaseModel):
    sequence: int
    type: str
    timestamp: datetime = Field(default_factory=utc_now)
    data: Dict[str, Any] = Field(default_factory=dict)


class Run(BaseModel):
    """One execution with explicit lifecycle and parent/child identity."""

    id: str = Field(default_factory=lambda: f"run_{uuid4().hex}")
    parent_run_id: Optional[str] = None
    type: RunType
    status: RunStatus = RunStatus.PENDING
    conversation_id: Optional[str] = None
    input: Dict[str, Any] = Field(default_factory=dict)
    result: Optional[Any] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    events: List[RunEvent] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
