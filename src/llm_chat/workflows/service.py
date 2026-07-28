"""WorkflowDefinition 应用服务。"""

from __future__ import annotations

from string import Formatter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Protocol
from uuid import uuid4

from llm_chat.work import (
    ArtifactFeedbackDecision,
    GrantStatus,
    PlanStatus,
    WorkItemStatus,
)

from .models import WorkflowDefinition, WorkflowParameter, WorkflowVersion


class WorkflowRepository(Protocol):
    def create_workflow(
        self,
        definition: WorkflowDefinition,
        version: WorkflowVersion,
    ) -> bool:
        ...

    def get_workflow(self, workflow_id: str) -> Optional[WorkflowDefinition]:
        ...

    def list_workflows(self, limit: int = 100) -> List[WorkflowDefinition]:
        ...

    def get_workflow_version(
        self,
        workflow_id: str,
        version: Optional[int] = None,
    ) -> Optional[WorkflowVersion]:
        ...

    def create_workflow_version(
        self,
        version: WorkflowVersion,
        *,
        expected_latest_version: int,
    ) -> bool:
        ...


class WorkflowService:
    def __init__(self, *, repository: WorkflowRepository, work_items):
        self.repository = repository
        self.work_items = work_items

    def create_from_work_item(
        self,
        work_item_id: str,
        *,
        name: Optional[str] = None,
        description: str = "",
        objective_template: Optional[str] = None,
        parameters: Optional[List[WorkflowParameter]] = None,
    ):
        detail = self.work_items.detail(work_item_id)
        if detail.work_item.status != WorkItemStatus.COMPLETED:
            raise ValueError("only a completed work item can become a workflow")
        if not detail.artifacts:
            raise ValueError("workflow source must contain at least one artifact")
        latest_feedback = {}
        for feedback in detail.artifact_feedback:
            latest_feedback.setdefault(feedback.artifact_id, feedback)
        if latest_feedback and not any(
            item.decision == ArtifactFeedbackDecision.ACCEPTED for item in latest_feedback.values()
        ):
            raise ValueError("reviewed workflow source must have an accepted artifact")

        definition = WorkflowDefinition(
            name=(name or detail.work_item.title).strip(),
            description=description.strip(),
        )
        plan = next(
            (
                candidate
                for candidate in self.work_items.list_plan_revisions(work_item_id)
                if candidate.status == PlanStatus.APPROVED
            ),
            None,
        )
        plan_steps = self._portable_plan_steps(plan) if plan else []
        version = WorkflowVersion(
            workflow_id=definition.id,
            version=1,
            objective_template=(objective_template or detail.work_item.objective).strip(),
            parameters=parameters or [],
            plan_steps=plan_steps,
            expected_artifact_kinds=list(
                dict.fromkeys(artifact.kind for artifact in detail.artifacts)
            ),
            required_resources=[
                {
                    "capability": grant.capability,
                    "resource_type": grant.resource_type.value,
                    "resource": grant.resource,
                    "scope": grant.scope.value,
                }
                for grant in detail.grants
                if grant.status == GrantStatus.ACTIVE
                and (grant.expires_at is None or grant.expires_at > datetime.now(timezone.utc))
            ],
            source_work_item_id=work_item_id,
            approval_policy={"resource_grants_required": True},
            failure_policy={"mode": "pause_for_review"},
        )
        self._validate_template(version)
        if not self.repository.create_workflow(definition, version):
            raise ValueError(f"workflow already exists: {definition.id}")
        return definition, version

    def render(
        self,
        workflow_id: str,
        *,
        version: Optional[int] = None,
        inputs: Optional[Dict[str, str]] = None,
    ):
        definition = self.repository.get_workflow(workflow_id)
        if definition is None:
            raise KeyError(f"Unknown workflow: {workflow_id}")
        workflow_version = self.repository.get_workflow_version(
            workflow_id,
            version,
        )
        if workflow_version is None:
            raise KeyError(f"Unknown workflow version: {workflow_id}@{version}")
        values = dict(inputs or {})
        allowed = {parameter.name for parameter in workflow_version.parameters}
        unknown = set(values) - allowed
        if unknown:
            raise ValueError(f"unknown workflow inputs: {', '.join(sorted(unknown))}")
        for parameter in workflow_version.parameters:
            if parameter.name not in values and parameter.default is not None:
                values[parameter.name] = parameter.default
            if parameter.required and parameter.name not in values:
                raise ValueError(f"missing workflow input: {parameter.name}")
        return workflow_version, workflow_version.objective_template.format_map(values)

    def revise(
        self,
        workflow_id: str,
        *,
        change_summary: str,
        objective_template: Optional[str] = None,
        parameters: Optional[List[WorkflowParameter]] = None,
    ) -> WorkflowVersion:
        definition, current = self.get(workflow_id)
        change_summary = change_summary.strip()
        if not change_summary:
            raise ValueError("workflow revision requires a change summary")
        revised = current.model_copy(
            update={
                "id": f"workflow_version_{uuid4().hex}",
                "version": current.version + 1,
                "objective_template": (
                    objective_template.strip()
                    if objective_template is not None
                    else current.objective_template
                ),
                "parameters": (parameters if parameters is not None else current.parameters),
                "change_summary": change_summary,
                "created_at": datetime.now(timezone.utc),
            },
            deep=True,
        )
        self._validate_template(revised)
        if not self.repository.create_workflow_version(
            revised,
            expected_latest_version=definition.latest_version,
        ):
            raise ValueError("workflow was revised concurrently; reload and retry")
        return revised

    def list(self, *, limit: int = 100):
        return self.repository.list_workflows(limit=limit)

    def get(self, workflow_id: str, *, version: Optional[int] = None):
        definition = self.repository.get_workflow(workflow_id)
        if definition is None:
            raise KeyError(f"Unknown workflow: {workflow_id}")
        workflow_version = self.repository.get_workflow_version(
            workflow_id,
            version,
        )
        if workflow_version is None:
            raise KeyError(f"Unknown workflow version: {workflow_id}@{version}")
        return definition, workflow_version

    @staticmethod
    def _validate_template(version: WorkflowVersion) -> None:
        declared = {parameter.name for parameter in version.parameters}
        referenced = {
            field_name
            for _, field_name, _, _ in Formatter().parse(version.objective_template)
            if field_name
        }
        undeclared = referenced - declared
        if undeclared:
            raise ValueError(
                "workflow template has undeclared parameters: " + ", ".join(sorted(undeclared))
            )

    @staticmethod
    def _portable_plan_steps(plan) -> List[Dict[str, Any]]:
        if plan.status != PlanStatus.APPROVED:
            return []
        alias_by_id = {step.id: str(step.position) for step in plan.steps}
        return [
            {
                "id": alias_by_id[step.id],
                "title": step.title,
                "description": step.description,
                "depends_on": [alias_by_id[dependency] for dependency in step.depends_on],
                "expected_artifact_kind": (
                    step.expected_artifact_kind.value if step.expected_artifact_kind else None
                ),
                "required_capabilities": list(step.required_capabilities),
                "metadata": dict(step.metadata),
            }
            for step in plan.steps
        ]
