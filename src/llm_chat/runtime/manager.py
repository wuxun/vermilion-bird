"""Thread-safe, instance-scoped Run lifecycle manager."""

from __future__ import annotations

import logging
import threading
from collections import deque
from typing import Any, Callable, Dict, List, Optional, Protocol

from .models import Run, RunEvent, RunStatus, RunType, utc_now

logger = logging.getLogger(__name__)
RunObserver = Callable[[Run, RunEvent], None]


class RunRepository(Protocol):
    """RunManager 所需的最小持久化端口。"""

    def save_run(self, run: Run) -> None:
        ...

    def append_run_event(self, run_id: str, event: RunEvent) -> None:
        ...

    def get_run(self, run_id: str) -> Optional[Run]:
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


class RunManager:
    """管理 Run 生命周期，并可选地将其同步到持久化仓储。"""

    def __init__(
        self,
        max_history: int = 1000,
        *,
        repository: Optional[RunRepository] = None,
        recover_interrupted: bool = True,
    ):
        self._max_history = max_history
        self._repository = repository
        self._runs: Dict[str, Run] = {}
        self._order: deque[str] = deque()
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
    ) -> Run:
        run = Run(
            type=run_type,
            parent_run_id=parent_run_id,
            conversation_id=conversation_id,
            input=input or {},
            metadata=metadata or {},
            status=RunStatus.RUNNING,
            started_at=utc_now(),
        )
        with self._lock:
            self._runs[run.id] = run
            self._order.append(run.id)
            self._prune_locked()
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
                self._runs[run.id] = run
                self._order.append(run.id)
            if not recover_interrupted:
                return
            for run in self._runs.values():
                if run.status not in {RunStatus.PENDING, RunStatus.RUNNING}:
                    continue
                run.status = RunStatus.FAILED
                run.error = "应用重启前运行未正常结束"
                run.finished_at = utc_now()
                event = RunEvent(
                    sequence=len(run.events) + 1,
                    type="run.recovered",
                    data={"previous_status": "interrupted"},
                )
                run.events.append(event)
                self._persist_run_locked(run)
                self._persist_event_locked(run.id, event)

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
            self._runs.pop(oldest, None)
