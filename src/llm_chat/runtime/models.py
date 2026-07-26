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
    PAUSED = "paused"
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


class RecoveryPolicy(str, Enum):
    """进程中断后如何处置尚未结束的 Run。"""

    FAIL = "fail"
    RETRY = "retry"
    RESUME = "resume"
    MANUAL = "manual"


class RunEvent(BaseModel):
    sequence: int
    type: str
    timestamp: datetime = Field(default_factory=utc_now)
    data: Dict[str, Any] = Field(default_factory=dict)


class RunCheckpoint(BaseModel):
    """可恢复执行的最新状态快照。"""

    cursor: str
    state: Dict[str, Any] = Field(default_factory=dict)
    version: int = 1
    created_at: datetime = Field(default_factory=utc_now)


class Run(BaseModel):
    """One execution with explicit lifecycle and parent/child identity."""

    id: str = Field(default_factory=lambda: f"run_{uuid4().hex}")
    parent_run_id: Optional[str] = None
    work_item_id: Optional[str] = None
    type: RunType
    status: RunStatus = RunStatus.PENDING
    conversation_id: Optional[str] = None
    input: Dict[str, Any] = Field(default_factory=dict)
    result: Optional[Any] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    events: List[RunEvent] = Field(default_factory=list)
    attempt: int = 1
    max_attempts: int = 1
    idempotency_key: Optional[str] = None
    recovery_policy: RecoveryPolicy = RecoveryPolicy.FAIL
    checkpoint: Optional[RunCheckpoint] = None
    heartbeat_at: Optional[datetime] = None
    lease_owner: Optional[str] = None
    lease_expires_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utc_now)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    @property
    def can_retry(self) -> bool:
        return self.status == RunStatus.FAILED and self.attempt < self.max_attempts

    @property
    def can_resume(self) -> bool:
        return self.status == RunStatus.PAUSED and self.checkpoint is not None
