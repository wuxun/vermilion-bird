"""WorkflowDefinition SQLite repository。"""

import json
from datetime import datetime, timezone
from typing import List, Optional

from llm_chat.work import ArtifactKind
from llm_chat.workflows import (
    WorkflowDefinition,
    WorkflowParameter,
    WorkflowStatus,
    WorkflowVersion,
)


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _load(value, default):
    try:
        return json.loads(value) if value else default
    except (TypeError, ValueError):
        return default


def _datetime(value):
    return datetime.fromisoformat(value) if value else datetime.now(timezone.utc)


class StorageWorkflowMixin:
    def create_workflow(
        self,
        definition: WorkflowDefinition,
        version: WorkflowVersion,
    ) -> bool:
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO workflow_definitions (
                    id, name, description, status, latest_version,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    definition.id,
                    definition.name,
                    definition.description,
                    definition.status.value,
                    definition.latest_version,
                    definition.created_at.isoformat(),
                    definition.updated_at.isoformat(),
                ),
            )
            if cursor.rowcount != 1:
                return False
            conn.execute(
                """
                INSERT INTO workflow_versions (
                    id, workflow_id, version, objective_template,
                    parameters_json, plan_steps_json,
                    expected_artifact_kinds_json, required_resources_json,
                    budget_json, approval_policy_json, failure_policy_json,
                    source_work_item_id, change_summary, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._workflow_version_values(version),
            )
            return True

    def get_workflow(self, workflow_id: str) -> Optional[WorkflowDefinition]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM workflow_definitions WHERE id = ?",
                (workflow_id,),
            ).fetchone()
        return self._row_to_workflow(row) if row else None

    def list_workflows(self, limit: int = 100) -> List[WorkflowDefinition]:
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM workflow_definitions
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (max(1, limit),),
            ).fetchall()
        return [self._row_to_workflow(row) for row in rows]

    def get_workflow_version(
        self,
        workflow_id: str,
        version: Optional[int] = None,
    ) -> Optional[WorkflowVersion]:
        clause = "AND version = ?" if version is not None else ""
        params = (workflow_id, version) if version is not None else (workflow_id,)
        with self._get_connection() as conn:
            row = conn.execute(
                f"""
                SELECT * FROM workflow_versions
                WHERE workflow_id = ? {clause}
                ORDER BY version DESC
                LIMIT 1
                """,
                params,
            ).fetchone()
        return self._row_to_workflow_version(row) if row else None

    def list_workflow_versions(
        self,
        workflow_id: str,
        *,
        limit: int = 100,
    ) -> List[WorkflowVersion]:
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM workflow_versions
                WHERE workflow_id = ?
                ORDER BY version DESC
                LIMIT ?
                """,
                (workflow_id, max(1, limit)),
            ).fetchall()
        return [self._row_to_workflow_version(row) for row in rows]

    def create_workflow_version(
        self,
        version: WorkflowVersion,
        *,
        expected_latest_version: int,
    ) -> bool:
        with self._get_connection() as conn:
            current = conn.execute(
                """
                SELECT latest_version FROM workflow_definitions
                WHERE id = ?
                """,
                (version.workflow_id,),
            ).fetchone()
            if (
                current is None
                or current["latest_version"] != expected_latest_version
                or version.version != expected_latest_version + 1
            ):
                return False
            cursor = conn.execute(
                """
                UPDATE workflow_definitions
                SET latest_version = ?, updated_at = ?
                WHERE id = ? AND latest_version = ?
                """,
                (
                    version.version,
                    version.created_at.isoformat(),
                    version.workflow_id,
                    expected_latest_version,
                ),
            )
            if cursor.rowcount != 1:
                return False
            conn.execute(
                """
                INSERT INTO workflow_versions (
                    id, workflow_id, version, objective_template,
                    parameters_json, plan_steps_json,
                    expected_artifact_kinds_json, required_resources_json,
                    budget_json, approval_policy_json, failure_policy_json,
                    source_work_item_id, change_summary, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._workflow_version_values(version),
            )
            return True

    @staticmethod
    def _workflow_version_values(version: WorkflowVersion):
        return (
            version.id,
            version.workflow_id,
            version.version,
            version.objective_template,
            _json([item.model_dump(mode="json") for item in version.parameters]),
            _json(version.plan_steps),
            _json([item.value for item in version.expected_artifact_kinds]),
            _json(version.required_resources),
            _json(version.budget),
            _json(version.approval_policy),
            _json(version.failure_policy),
            version.source_work_item_id,
            version.change_summary,
            version.created_at.isoformat(),
        )

    @staticmethod
    def _row_to_workflow(row) -> WorkflowDefinition:
        return WorkflowDefinition(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            status=WorkflowStatus(row["status"]),
            latest_version=row["latest_version"],
            created_at=_datetime(row["created_at"]),
            updated_at=_datetime(row["updated_at"]),
        )

    @staticmethod
    def _row_to_workflow_version(row) -> WorkflowVersion:
        return WorkflowVersion(
            id=row["id"],
            workflow_id=row["workflow_id"],
            version=row["version"],
            objective_template=row["objective_template"],
            parameters=[
                WorkflowParameter.model_validate(item) for item in _load(row["parameters_json"], [])
            ],
            plan_steps=_load(row["plan_steps_json"], []),
            expected_artifact_kinds=[
                ArtifactKind(item) for item in _load(row["expected_artifact_kinds_json"], [])
            ],
            required_resources=_load(row["required_resources_json"], []),
            budget=_load(row["budget_json"], {}),
            approval_policy=_load(row["approval_policy_json"], {}),
            failure_policy=_load(row["failure_policy_json"], {}),
            source_work_item_id=row["source_work_item_id"],
            change_summary=row["change_summary"],
            created_at=_datetime(row["created_at"]),
        )
