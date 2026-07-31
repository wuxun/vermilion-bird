"""SQLite repository for privacy-safe local product events."""

import json
from datetime import datetime, timezone
from typing import List, Optional

from llm_chat.product_events import ProductEvent, ProductEventType


class StorageProductEventMixin:
    def append_product_event(self, event: ProductEvent) -> bool:
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO product_events(
                    id, event_type, subject_type, subject_id,
                    work_item_id, conversation_id, properties_json,
                    deduplication_key, occurred_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.id,
                    event.type.value,
                    event.subject_type,
                    event.subject_id,
                    event.work_item_id,
                    event.conversation_id,
                    json.dumps(event.properties, ensure_ascii=False, sort_keys=True),
                    event.deduplication_key,
                    event.occurred_at.isoformat(),
                ),
            )
        return cursor.rowcount == 1

    def list_product_events(
        self,
        *,
        event_type: Optional[ProductEventType] = None,
        work_item_id: Optional[str] = None,
        subject_id: Optional[str] = None,
        limit: int = 500,
    ) -> List[ProductEvent]:
        conditions = []
        values = []
        if event_type is not None:
            if not isinstance(event_type, ProductEventType):
                event_type = ProductEventType(event_type)
            conditions.append("event_type = ?")
            values.append(event_type.value)
        if work_item_id is not None:
            conditions.append("work_item_id = ?")
            values.append(work_item_id)
        if subject_id is not None:
            conditions.append("subject_id = ?")
            values.append(subject_id)
        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        values.append(max(1, limit))
        with self._get_connection() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM product_events
                {where}
                ORDER BY occurred_at DESC, id DESC
                LIMIT ?
                """,
                tuple(values),
            ).fetchall()
        return [self._row_to_product_event(row) for row in rows]

    def get_product_event_by_deduplication_key(
        self,
        deduplication_key: str,
    ) -> Optional[ProductEvent]:
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM product_events
                WHERE deduplication_key = ?
                LIMIT 1
                """,
                (deduplication_key,),
            ).fetchone()
        return self._row_to_product_event(row) if row else None

    def count_product_events(
        self,
        *,
        event_type: Optional[ProductEventType] = None,
    ) -> int:
        if event_type is None:
            query = "SELECT COUNT(*) FROM product_events"
            values = ()
        else:
            if not isinstance(event_type, ProductEventType):
                event_type = ProductEventType(event_type)
            query = "SELECT COUNT(*) FROM product_events WHERE event_type = ?"
            values = (event_type.value,)
        with self._get_connection() as conn:
            return int(conn.execute(query, values).fetchone()[0])

    @staticmethod
    def _row_to_product_event(row) -> ProductEvent:
        try:
            properties = json.loads(row["properties_json"] or "{}")
        except (TypeError, ValueError):
            properties = {}
        occurred_at = (
            datetime.fromisoformat(row["occurred_at"])
            if row["occurred_at"]
            else datetime.now(timezone.utc)
        )
        return ProductEvent(
            id=row["id"],
            type=ProductEventType(row["event_type"]),
            subject_type=row["subject_type"],
            subject_id=row["subject_id"],
            work_item_id=row["work_item_id"],
            conversation_id=row["conversation_id"],
            properties=properties,
            deduplication_key=row["deduplication_key"],
            occurred_at=occurred_at,
        )
