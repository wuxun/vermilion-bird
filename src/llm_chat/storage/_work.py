"""用户任务与交付物的 SQLite 持久化。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, List, Optional

from llm_chat.work.models import (
    Artifact,
    ArtifactFeedback,
    ArtifactFeedbackDecision,
    ArtifactKind,
    ArtifactReviewPolicy,
    GrantScope,
    GrantStatus,
    PlanRevision,
    PlanStatus,
    PlanStep,
    PlanStepStatus,
    ResourceGrant,
    ResourceType,
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
                    workflow_id, series_key, artifact_review_policy, workspace,
                    root_run_id, latest_run_id, idempotency_key, metadata_json,
                    created_at, updated_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    workflow_id, series_key, artifact_review_policy, workspace,
                    root_run_id, latest_run_id, idempotency_key, metadata_json,
                    created_at, updated_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title = excluded.title,
                    objective = excluded.objective,
                    kind = excluded.kind,
                    status = excluded.status,
                    conversation_id = excluded.conversation_id,
                    workflow_id = excluded.workflow_id,
                    series_key = excluded.series_key,
                    artifact_review_policy = excluded.artifact_review_policy,
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

    def get_work_item_by_series_key(self, series_key: str) -> Optional[WorkItem]:
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM work_items
                WHERE series_key = ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (series_key,),
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

    def create_artifact_feedback(self, feedback: ArtifactFeedback) -> bool:
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO artifact_feedback (
                    id, artifact_id, work_item_id, decision, note,
                    created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    feedback.id,
                    feedback.artifact_id,
                    feedback.work_item_id,
                    feedback.decision.value,
                    feedback.note,
                    feedback.created_by,
                    feedback.created_at.isoformat(),
                ),
            )
            return cursor.rowcount == 1

    def list_artifact_feedback(
        self,
        work_item_id: str,
        *,
        artifact_id: Optional[str] = None,
        limit: int = 500,
    ) -> List[ArtifactFeedback]:
        clause = "AND artifact_id = ?" if artifact_id else ""
        params = (
            (work_item_id, artifact_id, max(1, limit))
            if artifact_id
            else (work_item_id, max(1, limit))
        )
        with self._get_connection() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM artifact_feedback
                WHERE work_item_id = ? {clause}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._row_to_artifact_feedback(row) for row in rows]

    def create_plan_revision(self, plan: PlanRevision) -> bool:
        """原子保存计划头和步骤；版本冲突时不产生部分数据。"""

        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO plan_revisions (
                    id, work_item_id, version, summary, status,
                    change_summary, created_by, created_at, approved_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan.id,
                    plan.work_item_id,
                    plan.version,
                    plan.summary,
                    plan.status.value,
                    plan.change_summary,
                    plan.created_by,
                    plan.created_at.isoformat(),
                    plan.approved_at.isoformat() if plan.approved_at else None,
                ),
            )
            if cursor.rowcount != 1:
                return False
            for step in plan.steps:
                conn.execute(
                    """
                    INSERT INTO plan_steps (
                        id, plan_revision_id, position, title, description,
                        status, depends_on_json, expected_artifact_kind,
                        required_capabilities_json, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    self._plan_step_values(step),
                )
            return True

    def get_plan_revision(self, plan_id: str) -> Optional[PlanRevision]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM plan_revisions WHERE id = ?",
                (plan_id,),
            ).fetchone()
            if row is None:
                return None
            steps = conn.execute(
                """
                SELECT * FROM plan_steps
                WHERE plan_revision_id = ?
                ORDER BY position
                """,
                (plan_id,),
            ).fetchall()
        return self._row_to_plan(row, steps)

    def get_latest_plan_revision(
        self,
        work_item_id: str,
        *,
        approved_only: bool = False,
    ) -> Optional[PlanRevision]:
        where = "AND status = ?" if approved_only else ""
        params = (work_item_id, PlanStatus.APPROVED.value) if approved_only else (work_item_id,)
        with self._get_connection() as conn:
            row = conn.execute(
                f"""
                SELECT * FROM plan_revisions
                WHERE work_item_id = ? {where}
                ORDER BY version DESC
                LIMIT 1
                """,
                params,
            ).fetchone()
        return self.get_plan_revision(row["id"]) if row else None

    def list_plan_revisions(
        self,
        work_item_id: str,
        *,
        limit: int = 50,
    ) -> List[PlanRevision]:
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT id FROM plan_revisions
                WHERE work_item_id = ?
                ORDER BY version DESC
                LIMIT ?
                """,
                (work_item_id, max(1, limit)),
            ).fetchall()
        return [plan for row in rows if (plan := self.get_plan_revision(row["id"])) is not None]

    def approve_plan_revision(self, plan_id: str, *, approved_at) -> bool:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT work_item_id FROM plan_revisions WHERE id = ?",
                (plan_id,),
            ).fetchone()
            if row is None:
                return False
            conn.execute(
                """
                UPDATE plan_revisions
                SET status = ?
                WHERE work_item_id = ? AND id != ? AND status = ?
                """,
                (
                    PlanStatus.SUPERSEDED.value,
                    row["work_item_id"],
                    plan_id,
                    PlanStatus.APPROVED.value,
                ),
            )
            cursor = conn.execute(
                """
                UPDATE plan_revisions
                SET status = ?, approved_at = ?
                WHERE id = ? AND status = ?
                """,
                (
                    PlanStatus.APPROVED.value,
                    approved_at.isoformat(),
                    plan_id,
                    PlanStatus.DRAFT.value,
                ),
            )
            return cursor.rowcount == 1

    def update_plan_step_status(
        self,
        plan_id: str,
        step_id: str,
        status: PlanStepStatus,
    ) -> bool:
        value = status.value if isinstance(status, PlanStepStatus) else str(status)
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE plan_steps
                SET status = ?
                WHERE id = ? AND plan_revision_id = ?
                """,
                (value, step_id, plan_id),
            )
            return cursor.rowcount == 1

    def create_resource_grant(self, grant: ResourceGrant) -> bool:
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO resource_grants (
                    id, work_item_id, workflow_id, capability, resource_type,
                    resource, scope, status, created_by, reason, created_at,
                    expires_at, revoked_at, last_used_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._resource_grant_values(grant),
            )
            return cursor.rowcount == 1

    def save_resource_grant(self, grant: ResourceGrant) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO resource_grants (
                    id, work_item_id, workflow_id, capability, resource_type,
                    resource, scope, status, created_by, reason, created_at,
                    expires_at, revoked_at, last_used_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status = excluded.status,
                    expires_at = excluded.expires_at,
                    revoked_at = excluded.revoked_at,
                    last_used_at = excluded.last_used_at
                """,
                self._resource_grant_values(grant),
            )

    def get_resource_grant(self, grant_id: str) -> Optional[ResourceGrant]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM resource_grants WHERE id = ?",
                (grant_id,),
            ).fetchone()
        return self._row_to_resource_grant(row) if row else None

    def list_resource_grants(
        self,
        *,
        work_item_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        status: Optional[GrantStatus] = None,
        limit: int = 200,
    ) -> List[ResourceGrant]:
        clauses = []
        params = []
        if work_item_id is not None and workflow_id is not None:
            clauses.append("(work_item_id = ? OR workflow_id = ?)")
            params.extend((work_item_id, workflow_id))
        elif work_item_id is not None:
            clauses.append("work_item_id = ?")
            params.append(work_item_id)
        elif workflow_id is not None:
            clauses.append("workflow_id = ?")
            params.append(workflow_id)
        if status is not None:
            clauses.append("status = ?")
            params.append(status.value if isinstance(status, GrantStatus) else str(status))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, limit))
        with self._get_connection() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM resource_grants
                {where}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._row_to_resource_grant(row) for row in rows]

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
            work_item.series_key,
            work_item.artifact_review_policy.value,
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
    def _plan_step_values(step: PlanStep) -> tuple:
        return (
            step.id,
            step.plan_revision_id,
            step.position,
            step.title,
            step.description,
            step.status.value,
            _dump_json(step.depends_on),
            (step.expected_artifact_kind.value if step.expected_artifact_kind else None),
            _dump_json(step.required_capabilities),
            _dump_json(step.metadata),
        )

    @staticmethod
    def _resource_grant_values(grant: ResourceGrant) -> tuple:
        return (
            grant.id,
            grant.work_item_id,
            grant.workflow_id,
            grant.capability,
            grant.resource_type.value,
            grant.resource,
            grant.scope.value,
            grant.status.value,
            grant.created_by,
            grant.reason,
            grant.created_at.isoformat(),
            grant.expires_at.isoformat() if grant.expires_at else None,
            grant.revoked_at.isoformat() if grant.revoked_at else None,
            grant.last_used_at.isoformat() if grant.last_used_at else None,
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
            series_key=row["series_key"],
            artifact_review_policy=ArtifactReviewPolicy(
                row["artifact_review_policy"] or ArtifactReviewPolicy.REQUIRED.value
            ),
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

    @staticmethod
    def _row_to_artifact_feedback(row: Any) -> ArtifactFeedback:
        return ArtifactFeedback(
            id=row["id"],
            artifact_id=row["artifact_id"],
            work_item_id=row["work_item_id"],
            decision=ArtifactFeedbackDecision(row["decision"]),
            note=row["note"],
            created_by=row["created_by"],
            created_at=_parse_datetime(row["created_at"]) or datetime.now(timezone.utc),
        )

    @staticmethod
    def _row_to_plan(row: Any, step_rows: List[Any]) -> PlanRevision:
        return PlanRevision(
            id=row["id"],
            work_item_id=row["work_item_id"],
            version=row["version"],
            summary=row["summary"],
            status=PlanStatus(row["status"]),
            change_summary=row["change_summary"],
            created_by=row["created_by"],
            created_at=_parse_datetime(row["created_at"]) or datetime.now(timezone.utc),
            approved_at=_parse_datetime(row["approved_at"]),
            steps=[
                PlanStep(
                    id=step["id"],
                    plan_revision_id=step["plan_revision_id"],
                    position=step["position"],
                    title=step["title"],
                    description=step["description"],
                    status=PlanStepStatus(step["status"]),
                    depends_on=_load_json(step["depends_on_json"], []),
                    expected_artifact_kind=(
                        ArtifactKind(step["expected_artifact_kind"])
                        if step["expected_artifact_kind"]
                        else None
                    ),
                    required_capabilities=_load_json(
                        step["required_capabilities_json"],
                        [],
                    ),
                    metadata=_load_json(step["metadata_json"], {}),
                )
                for step in step_rows
            ],
        )

    @staticmethod
    def _row_to_resource_grant(row: Any) -> ResourceGrant:
        return ResourceGrant(
            id=row["id"],
            work_item_id=row["work_item_id"],
            workflow_id=row["workflow_id"],
            capability=row["capability"],
            resource_type=ResourceType(row["resource_type"]),
            resource=row["resource"],
            scope=GrantScope(row["scope"]),
            status=GrantStatus(row["status"]),
            created_by=row["created_by"],
            reason=row["reason"],
            created_at=_parse_datetime(row["created_at"]) or datetime.now(timezone.utc),
            expires_at=_parse_datetime(row["expires_at"]),
            revoked_at=_parse_datetime(row["revoked_at"]),
            last_used_at=_parse_datetime(row["last_used_at"]),
        )
