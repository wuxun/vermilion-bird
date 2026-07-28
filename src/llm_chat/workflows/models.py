"""可复用工作流定义及不可变版本。"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from llm_chat.work import ArtifactKind


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class WorkflowStatus(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class WorkflowParameter(BaseModel):
    name: str
    description: str = ""
    required: bool = True
    default: Optional[str] = None


class WorkflowDefinition(BaseModel):
    id: str = Field(default_factory=lambda: f"workflow_{uuid4().hex}")
    name: str
    description: str = ""
    status: WorkflowStatus = WorkflowStatus.ACTIVE
    latest_version: int = 1
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class WorkflowVersion(BaseModel):
    id: str = Field(default_factory=lambda: f"workflow_version_{uuid4().hex}")
    workflow_id: str
    version: int
    objective_template: str
    parameters: List[WorkflowParameter] = Field(default_factory=list)
    plan_steps: List[Dict[str, Any]] = Field(default_factory=list)
    expected_artifact_kinds: List[ArtifactKind] = Field(default_factory=list)
    required_resources: List[Dict[str, Any]] = Field(default_factory=list)
    budget: Dict[str, Any] = Field(default_factory=dict)
    approval_policy: Dict[str, Any] = Field(default_factory=dict)
    failure_policy: Dict[str, Any] = Field(default_factory=dict)
    source_work_item_id: Optional[str] = None
    change_summary: str = ""
    created_at: datetime = Field(default_factory=utc_now)
