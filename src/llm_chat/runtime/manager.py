"""Thread-safe, instance-scoped Run lifecycle manager."""

from __future__ import annotations

import logging
import threading
from collections import deque
from typing import Any, Callable, Dict, List, Optional

from .models import Run, RunEvent, RunStatus, RunType, utc_now

logger = logging.getLogger(__name__)
RunObserver = Callable[[Run, RunEvent], None]


class RunManager:
    """Own Run state and ordered events without process-global mutable state."""

    def __init__(self, max_history: int = 1000):
        self._max_history = max_history
        self._runs: Dict[str, Run] = {}
        self._order: deque[str] = deque()
        self._observers: List[RunObserver] = []
        self._lock = threading.RLock()

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
            return run.model_copy(deep=True) if run else None

    def list(self, limit: int = 50) -> List[Run]:
        with self._lock:
            ids = list(self._order)[-max(0, limit) :]
            return [self._runs[run_id].model_copy(deep=True) for run_id in reversed(ids)]

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

    def _prune_locked(self) -> None:
        while len(self._order) > self._max_history:
            oldest = self._order[0]
            run = self._runs[oldest]
            if not run.status.terminal:
                break
            self._order.popleft()
            self._runs.pop(oldest, None)
