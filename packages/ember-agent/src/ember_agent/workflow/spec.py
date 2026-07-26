"""Canonical declarative workflow specification."""

from __future__ import annotations

from typing import List, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class WorkflowNodeSpec(BaseModel):
    id: str
    profile: str = Field(validation_alias=AliasChoices("profile", "role"))
    task: str = "{user_task}"
    parallel: int = Field(default=1, ge=1)
    depends_on: List[str] = Field(default_factory=list)
    collect: str = ""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @property
    def role(self) -> str:
        """Legacy PatternStage name."""
        return self.profile


class WorkflowSpec(BaseModel):
    name: str
    description: str
    nodes: List[WorkflowNodeSpec] = Field(validation_alias=AliasChoices("nodes", "stages"))
    aggregator_profile: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices(
            "aggregator_profile",
            "aggregator_role",
        ),
    )
    aggregator_task: Optional[str] = None
    max_parallel: int = Field(default=5, ge=1)
    timeout_per_agent: int = Field(default=300, ge=1)
    max_rounds: int = Field(default=1, ge=1)
    continue_on_failure: bool = True

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @property
    def stages(self) -> List[WorkflowNodeSpec]:
        """Legacy CollaborationPattern name."""
        return self.nodes

    @property
    def aggregator_role(self) -> Optional[str]:
        """Legacy CollaborationPattern name."""
        return self.aggregator_profile
