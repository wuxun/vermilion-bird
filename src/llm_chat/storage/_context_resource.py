"""SQLite repository for attached context resources."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from llm_chat.context.resources import ContextResource


def _datetime(value):
    return datetime.fromisoformat(value) if value else None


class StorageContextResourceMixin:
    def create_context_resource(self, resource: ContextResource) -> bool:
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO context_resources(
                    id, conversation_id, work_item_id, kind, display_name,
                    source_path, snapshot_hash, size_bytes, modified_at,
                    sensitivity, transfer_policy, status,
                    created_at, updated_at, removed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    resource.id,
                    resource.conversation_id,
                    resource.work_item_id,
                    resource.kind.value,
                    resource.display_name,
                    resource.source_path,
                    resource.snapshot_hash,
                    resource.size_bytes,
                    resource.modified_at.isoformat() if resource.modified_at else None,
                    resource.sensitivity.value,
                    resource.transfer_policy.value,
                    resource.status.value,
                    resource.created_at.isoformat(),
                    resource.updated_at.isoformat(),
                    resource.removed_at.isoformat() if resource.removed_at else None,
                ),
            )
        return cursor.rowcount == 1

    def get_context_resource(self, resource_id: str) -> Optional[ContextResource]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM context_resources WHERE id = ?",
                (resource_id,),
            ).fetchone()
        return self._row_to_context_resource(row) if row else None

    def get_active_context_resource_by_path(
        self,
        conversation_id: str,
        source_path: str,
    ) -> Optional[ContextResource]:
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM context_resources
                WHERE conversation_id = ? AND source_path = ? AND status = 'active'
                LIMIT 1
                """,
                (conversation_id, source_path),
            ).fetchone()
        return self._row_to_context_resource(row) if row else None

    def list_context_resources(
        self,
        *,
        conversation_id: Optional[str] = None,
        work_item_id: Optional[str] = None,
        active_only: bool = True,
        limit: int = 100,
    ) -> List[ContextResource]:
        conditions = []
        values = []
        if conversation_id is not None:
            conditions.append("conversation_id = ?")
            values.append(conversation_id)
        if work_item_id is not None:
            conditions.append("work_item_id = ?")
            values.append(work_item_id)
        if active_only:
            conditions.append("status = 'active'")
        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        values.append(max(1, limit))
        with self._get_connection() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM context_resources
                {where}
                ORDER BY created_at, id
                LIMIT ?
                """,
                tuple(values),
            ).fetchall()
        return [self._row_to_context_resource(row) for row in rows]

    def remove_context_resource(self, resource_id: str, *, removed_at: datetime) -> bool:
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE context_resources
                SET status = 'removed', updated_at = ?, removed_at = ?
                WHERE id = ? AND status = 'active'
                """,
                (removed_at.isoformat(), removed_at.isoformat(), resource_id),
            )
        return cursor.rowcount == 1

    def bind_context_resources_to_work_item(
        self,
        conversation_id: str,
        work_item_id: str,
    ) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE context_resources
                SET work_item_id = ?, updated_at = ?
                WHERE conversation_id = ?
                  AND status = 'active'
                  AND (work_item_id IS NULL OR work_item_id = ?)
                """,
                (work_item_id, now, conversation_id, work_item_id),
            )
        return cursor.rowcount

    @staticmethod
    def _row_to_context_resource(row) -> ContextResource:
        from llm_chat.context.resources import (
            ContextResource,
            ContextResourceKind,
            ContextResourceStatus,
            ContextResourceSensitivity,
            ExternalTransferPolicy,
        )

        return ContextResource(
            id=row["id"],
            conversation_id=row["conversation_id"],
            work_item_id=row["work_item_id"],
            kind=ContextResourceKind(row["kind"]),
            display_name=row["display_name"],
            source_path=row["source_path"],
            snapshot_hash=row["snapshot_hash"],
            size_bytes=row["size_bytes"],
            modified_at=_datetime(row["modified_at"]),
            sensitivity=ContextResourceSensitivity(row["sensitivity"]),
            transfer_policy=ExternalTransferPolicy(row["transfer_policy"]),
            status=ContextResourceStatus(row["status"]),
            created_at=_datetime(row["created_at"]) or datetime.now(timezone.utc),
            updated_at=_datetime(row["updated_at"]) or datetime.now(timezone.utc),
            removed_at=_datetime(row["removed_at"]),
        )
