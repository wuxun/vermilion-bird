"""Privacy-safe local product events and funnel metrics.

Product events describe that an interaction happened. They deliberately never
store prompts, message bodies, artifact contents, file paths or credentials.
Lifecycle state continues to come from WorkItem, Run, Artifact and Workflow
repositories; this module only supplies durable product-usage evidence.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol
from uuid import uuid4

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ProductEventType(str, Enum):
    WORK_ITEM_CREATED = "work_item.created"
    WORK_ITEM_STARTED = "work_item.started"
    WORK_ITEM_TERMINAL = "work_item.terminal"
    ARTIFACT_CREATED = "artifact.created"
    ARTIFACT_VIEWED = "artifact.viewed"
    ARTIFACT_FEEDBACK = "artifact.feedback"
    ARTIFACT_EXPORTED = "artifact.exported"
    WORKFLOW_CREATED = "workflow.created"
    WORKFLOW_REVISED = "workflow.revised"
    WORKFLOW_RUN_STARTED = "workflow.run_started"
    CONTEXT_RESOURCE_ATTACHED = "context_resource.attached"
    CONTEXT_RESOURCE_REMOVED = "context_resource.removed"


class ProductEvent(BaseModel):
    id: str = Field(default_factory=lambda: f"product_event_{uuid4().hex}")
    type: ProductEventType
    subject_type: str
    subject_id: str
    work_item_id: Optional[str] = None
    conversation_id: Optional[str] = None
    properties: Dict[str, Any] = Field(default_factory=dict)
    deduplication_key: Optional[str] = None
    occurred_at: datetime = Field(default_factory=utc_now)


class ProductEventRepository(Protocol):
    def append_product_event(self, event: ProductEvent) -> bool:
        ...

    def list_product_events(
        self,
        *,
        event_type: Optional[ProductEventType] = None,
        work_item_id: Optional[str] = None,
        subject_id: Optional[str] = None,
        limit: int = 500,
    ) -> List[ProductEvent]:
        ...

    def get_product_event_by_deduplication_key(
        self,
        deduplication_key: str,
    ) -> Optional[ProductEvent]:
        ...

    def count_product_events(
        self,
        *,
        event_type: Optional[ProductEventType] = None,
    ) -> int:
        ...


class ProductEventService:
    """Append-only local analytics with an explicit non-content schema."""

    # Call sites may only attach categorical or numeric attributes. Keys that
    # could contain user content are intentionally absent.
    SAFE_PROPERTY_KEYS = {
        "artifact_kind",
        "artifact_relation",
        "artifact_version",
        "decision",
        "entrypoint",
        "export_kind",
        "kind",
        "review_policy",
        "resource_kind",
        "run_type",
        "source",
        "status",
        "transfer_policy",
        "workflow_version",
    }

    def __init__(self, repository: ProductEventRepository):
        self.repository = repository

    def record(
        self,
        event_type: ProductEventType,
        *,
        subject_type: str,
        subject_id: str,
        work_item_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        properties: Optional[Dict[str, Any]] = None,
        deduplication_key: Optional[str] = None,
    ) -> ProductEvent:
        if not isinstance(event_type, ProductEventType):
            event_type = ProductEventType(event_type)
        event = ProductEvent(
            type=event_type,
            subject_type=self._identifier(subject_type, "subject type"),
            subject_id=self._identifier(subject_id, "subject id"),
            work_item_id=work_item_id,
            conversation_id=conversation_id,
            properties=self._sanitize_properties(properties or {}),
            deduplication_key=deduplication_key,
        )
        created = self.repository.append_product_event(event)
        if not created and deduplication_key:
            existing = self.repository.get_product_event_by_deduplication_key(
                deduplication_key
            )
            if existing is not None:
                return existing
        return event.model_copy(deep=True)

    def safe_record(self, *args, **kwargs) -> Optional[ProductEvent]:
        """Record without allowing analytics failure to break user work."""

        try:
            return self.record(*args, **kwargs)
        except Exception:
            logger.warning("Local product event recording failed", exc_info=True)
            return None

    def list(
        self,
        *,
        event_type: Optional[ProductEventType] = None,
        work_item_id: Optional[str] = None,
        subject_id: Optional[str] = None,
        limit: int = 500,
    ) -> List[ProductEvent]:
        return self.repository.list_product_events(
            event_type=event_type,
            work_item_id=work_item_id,
            subject_id=subject_id,
            limit=limit,
        )

    def local_summary(self) -> Dict[str, int]:
        """Return local event counts; no network or user content is involved."""

        return {
            event_type.value: self.repository.count_product_events(event_type=event_type)
            for event_type in ProductEventType
        }

    @classmethod
    def _sanitize_properties(cls, properties: Dict[str, Any]) -> Dict[str, Any]:
        unknown = sorted(set(properties) - cls.SAFE_PROPERTY_KEYS)
        if unknown:
            raise ValueError("unsafe product event properties: " + ", ".join(unknown))
        sanitized: Dict[str, Any] = {}
        for key, value in properties.items():
            if value is None or isinstance(value, (str, int, float, bool)):
                sanitized[key] = value
                continue
            if isinstance(value, Enum):
                sanitized[key] = value.value
                continue
            raise TypeError(f"product event property {key} must be a scalar")
        return sanitized

    @staticmethod
    def _identifier(value: str, label: str) -> str:
        value = (value or "").strip()
        if not value:
            raise ValueError(f"product event {label} cannot be empty")
        return value
