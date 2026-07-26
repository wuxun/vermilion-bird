"""WorkItem 应用服务：协调产品任务、Run 与 Artifact。"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Dict, List, Optional, Protocol

from llm_chat.runtime import RecoveryPolicy, Run, RunEvent, RunManager, RunStatus, RunType

from .models import (
    Artifact,
    ArtifactKind,
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


class WorkItemService:
    """产品任务的唯一写入口，并把主 Run 生命周期投影为任务状态。"""

    def __init__(
        self,
        *,
        repository: WorkItemRepository,
        runs: RunManager,
    ):
        self.repository = repository
        self.runs = runs
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
        workspace: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> WorkItem:
        objective = objective.strip()
        if not objective:
            raise ValueError("work item objective cannot be empty")
        if not isinstance(kind, WorkItemKind):
            kind = WorkItemKind(kind)
        if idempotency_key:
            existing = self.repository.get_work_item_by_idempotency_key(idempotency_key)
            if existing is not None:
                return existing
        display_title = (title or objective[:80]).strip()
        if not display_title:
            raise ValueError("work item title cannot be empty")
        item = WorkItem(
            title=display_title,
            objective=objective,
            kind=kind,
            conversation_id=conversation_id,
            workflow_id=workflow_id,
            workspace=workspace,
            idempotency_key=idempotency_key,
            metadata=metadata or {},
        )
        created = self.repository.create_work_item(item)
        if not created and idempotency_key:
            existing = self.repository.get_work_item_by_idempotency_key(idempotency_key)
            if existing is not None:
                return existing
        if not created:
            raise ValueError(f"work item already exists: {item.id}")
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
            raise ValueError(
                f"Idempotent run {run.id} belongs to work item {run.work_item_id}"
            )
        with self._lock:
            item = self._require(work_item_id)
            item.root_run_id = item.root_run_id or run.id
            item.latest_run_id = run.id
            self._apply_run_status(item, run)
            self.repository.save_work_item(item)
        self._notify(item)
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
        )

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
        self._notify(item)

    @staticmethod
    def _apply_run_status(item: WorkItem, run: Run) -> None:
        mapping = {
            RunStatus.PENDING: WorkItemStatus.READY,
            RunStatus.RUNNING: WorkItemStatus.RUNNING,
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
            and run.status in {RunStatus.PENDING, RunStatus.RUNNING}
            for run in linked_runs
        )
        paused_children = any(
            run.id != primary.id
            and run.status == RunStatus.PAUSED
            for run in linked_runs
        )

        self._apply_run_status(item, primary)
        if approval_waiting:
            item.status = WorkItemStatus.WAITING_APPROVAL
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
