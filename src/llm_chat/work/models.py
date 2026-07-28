"""用户任务与交付物的产品领域模型。"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from llm_chat.runtime.models import Run


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class WorkItemKind(str, Enum):
    """用户看到的工作类型；与底层 RunType 解耦。"""

    CHAT = "chat"
    TASK = "task"
    AUTOMATION = "automation"


class WorkItemStatus(str, Enum):
    DRAFT = "draft"
    READY = "ready"
    RUNNING = "running"
    CANCELLING = "cancelling"
    PAUSING = "pausing"
    WAITING_APPROVAL = "waiting_approval"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def terminal(self) -> bool:
        return self in {
            WorkItemStatus.COMPLETED,
            WorkItemStatus.FAILED,
            WorkItemStatus.CANCELLED,
        }


class ArtifactKind(str, Enum):
    TEXT = "text"
    FILE = "file"
    REPORT = "report"
    CODE = "code"
    LINK = "link"
    MESSAGE = "message"
    OTHER = "other"


class PlanStatus(str, Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    SUPERSEDED = "superseded"


class PlanStepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ResourceType(str, Enum):
    DIRECTORY = "directory"
    DOMAIN = "domain"
    MESSAGE_TARGET = "message_target"


class GrantScope(str, Enum):
    ONCE = "once"
    WORK_ITEM = "work_item"
    WORKFLOW = "workflow"


class GrantStatus(str, Enum):
    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"


class WorkItem(BaseModel):
    """一件用户希望完成的工作，可包含多次执行尝试。"""

    id: str = Field(default_factory=lambda: f"work_{uuid4().hex}")
    title: str
    objective: str
    kind: WorkItemKind = WorkItemKind.TASK
    status: WorkItemStatus = WorkItemStatus.READY
    conversation_id: Optional[str] = None
    workflow_id: Optional[str] = None
    workspace: Optional[str] = None
    root_run_id: Optional[str] = None
    latest_run_id: Optional[str] = None
    idempotency_key: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    completed_at: Optional[datetime] = None


class Artifact(BaseModel):
    """任务执行产生的可独立查询与交付的结果。"""

    id: str = Field(default_factory=lambda: f"artifact_{uuid4().hex}")
    work_item_id: str
    run_id: Optional[str] = None
    kind: ArtifactKind = ArtifactKind.OTHER
    name: str
    uri: Optional[str] = None
    content: Optional[str] = None
    content_preview: Optional[str] = None
    checksum: Optional[str] = None
    idempotency_key: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class PlanStep(BaseModel):
    """计划定义中的一个稳定步骤。"""

    id: str = Field(default_factory=lambda: f"step_{uuid4().hex}")
    plan_revision_id: str = ""
    position: int
    title: str
    description: str = ""
    status: PlanStepStatus = PlanStepStatus.PENDING
    depends_on: List[str] = Field(default_factory=list)
    expected_artifact_kind: Optional[ArtifactKind] = None
    required_capabilities: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class PlanRevision(BaseModel):
    """任务计划的版本化快照；批准新版本时旧版本被保留并标记取代。"""

    id: str = Field(default_factory=lambda: f"plan_{uuid4().hex}")
    work_item_id: str
    version: int
    summary: str
    status: PlanStatus = PlanStatus.DRAFT
    change_summary: str = ""
    created_by: str = "local-user"
    steps: List[PlanStep] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    approved_at: Optional[datetime] = None


class ResourceGrant(BaseModel):
    """对一个具体资源边界的可撤销授权。"""

    id: str = Field(default_factory=lambda: f"grant_{uuid4().hex}")
    work_item_id: Optional[str] = None
    workflow_id: Optional[str] = None
    capability: str
    resource_type: ResourceType
    resource: str
    scope: GrantScope = GrantScope.WORK_ITEM
    status: GrantStatus = GrantStatus.ACTIVE
    created_by: str = "local-user"
    reason: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    expires_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None


class WorkItemDetail(BaseModel):
    """任务中心所需的聚合只读视图。"""

    work_item: WorkItem
    runs: List[Run] = Field(default_factory=list)
    artifacts: List[Artifact] = Field(default_factory=list)
    plan: Optional[PlanRevision] = None
    grants: List[ResourceGrant] = Field(default_factory=list)
