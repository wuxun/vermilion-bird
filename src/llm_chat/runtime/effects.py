"""持久化副作用 Outbox 与崩溃后协调。"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Protocol
from uuid import uuid4

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class EffectStatus(str, Enum):
    PENDING = "pending"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    UNCERTAIN = "uncertain"


class EffectResolution(str, Enum):
    SUCCEEDED = "succeeded"
    NOT_APPLIED = "not_applied"
    RETRY_APPROVED = "retry_approved"


class EffectRecord(BaseModel):
    id: str = Field(default_factory=lambda: f"effect_{uuid4().hex}")
    effect_key: str
    run_id: Optional[str] = None
    kind: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    status: EffectStatus = EffectStatus.PENDING
    retry_safe: bool = False
    attempts: int = 0
    result: Optional[Any] = None
    error: Optional[str] = None
    resolution: Optional[EffectResolution] = None
    reconciliation_note: Optional[str] = None
    reconciled_by: Optional[str] = None
    reconciled_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)
    finished_at: Optional[datetime] = None


class EffectRepository(Protocol):
    def create_effect(self, effect: EffectRecord) -> bool:
        ...

    def save_effect(self, effect: EffectRecord) -> None:
        ...

    def get_effect(self, effect_key: str) -> Optional[EffectRecord]:
        ...

    def list_effects(
        self,
        *,
        status: Optional[EffectStatus] = None,
        limit: int = 1000,
    ) -> List[EffectRecord]:
        ...

    def resolve_effect(
        self,
        effect: EffectRecord,
        *,
        expected_status: EffectStatus,
    ) -> bool:
        ...


class UncertainEffectError(RuntimeError):
    """执行可能已到达外部系统，禁止自动重复。"""


class EffectOutbox:
    """用稳定 key 串行化副作用，并保存确定结果。"""

    def __init__(self, repository: EffectRepository):
        self.repository = repository
        self._lock = threading.RLock()

    def prepare(
        self,
        *,
        effect_key: str,
        kind: str,
        payload: Dict[str, Any],
        run_id: Optional[str] = None,
        retry_safe: bool = False,
    ) -> EffectRecord:
        if not effect_key:
            raise ValueError("effect_key cannot be empty")
        record = EffectRecord(
            effect_key=effect_key,
            run_id=run_id,
            kind=kind,
            payload=dict(payload),
            retry_safe=retry_safe,
        )
        if self.repository.create_effect(record):
            return record
        existing = self.repository.get_effect(effect_key)
        if existing is None:
            raise RuntimeError(f"Effect was not created and cannot be loaded: {effect_key}")
        return existing

    def execute(
        self,
        *,
        effect_key: str,
        executor: Callable[[], Any],
    ) -> EffectRecord:
        with self._lock:
            record = self.repository.get_effect(effect_key)
            if record is None:
                raise KeyError(f"Unknown effect: {effect_key}")
            if record.status == EffectStatus.COMPLETED:
                return record
            if record.status in {EffectStatus.EXECUTING, EffectStatus.UNCERTAIN}:
                raise UncertainEffectError(
                    f"Effect {effect_key} may already have executed; manual reconciliation required"
                )
            if record.status == EffectStatus.FAILED and not record.retry_safe:
                raise ValueError(f"Effect {effect_key} is not safe to retry")
            record.status = EffectStatus.EXECUTING
            record.attempts += 1
            record.error = None
            record.updated_at = _utc_now()
            self.repository.save_effect(record)

        try:
            result = executor()
        except Exception as exc:
            with self._lock:
                record.status = EffectStatus.FAILED
                record.error = str(exc)
                record.updated_at = _utc_now()
                record.finished_at = record.updated_at
                self.repository.save_effect(record)
            raise

        with self._lock:
            record.status = EffectStatus.COMPLETED
            record.result = result
            record.error = None
            record.updated_at = _utc_now()
            record.finished_at = record.updated_at
            self.repository.save_effect(record)
            return record.model_copy(deep=True)

    def reconcile_interrupted(self) -> List[EffectRecord]:
        """把进程退出时仍 executing 的副作用标为 uncertain，绝不自动重放。"""

        reconciled: List[EffectRecord] = []
        with self._lock:
            for record in self.repository.list_effects(
                status=EffectStatus.EXECUTING,
                limit=1000,
            ):
                record.status = EffectStatus.UNCERTAIN
                record.error = "应用在副作用执行期间退出，外部结果未知，需要人工核对"
                record.updated_at = _utc_now()
                self.repository.save_effect(record)
                reconciled.append(record.model_copy(deep=True))
        return reconciled

    def resolve_uncertain(
        self,
        *,
        effect_key: str,
        resolution: EffectResolution,
        note: str,
        result: Any = None,
        actor: str = "local-user",
    ) -> EffectRecord:
        """记录人工核对结论；不会在此方法中执行任何副作用。"""

        if not isinstance(resolution, EffectResolution):
            resolution = EffectResolution(resolution)
        note = note.strip()
        if not note:
            raise ValueError("reconciliation note cannot be empty")
        actor = actor.strip()
        if not actor:
            raise ValueError("reconciliation actor cannot be empty")

        with self._lock:
            record = self.repository.get_effect(effect_key)
            if record is None:
                raise KeyError(f"Unknown effect: {effect_key}")
            if record.status != EffectStatus.UNCERTAIN:
                raise ValueError(f"Effect {effect_key} is {record.status.value}, not uncertain")
            if resolution == EffectResolution.RETRY_APPROVED and not record.retry_safe:
                raise ValueError(f"Effect {effect_key} is not declared safe to retry")

            now = _utc_now()
            record.resolution = resolution
            record.reconciliation_note = note
            record.reconciled_by = actor
            record.reconciled_at = now
            record.updated_at = now
            record.finished_at = now

            if resolution == EffectResolution.SUCCEEDED:
                record.status = EffectStatus.COMPLETED
                record.result = result
                record.error = None
            else:
                record.status = EffectStatus.FAILED
                record.error = note

            if not self.repository.resolve_effect(
                record,
                expected_status=EffectStatus.UNCERTAIN,
            ):
                raise ValueError(
                    f"Effect {effect_key} was reconciled by another process"
                )
            return record.model_copy(deep=True)
