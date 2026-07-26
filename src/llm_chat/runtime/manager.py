"""Thread-safe, instance-scoped Run lifecycle manager."""

from __future__ import annotations

import logging
import threading
from collections import deque
from datetime import timedelta
from typing import Any, Callable, Dict, List, Optional, Protocol
from uuid import uuid4

from .models import (
    RecoveryPolicy,
    Run,
    RunCheckpoint,
    RunEvent,
    RunStatus,
    RunType,
    utc_now,
)

logger = logging.getLogger(__name__)
RunObserver = Callable[[Run, RunEvent], None]


class RunRepository(Protocol):
    """RunManager 所需的最小持久化端口。"""

    def save_run(self, run: Run) -> None:
        ...

    def append_run_event(self, run_id: str, event: RunEvent) -> None:
        ...

    def create_run(self, run: Run) -> bool:
        ...

    def get_run(self, run_id: str) -> Optional[Run]:
        ...

    def get_run_by_idempotency_key(self, idempotency_key: str) -> Optional[Run]:
        ...

    def list_runs(
        self,
        limit: int = 50,
        *,
        offset: int = 0,
        status: Optional[RunStatus] = None,
        run_type: Optional[RunType] = None,
        conversation_id: Optional[str] = None,
    ) -> List[Run]:
        ...

    def list_child_runs(self, parent_run_id: str) -> List[Run]:
        ...

    def try_claim_run(
        self,
        run_id: str,
        *,
        owner: str,
        heartbeat_at,
        lease_expires_at,
    ) -> bool:
        ...

    def release_run_lease(self, run_id: str, *, owner: str) -> bool:
        ...


class RunManager:
    """管理 Run 生命周期，并可选地将其同步到持久化仓储。"""

    def __init__(
        self,
        max_history: int = 1000,
        *,
        repository: Optional[RunRepository] = None,
        recover_interrupted: bool = True,
        owner_id: Optional[str] = None,
    ):
        self._max_history = max_history
        self._repository = repository
        self.owner_id = owner_id or f"runner_{uuid4().hex}"
        self._runs: Dict[str, Run] = {}
        self._order: deque[str] = deque()
        self._idempotency: Dict[str, str] = {}
        self._observers: List[RunObserver] = []
        self._lock = threading.RLock()
        self._restore(recover_interrupted=recover_interrupted)

    def start(
        self,
        run_type: RunType,
        *,
        conversation_id: Optional[str] = None,
        parent_run_id: Optional[str] = None,
        input: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
        recovery_policy: RecoveryPolicy = RecoveryPolicy.FAIL,
        max_attempts: int = 1,
    ) -> Run:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if not isinstance(recovery_policy, RecoveryPolicy):
            recovery_policy = RecoveryPolicy(recovery_policy)

        if idempotency_key:
            existing = self._find_by_idempotency_key(idempotency_key)
            if existing is not None:
                return existing

        run = Run(
            type=run_type,
            parent_run_id=parent_run_id,
            conversation_id=conversation_id,
            input=input or {},
            metadata=metadata or {},
            idempotency_key=idempotency_key,
            recovery_policy=recovery_policy,
            max_attempts=max_attempts,
            status=RunStatus.RUNNING,
            started_at=utc_now(),
            heartbeat_at=utc_now(),
        )
        with self._lock:
            if idempotency_key:
                existing_id = self._idempotency.get(idempotency_key)
                if existing_id:
                    return self._runs[existing_id].model_copy(deep=True)
            if self._repository is not None:
                try:
                    created = self._repository.create_run(run.model_copy(deep=True))
                except Exception:
                    logger.warning("Failed to atomically create run", exc_info=True)
                    created = True
                    self._persist_run_locked(run)
                if not created and idempotency_key:
                    existing = self._repository.get_run_by_idempotency_key(idempotency_key)
                    if existing is not None:
                        self._remember_locked(existing)
                        return existing.model_copy(deep=True)
            self._runs[run.id] = run
            self._order.append(run.id)
            if idempotency_key:
                self._idempotency[idempotency_key] = run.id
            self._prune_locked()
            if self._repository is None:
                self._persist_run_locked(run)
        self.emit(run.id, "run.started")
        return run.model_copy(deep=True)

    def emit(self, run_id: str, event_type: str, data: Optional[Dict[str, Any]] = None) -> RunEvent:
        with self._lock:
            run = self._require_locked(run_id)
            event = RunEvent(
                sequence=len(run.events) + 1,
                type=event_type,
                data=data or {},
            )
            run.events.append(event)
            snapshot = run.model_copy(deep=True)
            observers = list(self._observers)
            self._persist_event_locked(run_id, event)

        for observer in observers:
            try:
                observer(snapshot, event.model_copy(deep=True))
            except Exception:
                logger.warning("Run observer failed", exc_info=True)
        return event.model_copy(deep=True)

    def complete(self, run_id: str, result: Any = None) -> Run:
        return self._finish(run_id, RunStatus.COMPLETED, result=result)

    def fail(self, run_id: str, error: str) -> Run:
        return self._finish(run_id, RunStatus.FAILED, error=error)

    def cancel(self, run_id: str) -> Run:
        return self._finish(run_id, RunStatus.CANCELLED)

    def reconcile_terminal(
        self,
        run_id: str,
        *,
        succeeded: bool,
        note: str,
        result: Any = None,
    ) -> Run:
        """按人工对账结果修正中断 Run，并追加不可变审计事件。"""

        note = note.strip()
        if not note:
            raise ValueError("reconciliation note cannot be empty")
        with self._lock:
            run = self._require_locked(run_id)
            if run.status == RunStatus.COMPLETED:
                raise ValueError(f"Run {run_id} is already completed")
            run.status = RunStatus.COMPLETED if succeeded else RunStatus.FAILED
            run.result = result if succeeded else run.result
            run.error = None if succeeded else note
            run.finished_at = utc_now()
            run.lease_owner = None
            run.lease_expires_at = None
            run.metadata["effect_reconciled"] = True
            self._persist_run_locked(run)
        self.emit(
            run_id,
            "run.effect_reconciled",
            {"succeeded": succeeded, "note": note},
        )
        restored = self.get(run_id)
        assert restored is not None
        return restored

    def checkpoint(
        self,
        run_id: str,
        *,
        cursor: str,
        state: Dict[str, Any],
        expected_version: Optional[int] = None,
    ) -> Run:
        """保存最新恢复点，可用 expected_version 防止陈旧写入。"""

        with self._lock:
            run = self._require_locked(run_id)
            if run.status.terminal:
                raise ValueError(f"Cannot checkpoint terminal run {run_id}")
            current_version = run.checkpoint.version if run.checkpoint else 0
            if expected_version is not None and expected_version != current_version:
                raise ValueError(
                    f"Checkpoint version conflict: expected {expected_version}, "
                    f"current {current_version}"
                )
            run.checkpoint = RunCheckpoint(
                cursor=cursor,
                state=state,
                version=current_version + 1,
            )
            self._persist_run_locked(run)
            version = run.checkpoint.version
        self.emit(
            run_id,
            "run.checkpointed",
            {"cursor": cursor, "version": version},
        )
        restored = self.get(run_id)
        assert restored is not None
        return restored

    def pause(self, run_id: str, reason: str = "manual") -> Run:
        with self._lock:
            run = self._require_locked(run_id)
            if run.status.terminal:
                raise ValueError(f"Cannot pause terminal run {run_id}")
            if run.status == RunStatus.PAUSED:
                return run.model_copy(deep=True)
            run.status = RunStatus.PAUSED
            run.lease_owner = None
            run.lease_expires_at = None
            run.metadata["pause_reason"] = reason
            self._persist_run_locked(run)
        self.emit(run_id, "run.paused", {"reason": reason})
        restored = self.get(run_id)
        assert restored is not None
        return restored

    def resume(self, run_id: str) -> Run:
        """从持久化检查点恢复同一次 attempt。"""

        with self._lock:
            run = self._require_locked(run_id)
            if run.status != RunStatus.PAUSED:
                raise ValueError(f"Run {run_id} is not paused")
            if run.checkpoint is None:
                raise ValueError(f"Run {run_id} has no checkpoint")
            run.status = RunStatus.RUNNING
            run.error = None
            run.finished_at = None
            run.started_at = run.started_at or utc_now()
            run.metadata.pop("pause_reason", None)
            self._persist_run_locked(run)
            checkpoint = run.checkpoint
        self.emit(
            run_id,
            "run.resumed",
            {"cursor": checkpoint.cursor, "version": checkpoint.version},
        )
        restored = self.get(run_id)
        assert restored is not None
        return restored

    def retry(self, run_id: str) -> Run:
        """在同一逻辑 Run 内开始下一次 attempt。"""

        with self._lock:
            run = self._require_locked(run_id)
            if run.status != RunStatus.FAILED:
                raise ValueError(f"Run {run_id} is not failed")
            if run.attempt >= run.max_attempts:
                raise ValueError(f"Run {run_id} has exhausted all attempts")
            run.attempt += 1
            run.status = RunStatus.RUNNING
            run.result = None
            run.error = None
            run.finished_at = None
            run.started_at = utc_now()
            run.heartbeat_at = run.started_at
            run.lease_owner = None
            run.lease_expires_at = None
            self._persist_run_locked(run)
            attempt = run.attempt
        self.emit(run_id, "run.retried", {"attempt": attempt})
        restored = self.get(run_id)
        assert restored is not None
        return restored

    def replay(self, run_id: str) -> Run:
        """以相同输入创建新的 Run，并保留来源链路。"""

        source = self.get(run_id)
        if source is None:
            raise KeyError(f"Unknown run: {run_id}")
        metadata = dict(source.metadata)
        metadata["replay_of_run_id"] = source.id
        return self.start(
            source.type,
            conversation_id=source.conversation_id,
            parent_run_id=source.id,
            input=source.input,
            metadata=metadata,
            recovery_policy=source.recovery_policy,
            max_attempts=source.max_attempts,
        )

    def claim(
        self,
        run_id: str,
        *,
        owner: Optional[str] = None,
        lease_seconds: int = 60,
    ) -> bool:
        """获取可续期租约，阻止多个进程同时执行一个 Run。"""

        if lease_seconds < 1:
            raise ValueError("lease_seconds must be at least 1")
        owner = owner or self.owner_id
        now = utc_now()
        expires_at = now + timedelta(seconds=lease_seconds)
        with self._lock:
            run = self._require_locked(run_id)
            if run.status.terminal:
                return False
            if self._repository is not None:
                try:
                    claimed = self._repository.try_claim_run(
                        run_id,
                        owner=owner,
                        heartbeat_at=now,
                        lease_expires_at=expires_at,
                    )
                except Exception:
                    logger.warning("Failed to claim run %s", run_id, exc_info=True)
                    return False
                if not claimed:
                    return False
            elif (
                run.lease_owner
                and run.lease_owner != owner
                and run.lease_expires_at
                and run.lease_expires_at > now
            ):
                return False
            run.status = RunStatus.RUNNING
            run.lease_owner = owner
            run.heartbeat_at = now
            run.lease_expires_at = expires_at
            self._persist_run_locked(run)
        self.emit(run_id, "run.claimed", {"owner": owner})
        return True

    def heartbeat(
        self,
        run_id: str,
        *,
        owner: Optional[str] = None,
        lease_seconds: int = 60,
    ) -> Run:
        owner = owner or self.owner_id
        now = utc_now()
        expires_at = now + timedelta(seconds=lease_seconds)
        with self._lock:
            run = self._require_locked(run_id)
            if run.lease_owner != owner:
                raise ValueError(f"Run {run_id} is leased by another owner")
            if self._repository is not None:
                claimed = self._repository.try_claim_run(
                    run_id,
                    owner=owner,
                    heartbeat_at=now,
                    lease_expires_at=expires_at,
                )
                if not claimed:
                    raise ValueError(f"Lease for run {run_id} was lost")
            run.heartbeat_at = now
            run.lease_expires_at = expires_at
            self._persist_run_locked(run)
            return run.model_copy(deep=True)

    def release(self, run_id: str, *, owner: Optional[str] = None) -> bool:
        owner = owner or self.owner_id
        with self._lock:
            run = self._require_locked(run_id)
            if run.lease_owner != owner:
                return False
            if self._repository is not None:
                try:
                    if not self._repository.release_run_lease(
                        run_id,
                        owner=owner,
                    ):
                        return False
                except Exception:
                    logger.warning("Failed to release run %s", run_id, exc_info=True)
                    return False
            run.lease_owner = None
            run.lease_expires_at = None
            self._persist_run_locked(run)
        self.emit(run_id, "run.released", {"owner": owner})
        return True

    def get(self, run_id: str) -> Optional[Run]:
        with self._lock:
            run = self._runs.get(run_id)
            if run:
                return run.model_copy(deep=True)
        if self._repository is not None:
            try:
                return self._repository.get_run(run_id)
            except Exception:
                logger.warning("Failed to load run %s", run_id, exc_info=True)
        return None

    def list(
        self,
        limit: int = 50,
        *,
        offset: int = 0,
        status: Optional[RunStatus] = None,
        run_type: Optional[RunType] = None,
        conversation_id: Optional[str] = None,
    ) -> List[Run]:
        if limit <= 0:
            return []
        if self._repository is not None:
            try:
                return self._repository.list_runs(
                    limit=limit,
                    offset=offset,
                    status=status,
                    run_type=run_type,
                    conversation_id=conversation_id,
                )
            except Exception:
                logger.warning("Failed to list persisted runs", exc_info=True)
        with self._lock:
            runs = [self._runs[run_id] for run_id in reversed(self._order)]
            if status is not None:
                runs = [run for run in runs if run.status == status]
            if run_type is not None:
                runs = [run for run in runs if run.type == run_type]
            if conversation_id is not None:
                runs = [run for run in runs if run.conversation_id == conversation_id]
            return [
                run.model_copy(deep=True) for run in runs[max(0, offset) : max(0, offset) + limit]
            ]

    def children(self, parent_run_id: str) -> List[Run]:
        """Return direct children in creation order."""
        if self._repository is not None:
            try:
                return self._repository.list_child_runs(parent_run_id)
            except Exception:
                logger.warning(
                    "Failed to load child runs for %s",
                    parent_run_id,
                    exc_info=True,
                )
        with self._lock:
            return [
                self._runs[run_id].model_copy(deep=True)
                for run_id in self._order
                if self._runs[run_id].parent_run_id == parent_run_id
            ]

    def subscribe(self, observer: RunObserver) -> Callable[[], None]:
        with self._lock:
            self._observers.append(observer)

        def unsubscribe() -> None:
            with self._lock:
                if observer in self._observers:
                    self._observers.remove(observer)

        return unsubscribe

    def _finish(
        self,
        run_id: str,
        status: RunStatus,
        *,
        result: Any = None,
        error: Optional[str] = None,
    ) -> Run:
        with self._lock:
            run = self._require_locked(run_id)
            if run.status.terminal:
                return run.model_copy(deep=True)
            run.status = status
            run.result = result
            run.error = error
            run.finished_at = utc_now()
            run.lease_owner = None
            run.lease_expires_at = None
            self._persist_run_locked(run)
        self.emit(
            run_id,
            f"run.{status.value}",
            {"error": error} if error else {},
        )
        return self.get(run_id)

    def _require_locked(self, run_id: str) -> Run:
        try:
            return self._runs[run_id]
        except KeyError as exc:
            if self._repository is not None:
                try:
                    run = self._repository.get_run(run_id)
                except Exception:
                    run = None
                if run is not None:
                    self._remember_locked(run)
                    return self._runs[run_id]
            raise KeyError(f"Unknown run: {run_id}") from exc

    def _restore(self, *, recover_interrupted: bool) -> None:
        if self._repository is None:
            return
        try:
            restored = self._repository.list_runs(limit=self._max_history)
        except Exception:
            logger.warning("Failed to restore persisted runs", exc_info=True)
            return

        with self._lock:
            for run in reversed(restored):
                self._remember_locked(run)
            if not recover_interrupted:
                return
            for run in self._runs.values():
                if run.status not in {RunStatus.PENDING, RunStatus.RUNNING}:
                    continue
                now = utc_now()
                if run.lease_expires_at and run.lease_expires_at > now:
                    continue
                previous_status = run.status.value
                recoverable = (
                    run.recovery_policy == RecoveryPolicy.RESUME and run.checkpoint is not None
                ) or run.recovery_policy == RecoveryPolicy.MANUAL
                retryable = (
                    run.recovery_policy == RecoveryPolicy.RETRY and run.attempt < run.max_attempts
                )
                if recoverable:
                    run.status = RunStatus.PAUSED
                    run.error = "应用重启前运行中断，等待恢复"
                    run.metadata["recovery_action"] = "resume" if run.checkpoint else "replay"
                else:
                    run.status = RunStatus.FAILED
                    run.error = "应用重启前运行未正常结束"
                    run.finished_at = now
                    if retryable:
                        run.metadata["recovery_action"] = "retry"
                run.lease_owner = None
                run.lease_expires_at = None
                event = RunEvent(
                    sequence=len(run.events) + 1,
                    type="run.recovered",
                    data={
                        "previous_status": previous_status,
                        "recovery_action": run.metadata.get("recovery_action"),
                    },
                )
                run.events.append(event)
                self._persist_run_locked(run)
                self._persist_event_locked(run.id, event)

    def _find_by_idempotency_key(self, idempotency_key: str) -> Optional[Run]:
        with self._lock:
            run_id = self._idempotency.get(idempotency_key)
            if run_id and run_id in self._runs:
                return self._runs[run_id].model_copy(deep=True)
        if self._repository is None:
            return None
        try:
            run = self._repository.get_run_by_idempotency_key(idempotency_key)
        except Exception:
            logger.warning("Failed to resolve idempotent run", exc_info=True)
            return None
        if run is not None:
            with self._lock:
                self._remember_locked(run)
            return run.model_copy(deep=True)
        return None

    def _remember_locked(self, run: Run) -> None:
        if run.id not in self._runs:
            self._order.append(run.id)
        self._runs[run.id] = run
        if run.idempotency_key:
            self._idempotency[run.idempotency_key] = run.id

    def _persist_run_locked(self, run: Run) -> None:
        if self._repository is None:
            return
        try:
            self._repository.save_run(run.model_copy(deep=True))
        except Exception:
            logger.warning("Failed to persist run %s", run.id, exc_info=True)

    def _persist_event_locked(self, run_id: str, event: RunEvent) -> None:
        if self._repository is None:
            return
        try:
            self._repository.append_run_event(
                run_id,
                event.model_copy(deep=True),
            )
        except Exception:
            logger.warning("Failed to persist run event for %s", run_id, exc_info=True)

    def _prune_locked(self) -> None:
        while len(self._order) > self._max_history:
            oldest = self._order[0]
            run = self._runs[oldest]
            if not run.status.terminal:
                break
            self._order.popleft()
            removed = self._runs.pop(oldest, None)
            if removed and removed.idempotency_key:
                self._idempotency.pop(removed.idempotency_key, None)
