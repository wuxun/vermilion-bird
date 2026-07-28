"""任务级评测模型。"""

from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from llm_chat.work import ArtifactKind, WorkItemStatus


class EvalScenario(BaseModel):
    id: str
    name: str
    category: str
    objective: str
    expected_status: WorkItemStatus = WorkItemStatus.COMPLETED
    accepted_artifact_kinds: List[ArtifactKind] = Field(default_factory=list)
    minimum_artifacts: int = 1
    requires_approval: bool = False
    maximum_duration_seconds: Optional[float] = None
    tags: List[str] = Field(default_factory=list)


class EvalResult(BaseModel):
    scenario_id: str
    work_item_id: str
    passed: bool
    checks: Dict[str, bool] = Field(default_factory=dict)
    failures: List[str] = Field(default_factory=list)
    duration_seconds: Optional[float] = None
    artifact_count: int = 0
    approval_count: int = 0
    uncertain_effect_count: int = 0


class EvalReport(BaseModel):
    results: List[EvalResult] = Field(default_factory=list)
    scenario_count: int = 0
    passed_count: int = 0
    completion_rate: float = 0.0
    artifact_rate: float = 0.0
    approval_compliance_rate: float = 0.0
    uncertain_effect_count: int = 0
    average_duration_seconds: Optional[float] = None
