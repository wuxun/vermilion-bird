"""用户任务与交付物的 SQLite 持久化。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, List, Optional

from llm_chat.work.models import (
    Artifact,
    ArtifactKind,
    WorkItem,
    WorkItemKind,
    WorkItemStatus,
)


def _dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _load_json(value: Optional[str], default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


class StorageWorkMixin:
    """为 Storage 提供 WorkItem 与 Artifact Repository 能力。"""

    def create_work_item(self, work_item: WorkItem) -> bool:
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO work_items (
                    id, title, objective, kind, status, conversation_id,
                    workflow_id, workspace, root_run_id, latest_run_id,
                    idempotency_key, metadata_json, created_at, updated_at,
                    completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._work_item_values(work_item),
            )
            return cursor.rowcount == 1

    def save_work_item(self, work_item: WorkItem) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO work_items (
                    id, title, objective, kind, status, conversation_id,
                    workflow_id, workspace, root_run_id, latest_run_id,
                    idempotency_key, metadata_json, created_at, updated_at,
                    completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title = excluded.title,
                    objective = excluded.objective,
                    kind = excluded.kind,
                    status = excluded.status,
                    conversation_id = excluded.conversation_id,
                    workflow_id = excluded.workflow_id,
                    workspace = excluded.workspace,
                    root_run_id = excluded.root_run_id,
                    latest_run_id = excluded.latest_run_id,
                    idempotency_key = excluded.idempotency_key,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at,
                    completed_at = excluded.completed_at
                """,
                self._work_item_values(work_item),
            )

    def get_work_item(self, work_item_id: str) -> Optional[WorkItem]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM work_items WHERE id = ?",
                (work_item_id,),
            ).fetchone()
        return self._row_to_work_item(row) if row else None

    def get_work_item_by_idempotency_key(self, idempotency_key: str) -> Optional[WorkItem]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM work_items WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        return self._row_to_work_item(row) if row else None

    def list_work_items(
        self,
        limit: int = 50,
        *,
        offset: int = 0,
        status: Optional[WorkItemStatus] = None,
        kind: Optional[WorkItemKind] = None,
        conversation_id: Optional[str] = None,
    ) -> List[WorkItem]:
        clauses: List[str] = []
        params: List[Any] = []
        if status is not None:
            clauses.append("status = ?")
            params.append(status.value if isinstance(status, WorkItemStatus) else str(status))
        if kind is not None:
            clauses.append("kind = ?")
            params.append(kind.value if isinstance(kind, WorkItemKind) else str(kind))
        if conversation_id is not None:
            clauses.append("conversation_id = ?")
            params.append(conversation_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend((max(1, limit), max(0, offset)))
        with self._get_connection() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM work_items
                {where}
                ORDER BY updated_at DESC
                LIMIT ? OFFSET ?
                """,
                params,
            ).fetchall()
        return [self._row_to_work_item(row) for row in rows]

    def save_artifact(self, artifact: Artifact) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO artifacts (
                    id, work_item_id, run_id, kind, name, uri, content,
                    content_preview, checksum, idempotency_key, metadata_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    work_item_id = excluded.work_item_id,
                    run_id = excluded.run_id,
                    kind = excluded.kind,
                    name = excluded.name,
                    uri = excluded.uri,
                    content = excluded.content,
                    content_preview = excluded.content_preview,
                    checksum = excluded.checksum,
                    idempotency_key = excluded.idempotency_key,
                    metadata_json = excluded.metadata_json
                """,
                self._artifact_values(artifact),
            )

    def create_artifact(self, artifact: Artifact) -> bool:
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO artifacts (
                    id, work_item_id, run_id, kind, name, uri, content,
                    content_preview, checksum, idempotency_key, metadata_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._artifact_values(artifact),
            )
            return cursor.rowcount == 1

    def get_artifact(self, artifact_id: str) -> Optional[Artifact]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM artifacts WHERE id = ?",
                (artifact_id,),
            ).fetchone()
        return self._row_to_artifact(row) if row else None

    def get_artifact_by_idempotency_key(self, idempotency_key: str) -> Optional[Artifact]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM artifacts WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        return self._row_to_artifact(row) if row else None

    def list_artifacts(
        self,
        work_item_id: str,
        *,
        limit: int = 200,
    ) -> List[Artifact]:
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM artifacts
                WHERE work_item_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (work_item_id, max(1, limit)),
            ).fetchall()
        return [self._row_to_artifact(row) for row in rows]

    @staticmethod
    def _work_item_values(work_item: WorkItem) -> tuple:
        return (
            work_item.id,
            work_item.title,
            work_item.objective,
            work_item.kind.value,
            work_item.status.value,
            work_item.conversation_id,
            work_item.workflow_id,
            work_item.workspace,
            work_item.root_run_id,
            work_item.latest_run_id,
            work_item.idempotency_key,
            _dump_json(work_item.metadata),
            work_item.created_at.isoformat(),
            work_item.updated_at.isoformat(),
            work_item.completed_at.isoformat() if work_item.completed_at else None,
        )

    @staticmethod
    def _artifact_values(artifact: Artifact) -> tuple:
        return (
            artifact.id,
            artifact.work_item_id,
            artifact.run_id,
            artifact.kind.value,
            artifact.name,
            artifact.uri,
            artifact.content,
            artifact.content_preview,
            artifact.checksum,
            artifact.idempotency_key,
            _dump_json(artifact.metadata),
            artifact.created_at.isoformat(),
        )

    @staticmethod
    def _row_to_work_item(row: Any) -> WorkItem:
        now = datetime.now(timezone.utc)
        return WorkItem(
            id=row["id"],
            title=row["title"],
            objective=row["objective"],
            kind=WorkItemKind(row["kind"]),
            status=WorkItemStatus(row["status"]),
            conversation_id=row["conversation_id"],
            workflow_id=row["workflow_id"],
            workspace=row["workspace"],
            root_run_id=row["root_run_id"],
            latest_run_id=row["latest_run_id"],
            idempotency_key=row["idempotency_key"],
            metadata=_load_json(row["metadata_json"], {}),
            created_at=_parse_datetime(row["created_at"]) or now,
            updated_at=_parse_datetime(row["updated_at"]) or now,
            completed_at=_parse_datetime(row["completed_at"]),
        )

    @staticmethod
    def _row_to_artifact(row: Any) -> Artifact:
        return Artifact(
            id=row["id"],
            work_item_id=row["work_item_id"],
            run_id=row["run_id"],
            kind=ArtifactKind(row["kind"]),
            name=row["name"],
            uri=row["uri"],
            content=row["content"],
            content_preview=row["content_preview"],
            checksum=row["checksum"],
            idempotency_key=row["idempotency_key"],
            metadata=_load_json(row["metadata_json"], {}),
            created_at=_parse_datetime(row["created_at"]) or datetime.now(timezone.utc),
        )
