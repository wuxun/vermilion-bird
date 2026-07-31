"""WorkItem 应用服务：协调产品任务、Run 与 Artifact。"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol

from llm_chat.runtime import RecoveryPolicy, Run, RunEvent, RunManager, RunStatus, RunType
from llm_chat.product_events import ProductEventService, ProductEventType

from .models import (
    Artifact,
    ArtifactFeedback,
    ArtifactFeedbackDecision,
    ArtifactKind,
    ArtifactReviewPolicy,
    PlanRevision,
    PlanStatus,
    PlanStep,
    PlanStepStatus,
    ResourceGrant,
    WorkItem,
    WorkItemDetail,
    WorkItemKind,
    WorkItemStatus,
    utc_now,
)

WorkItemObserver = Callable[[WorkItem], None]
logger = logging.getLogger(__name__)


class WorkItemRepository(Protocol):
    """WorkItemService 所需的最小持久化端口。"""

    def create_work_item(self, work_item: WorkItem) -> bool:
        ...

    def save_work_item(self, work_item: WorkItem) -> None:
        ...

    def get_work_item(self, work_item_id: str) -> Optional[WorkItem]:
        ...

    def get_work_item_by_idempotency_key(self, idempotency_key: str) -> Optional[WorkItem]:
        ...

    def get_work_item_by_series_key(self, series_key: str) -> Optional[WorkItem]:
        ...

    def list_work_items(
        self,
        limit: int = 50,
        *,
        offset: int = 0,
        status: Optional[WorkItemStatus] = None,
        kind: Optional[WorkItemKind] = None,
        conversation_id: Optional[str] = None,
    ) -> List[WorkItem]:
        ...

    def save_artifact(self, artifact: Artifact) -> None:
        ...

    def create_artifact(self, artifact: Artifact) -> bool:
        ...

    def get_artifact(self, artifact_id: str) -> Optional[Artifact]:
        ...

    def get_artifact_by_idempotency_key(self, idempotency_key: str) -> Optional[Artifact]:
        ...

    def list_artifacts(
        self,
        work_item_id: str,
        *,
        limit: int = 200,
    ) -> List[Artifact]:
        ...

    def create_artifact_feedback(self, feedback: ArtifactFeedback) -> bool:
        ...

    def list_artifact_feedback(
        self,
        work_item_id: str,
        *,
        artifact_id: Optional[str] = None,
        limit: int = 500,
    ) -> List[ArtifactFeedback]:
        ...

    def create_plan_revision(self, plan: PlanRevision) -> bool:
        ...

    def get_plan_revision(self, plan_id: str) -> Optional[PlanRevision]:
        ...

    def get_latest_plan_revision(
        self,
        work_item_id: str,
        *,
        approved_only: bool = False,
    ) -> Optional[PlanRevision]:
        ...

    def list_plan_revisions(
        self,
        work_item_id: str,
        *,
        limit: int = 50,
    ) -> List[PlanRevision]:
        ...

    def approve_plan_revision(self, plan_id: str, *, approved_at) -> bool:
        ...

    def update_plan_step_status(
        self,
        plan_id: str,
        step_id: str,
        status: PlanStepStatus,
    ) -> bool:
        ...

    def list_resource_grants(
        self,
        *,
        work_item_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        status=None,
        limit: int = 200,
    ) -> List[ResourceGrant]:
        ...


class WorkItemService:
    """产品任务的唯一写入口，并把主 Run 生命周期投影为任务状态。"""

    def __init__(
        self,
        *,
        repository: WorkItemRepository,
        runs: RunManager,
        product_events: Optional[ProductEventService] = None,
    ):
        self.repository = repository
        self.runs = runs
        self.product_events = product_events
        self._lock = threading.RLock()
        self._observers: List[WorkItemObserver] = []
        self._unsubscribe_run = self.runs.subscribe(self._on_run_event)
        self.reconcile()

    def create(
        self,
        *,
        objective: str,
        title: Optional[str] = None,
        kind: WorkItemKind = WorkItemKind.TASK,
        conversation_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        series_key: Optional[str] = None,
        artifact_review_policy: ArtifactReviewPolicy = ArtifactReviewPolicy.REQUIRED,
        workspace: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> WorkItem:
        objective = objective.strip()
        if not objective:
            raise ValueError("work item objective cannot be empty")
        if not isinstance(kind, WorkItemKind):
            kind = WorkItemKind(kind)
        if not isinstance(artifact_review_policy, ArtifactReviewPolicy):
            artifact_review_policy = ArtifactReviewPolicy(artifact_review_policy)
        series_key = (series_key or "").strip() or None
        display_title = (title or objective[:80]).strip()
        if not display_title:
            raise ValueError("work item title cannot be empty")
        if series_key:
            existing = self.repository.get_work_item_by_series_key(series_key)
            if existing is not None:
                existing.title = display_title
                existing.objective = objective
                existing.kind = kind
                existing.artifact_review_policy = artifact_review_policy
                existing.conversation_id = conversation_id or existing.conversation_id
                existing.workflow_id = workflow_id or existing.workflow_id
                existing.workspace = workspace or existing.workspace
                if metadata:
                    existing.metadata.update(metadata)
                existing.updated_at = utc_now()
                self.repository.save_work_item(existing)
                self._notify(existing)
                return existing.model_copy(deep=True)
        if idempotency_key:
            existing = self.repository.get_work_item_by_idempotency_key(idempotency_key)
            if existing is not None:
                return existing
        item = WorkItem(
            title=display_title,
            objective=objective,
            kind=kind,
            conversation_id=conversation_id,
            workflow_id=workflow_id,
            series_key=series_key,
            artifact_review_policy=artifact_review_policy,
            workspace=workspace,
            idempotency_key=idempotency_key,
            metadata=metadata or {},
        )
        created = self.repository.create_work_item(item)
        if not created and idempotency_key:
            existing = self.repository.get_work_item_by_idempotency_key(idempotency_key)
            if existing is not None:
                return existing
        if not created and series_key:
            existing = self.repository.get_work_item_by_series_key(series_key)
            if existing is not None:
                return existing.model_copy(deep=True)
        if not created:
            raise ValueError(f"work item already exists: {item.id}")
        self._record_product_event(
            ProductEventType.WORK_ITEM_CREATED,
            subject_type="work_item",
            subject_id=item.id,
            work_item_id=item.id,
            conversation_id=item.conversation_id,
            properties={
                "kind": item.kind.value,
                "review_policy": item.artifact_review_policy.value,
                "source": self._event_source(item.metadata.get("source")),
            },
            deduplication_key=f"work-item:{item.id}:created",
        )
        self._notify(item)
        return item.model_copy(deep=True)

    def start(
        self,
        work_item_id: str,
        *,
        run_type: RunType = RunType.WORKFLOW,
        input: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
        recovery_policy: RecoveryPolicy = RecoveryPolicy.RESUME,
        max_attempts: int = 1,
    ) -> Run:
        item = self._require(work_item_id)
        run_metadata = dict(metadata or {})
        run_metadata.setdefault("work_item_kind", item.kind.value)
        run = self.runs.start(
            run_type,
            conversation_id=item.conversation_id,
            work_item_id=item.id,
            input=input or {"objective": item.objective},
            metadata=run_metadata,
            idempotency_key=idempotency_key,
            recovery_policy=recovery_policy,
            max_attempts=max_attempts,
        )
        if run.work_item_id != item.id:
            raise ValueError(f"Idempotent run {run.id} belongs to work item {run.work_item_id}")
        with self._lock:
            item = self._require(work_item_id)
            item.root_run_id = item.root_run_id or run.id
            item.latest_run_id = run.id
            self._apply_run_status(item, run)
            self.repository.save_work_item(item)
        self._notify(item)
        self._record_product_event(
            ProductEventType.WORK_ITEM_STARTED,
            subject_type="work_item",
            subject_id=item.id,
            work_item_id=item.id,
            conversation_id=item.conversation_id,
            properties={
                "kind": item.kind.value,
                "run_type": run.type.value,
                "source": self._event_source(item.metadata.get("source")),
            },
            deduplication_key=f"run:{run.id}:work-item-started",
        )
        return run

    def attach_run(
        self,
        work_item_id: str,
        run_id: str,
        *,
        make_primary: bool = False,
    ) -> WorkItem:
        item = self._require(work_item_id)
        run = self.runs.get(run_id)
        if run is None:
            raise KeyError(f"Unknown run: {run_id}")
        if run.work_item_id and run.work_item_id != work_item_id:
            raise ValueError(f"Run {run_id} belongs to another work item")
        if run.work_item_id != work_item_id:
            raise ValueError("existing runs must be linked by the RunManager before attachment")
        with self._lock:
            item.root_run_id = item.root_run_id or run.id
            if make_primary or item.latest_run_id is None:
                item.latest_run_id = run.id
                self._apply_run_status(item, run)
            item.updated_at = utc_now()
            self.repository.save_work_item(item)
        self._notify(item)
        return item.model_copy(deep=True)

    def add_artifact(
        self,
        work_item_id: str,
        *,
        name: str,
        kind: ArtifactKind = ArtifactKind.OTHER,
        run_id: Optional[str] = None,
        uri: Optional[str] = None,
        content: Optional[str] = None,
        content_preview: Optional[str] = None,
        checksum: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Artifact:
        self._require(work_item_id)
        name = name.strip()
        if not name:
            raise ValueError("artifact name cannot be empty")
        if not isinstance(kind, ArtifactKind):
            kind = ArtifactKind(kind)
        if idempotency_key:
            existing = self.repository.get_artifact_by_idempotency_key(idempotency_key)
            if existing is not None:
                if existing.work_item_id != work_item_id:
                    raise ValueError("artifact idempotency key belongs to another work item")
                return existing
        if run_id:
            run = self.runs.get(run_id)
            if run is None:
                raise KeyError(f"Unknown run: {run_id}")
            if run.work_item_id != work_item_id:
                raise ValueError(f"Run {run_id} does not belong to work item {work_item_id}")
        artifact = Artifact(
            work_item_id=work_item_id,
            run_id=run_id,
            kind=kind,
            name=name,
            uri=uri,
            content=content,
            content_preview=content_preview,
            checksum=checksum,
            idempotency_key=idempotency_key,
            metadata=metadata or {},
        )
        created = self.repository.create_artifact(artifact)
        if not created and idempotency_key:
            existing = self.repository.get_artifact_by_idempotency_key(idempotency_key)
            if existing is not None:
                return existing
        if not created:
            raise ValueError(f"artifact already exists: {artifact.id}")
        item = self._require(work_item_id)
        self._record_product_event(
            ProductEventType.ARTIFACT_CREATED,
            subject_type="artifact",
            subject_id=artifact.id,
            work_item_id=work_item_id,
            conversation_id=item.conversation_id,
            properties={"artifact_kind": artifact.kind.value},
            deduplication_key=f"artifact:{artifact.id}:created",
        )
        return artifact.model_copy(deep=True)

    def bind_conversation(self, work_item_id: str, conversation_id: str) -> WorkItem:
        conversation_id = conversation_id.strip()
        if not conversation_id:
            raise ValueError("conversation id cannot be empty")
        item = self._require(work_item_id)
        if item.conversation_id and item.conversation_id != conversation_id:
            raise ValueError(f"work item {work_item_id} is already bound to another conversation")
        item.conversation_id = conversation_id
        item.updated_at = utc_now()
        self.repository.save_work_item(item)
        self._notify(item)
        return item.model_copy(deep=True)

    def get(self, work_item_id: str) -> Optional[WorkItem]:
        item = self.repository.get_work_item(work_item_id)
        return item.model_copy(deep=True) if item else None

    def detail(self, work_item_id: str) -> WorkItemDetail:
        item = self._require(work_item_id)
        return WorkItemDetail(
            work_item=item,
            runs=self.runs.list(limit=1000, work_item_id=work_item_id),
            artifacts=self.repository.list_artifacts(work_item_id),
            artifact_feedback=self.repository.list_artifact_feedback(
                work_item_id,
                limit=500,
            ),
            plan=self.repository.get_latest_plan_revision(work_item_id),
            grants=self.repository.list_resource_grants(
                work_item_id=work_item_id,
                workflow_id=item.workflow_id,
                limit=200,
            ),
        )

    def submit_artifact_feedback(
        self,
        work_item_id: str,
        artifact_id: str,
        *,
        decision: ArtifactFeedbackDecision,
        note: str = "",
        created_by: str = "local-user",
    ) -> ArtifactFeedback:
        self._require(work_item_id)
        artifact = self.repository.get_artifact(artifact_id)
        if artifact is None or artifact.work_item_id != work_item_id:
            raise KeyError(f"Unknown artifact: {artifact_id}")
        if not isinstance(decision, ArtifactFeedbackDecision):
            decision = ArtifactFeedbackDecision(decision)
        feedback = ArtifactFeedback(
            artifact_id=artifact_id,
            work_item_id=work_item_id,
            decision=decision,
            note=note.strip(),
            created_by=created_by.strip() or "local-user",
        )
        if not self.repository.create_artifact_feedback(feedback):
            raise ValueError(f"artifact feedback already exists: {feedback.id}")
        item = self._require(work_item_id)
        self._record_product_event(
            ProductEventType.ARTIFACT_FEEDBACK,
            subject_type="artifact",
            subject_id=artifact_id,
            work_item_id=work_item_id,
            conversation_id=item.conversation_id,
            properties={
                "artifact_kind": artifact.kind.value,
                "decision": feedback.decision.value,
            },
            deduplication_key=f"artifact-feedback:{feedback.id}",
        )
        return feedback.model_copy(deep=True)

    def record_artifact_viewed(
        self,
        artifact_id: str,
        *,
        entrypoint: str = "gui",
    ) -> None:
        artifact = self.repository.get_artifact(artifact_id)
        if artifact is None:
            raise KeyError(f"Unknown artifact: {artifact_id}")
        item = self._require(artifact.work_item_id)
        normalized_entrypoint = entrypoint if entrypoint in {"cli", "gui"} else "other"
        self._record_product_event(
            ProductEventType.ARTIFACT_VIEWED,
            subject_type="artifact",
            subject_id=artifact.id,
            work_item_id=artifact.work_item_id,
            conversation_id=item.conversation_id,
            properties={
                "artifact_kind": artifact.kind.value,
                "entrypoint": normalized_entrypoint,
            },
        )

    def export_artifact(
        self,
        artifact_id: str,
        destination: str,
        *,
        overwrite: bool = False,
    ) -> str:
        """把内嵌内容或本地文件原子导出到用户指定位置。"""

        artifact = self.repository.get_artifact(artifact_id)
        if artifact is None:
            raise KeyError(f"Unknown artifact: {artifact_id}")
        destination_path = Path(destination).expanduser()
        if destination_path.exists() and destination_path.is_dir():
            destination_path = destination_path / artifact.name
        destination_path = destination_path.resolve(strict=False)
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        if destination_path.exists() and not overwrite:
            raise FileExistsError(f"destination already exists: {destination_path}")

        content = artifact.content
        source = None
        if content is None and artifact.uri:
            if artifact.uri.startswith(("http://", "https://")):
                content = artifact.uri
            else:
                source = Path(artifact.uri).expanduser().resolve(strict=False)
                if not source.is_file():
                    raise FileNotFoundError(f"artifact source not found: {source}")
        if content is None and source is None:
            content = artifact.content_preview
        if content is None and source is None:
            raise ValueError(f"artifact {artifact_id} has no exportable content")

        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination_path.name}.",
            suffix=".tmp",
            dir=str(destination_path.parent),
        )
        os.close(file_descriptor)
        temporary_path = Path(temporary_name)
        try:
            if source is not None:
                shutil.copy2(source, temporary_path)
            else:
                temporary_path.write_text(content, encoding="utf-8")
            temporary_path.replace(destination_path)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()
        item = self._require(artifact.work_item_id)
        self._record_product_event(
            ProductEventType.ARTIFACT_EXPORTED,
            subject_type="artifact",
            subject_id=artifact.id,
            work_item_id=artifact.work_item_id,
            conversation_id=item.conversation_id,
            properties={
                "artifact_kind": artifact.kind.value,
                "export_kind": self._export_kind(destination_path),
            },
        )
        return str(destination_path)

    def create_plan_revision(
        self,
        work_item_id: str,
        *,
        summary: str,
        steps: List[Dict[str, Any]],
        change_summary: str = "",
        created_by: str = "local-user",
        approve: bool = False,
    ) -> PlanRevision:
        """创建不可覆盖的计划版本，并可在同一用例中显式批准。"""

        self._require(work_item_id)
        summary = summary.strip()
        if not summary:
            raise ValueError("plan summary cannot be empty")
        if not steps:
            raise ValueError("plan must contain at least one step")
        latest = self.repository.get_latest_plan_revision(work_item_id)
        plan = PlanRevision(
            work_item_id=work_item_id,
            version=(latest.version + 1) if latest else 1,
            summary=summary,
            change_summary=change_summary.strip(),
            created_by=created_by.strip() or "local-user",
        )
        plan.steps = self._build_plan_steps(plan.id, steps)
        if not self.repository.create_plan_revision(plan):
            raise ValueError(f"plan version {plan.version} already exists for {work_item_id}")
        if approve:
            return self.approve_plan_revision(work_item_id, plan.id)
        return plan.model_copy(deep=True)

    def approve_plan_revision(
        self,
        work_item_id: str,
        plan_id: str,
    ) -> PlanRevision:
        self._require(work_item_id)
        plan = self.repository.get_plan_revision(plan_id)
        if plan is None or plan.work_item_id != work_item_id:
            raise KeyError(f"Unknown plan revision: {plan_id}")
        latest = self.repository.get_latest_plan_revision(work_item_id)
        if latest is None or latest.id != plan.id:
            raise ValueError("only the latest plan revision can be approved")
        if plan.status == PlanStatus.APPROVED:
            return plan
        approved_at = utc_now()
        if not self.repository.approve_plan_revision(
            plan.id,
            approved_at=approved_at,
        ):
            raise ValueError(f"plan revision cannot be approved: {plan.id}")
        approved = self.repository.get_plan_revision(plan.id)
        assert approved is not None
        return approved

    def update_plan_step(
        self,
        work_item_id: str,
        step_id: str,
        status: PlanStepStatus,
    ) -> PlanRevision:
        self._require(work_item_id)
        plan = self.repository.get_latest_plan_revision(
            work_item_id,
            approved_only=True,
        )
        if plan is None:
            raise ValueError("work item has no approved plan")
        if not isinstance(status, PlanStepStatus):
            status = PlanStepStatus(status)
        if not self.repository.update_plan_step_status(plan.id, step_id, status):
            raise KeyError(f"Unknown plan step: {step_id}")
        updated = self.repository.get_plan_revision(plan.id)
        assert updated is not None
        return updated

    def list_plan_revisions(
        self,
        work_item_id: str,
        *,
        limit: int = 50,
    ) -> List[PlanRevision]:
        self._require(work_item_id)
        return self.repository.list_plan_revisions(work_item_id, limit=limit)

    def list(
        self,
        limit: int = 50,
        *,
        offset: int = 0,
        status: Optional[WorkItemStatus] = None,
        kind: Optional[WorkItemKind] = None,
        conversation_id: Optional[str] = None,
    ) -> List[WorkItem]:
        return self.repository.list_work_items(
            limit=limit,
            offset=offset,
            status=status,
            kind=kind,
            conversation_id=conversation_id,
        )

    @staticmethod
    def _build_plan_steps(
        plan_id: str,
        definitions: List[Dict[str, Any]],
    ) -> List[PlanStep]:
        steps = []
        aliases: Dict[str, str] = {}
        for position, definition in enumerate(definitions, start=1):
            title = str(definition.get("title", "")).strip()
            if not title:
                raise ValueError(f"plan step {position} title cannot be empty")
            step = PlanStep(
                plan_revision_id=plan_id,
                position=position,
                title=title,
                description=str(definition.get("description", "")).strip(),
                expected_artifact_kind=definition.get("expected_artifact_kind"),
                required_capabilities=list(definition.get("required_capabilities", [])),
                metadata=dict(definition.get("metadata", {})),
            )
            alias = str(definition.get("id", position))
            if alias in aliases:
                raise ValueError(f"duplicate plan step id: {alias}")
            aliases[alias] = step.id
            steps.append(step)
        for step, definition in zip(steps, definitions):
            dependencies = []
            for dependency in definition.get("depends_on", []):
                key = str(dependency)
                if key not in aliases:
                    raise ValueError(f"unknown dependency {key} for plan step {step.position}")
                dependencies.append(aliases[key])
            if step.id in dependencies:
                raise ValueError("plan step cannot depend on itself")
            step.depends_on = dependencies
        dependencies_by_id = {step.id: set(step.depends_on) for step in steps}
        visiting = set()
        visited = set()

        def visit(step_id: str) -> None:
            if step_id in visiting:
                raise ValueError("plan step dependencies contain a cycle")
            if step_id in visited:
                return
            visiting.add(step_id)
            for dependency in dependencies_by_id[step_id]:
                visit(dependency)
            visiting.remove(step_id)
            visited.add(step_id)

        for step in steps:
            visit(step.id)
        return steps

    def reconcile(self, *, limit: int = 1000) -> List[WorkItem]:
        """启动时用主 Run 与阻塞型子 Run 修复任务状态投影。"""

        changed: List[WorkItem] = []
        for item in self.repository.list_work_items(limit=limit):
            previous = (
                item.status,
                item.completed_at,
                item.root_run_id,
                item.latest_run_id,
            )
            run = self.runs.get(item.latest_run_id) if item.latest_run_id else None
            if run is None:
                linked_runs = self.runs.list(limit=1000, work_item_id=item.id)
                root_runs = [candidate for candidate in linked_runs if not candidate.parent_run_id]
                if not root_runs:
                    continue
                # list() 按创建时间倒序；首项是当前执行，末项是最初执行。
                run = root_runs[0]
                item.root_run_id = item.root_run_id or root_runs[-1].id
                item.latest_run_id = run.id
            if run is None:
                continue
            self._apply_aggregate_status(item, run)
            current = (
                item.status,
                item.completed_at,
                item.root_run_id,
                item.latest_run_id,
            )
            if previous != current:
                self.repository.save_work_item(item)
                changed.append(item.model_copy(deep=True))
                self._record_terminal_event(item, run)
        return changed

    def subscribe(self, observer: WorkItemObserver) -> Callable[[], None]:
        with self._lock:
            self._observers.append(observer)

        def unsubscribe() -> None:
            with self._lock:
                if observer in self._observers:
                    self._observers.remove(observer)

        return unsubscribe

    def close(self) -> None:
        self._unsubscribe_run()

    def _on_run_event(self, run: Run, event: RunEvent) -> None:
        if not run.work_item_id:
            return
        item = self.repository.get_work_item(run.work_item_id)
        if item is None:
            return
        previous = (
            item.status,
            item.completed_at,
            item.root_run_id,
            item.latest_run_id,
        )
        if event.type == "run.started" and not run.parent_run_id:
            item.root_run_id = item.root_run_id or run.id
            item.latest_run_id = run.id
        primary = self.runs.get(item.latest_run_id) if item.latest_run_id else None
        if primary is None:
            return
        self._apply_aggregate_status(item, primary)
        current = (
            item.status,
            item.completed_at,
            item.root_run_id,
            item.latest_run_id,
        )
        if previous == current:
            return
        self.repository.save_work_item(item)
        self._record_terminal_event(item, primary)
        self._notify(item)

    def _record_terminal_event(self, item: WorkItem, run: Run) -> None:
        if not item.status.terminal:
            return
        self._record_product_event(
            ProductEventType.WORK_ITEM_TERMINAL,
            subject_type="work_item",
            subject_id=item.id,
            work_item_id=item.id,
            conversation_id=item.conversation_id,
            properties={
                "kind": item.kind.value,
                "run_type": run.type.value,
                "source": self._event_source(item.metadata.get("source")),
                "status": item.status.value,
            },
            deduplication_key=f"work-item:{item.id}:run:{run.id}:terminal:{item.status.value}",
        )

    def _record_product_event(self, event_type: ProductEventType, **kwargs) -> None:
        if self.product_events is not None:
            self.product_events.safe_record(event_type, **kwargs)

    @staticmethod
    def _event_source(value: Any) -> str:
        known = {"chat", "cli", "gui", "proactive", "scheduler", "webhook", "workflow"}
        normalized = str(value or "unknown").strip().lower()
        return normalized if normalized in known else "other"

    @staticmethod
    def _export_kind(path: Path) -> str:
        known = {
            ".csv",
            ".docx",
            ".html",
            ".json",
            ".md",
            ".pdf",
            ".pptx",
            ".txt",
            ".xlsx",
        }
        suffix = path.suffix.lower()
        return suffix[1:] if suffix in known else "other"

    @staticmethod
    def _apply_run_status(item: WorkItem, run: Run) -> None:
        mapping = {
            RunStatus.PENDING: WorkItemStatus.READY,
            RunStatus.RUNNING: WorkItemStatus.RUNNING,
            RunStatus.CANCEL_REQUESTED: WorkItemStatus.CANCELLING,
            RunStatus.PAUSE_REQUESTED: WorkItemStatus.PAUSING,
            RunStatus.WAITING_APPROVAL: WorkItemStatus.WAITING_APPROVAL,
            RunStatus.PAUSED: WorkItemStatus.PAUSED,
            RunStatus.COMPLETED: WorkItemStatus.COMPLETED,
            RunStatus.FAILED: WorkItemStatus.FAILED,
            RunStatus.CANCELLED: WorkItemStatus.CANCELLED,
        }
        item.status = mapping[run.status]
        item.updated_at = utc_now()
        item.completed_at = run.finished_at if run.status.terminal else None

    def _apply_aggregate_status(self, item: WorkItem, primary: Run) -> None:
        """主 Run 决定终态，阻塞型子 Run 可暂时覆盖为运行中/待审批。"""

        linked_runs = self.runs.list(limit=1000, work_item_id=item.id)
        approval_waiting = any(
            run.id != primary.id
            and run.status == RunStatus.PAUSED
            and bool(run.metadata.get("approval_kind"))
            for run in linked_runs
        )
        active_children = any(
            run.id != primary.id
            and run.status
            in {
                RunStatus.PENDING,
                RunStatus.RUNNING,
                RunStatus.CANCEL_REQUESTED,
                RunStatus.PAUSE_REQUESTED,
            }
            for run in linked_runs
        )
        paused_children = any(
            run.id != primary.id and run.status == RunStatus.PAUSED for run in linked_runs
        )

        self._apply_run_status(item, primary)
        if approval_waiting:
            item.status = WorkItemStatus.WAITING_APPROVAL
            item.completed_at = None
        elif any(run.status == RunStatus.CANCEL_REQUESTED for run in linked_runs):
            item.status = WorkItemStatus.CANCELLING
            item.completed_at = None
        elif any(run.status == RunStatus.PAUSE_REQUESTED for run in linked_runs):
            item.status = WorkItemStatus.PAUSING
            item.completed_at = None
        elif primary.status.terminal and active_children:
            item.status = WorkItemStatus.RUNNING
            item.completed_at = None
        elif primary.status.terminal and paused_children:
            item.status = WorkItemStatus.PAUSED
            item.completed_at = None

    def _require(self, work_item_id: str) -> WorkItem:
        item = self.repository.get_work_item(work_item_id)
        if item is None:
            raise KeyError(f"Unknown work item: {work_item_id}")
        return item

    def _notify(self, item: WorkItem) -> None:
        snapshot = item.model_copy(deep=True)
        with self._lock:
            observers = list(self._observers)
        for observer in observers:
            try:
                observer(snapshot.model_copy(deep=True))
            except Exception:
                logger.warning("Work item observer failed", exc_info=True)
