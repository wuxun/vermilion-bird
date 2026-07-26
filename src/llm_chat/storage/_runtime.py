"""运行记录与动作审批的 SQLite 持久化。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, List, Optional

from llm_chat.runtime.actions import ActionProposal, ActionStatus, Capability
from llm_chat.runtime.models import Run, RunEvent, RunStatus, RunType


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


class StorageRuntimeMixin:
    """为 Storage 提供 Run 与 ActionProposal 仓储能力。"""

    def save_run(self, run: Run) -> None:
        """新增或更新一次运行，不覆盖已经持久化的事件。"""

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO runs (
                    id, parent_run_id, type, status, conversation_id,
                    input_json, result_json, error, metadata_json,
                    created_at, started_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    parent_run_id = excluded.parent_run_id,
                    type = excluded.type,
                    status = excluded.status,
                    conversation_id = excluded.conversation_id,
                    input_json = excluded.input_json,
                    result_json = excluded.result_json,
                    error = excluded.error,
                    metadata_json = excluded.metadata_json,
                    started_at = excluded.started_at,
                    finished_at = excluded.finished_at
                """,
                (
                    run.id,
                    run.parent_run_id,
                    run.type.value,
                    run.status.value,
                    run.conversation_id,
                    _dump_json(run.input),
                    _dump_json(run.result),
                    run.error,
                    _dump_json(run.metadata),
                    run.created_at.isoformat(),
                    run.started_at.isoformat() if run.started_at else None,
                    run.finished_at.isoformat() if run.finished_at else None,
                ),
            )

    def append_run_event(self, run_id: str, event: RunEvent) -> None:
        """追加运行事件；相同序号的重复写入保持幂等。"""

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO run_events (run_id, sequence, type, timestamp, data_json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(run_id, sequence) DO UPDATE SET
                    type = excluded.type,
                    timestamp = excluded.timestamp,
                    data_json = excluded.data_json
                """,
                (
                    run_id,
                    event.sequence,
                    event.type,
                    event.timestamp.isoformat(),
                    _dump_json(event.data),
                ),
            )

    def get_run(self, run_id: str) -> Optional[Run]:
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                return None
            events = self._fetch_run_events(conn, run_id)
        return self._row_to_run(row, events)

    def list_runs(
        self,
        limit: int = 50,
        *,
        offset: int = 0,
        status: Optional[RunStatus] = None,
        run_type: Optional[RunType] = None,
        conversation_id: Optional[str] = None,
    ) -> List[Run]:
        clauses = []
        params: List[Any] = []
        if status is not None:
            clauses.append("status = ?")
            params.append(status.value if isinstance(status, RunStatus) else str(status))
        if run_type is not None:
            clauses.append("type = ?")
            params.append(run_type.value if isinstance(run_type, RunType) else str(run_type))
        if conversation_id is not None:
            clauses.append("conversation_id = ?")
            params.append(conversation_id)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend((max(1, limit), max(0, offset)))
        with self._get_connection() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM runs
                {where}
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                params,
            ).fetchall()
            return self._rows_to_runs(conn, rows)

    def list_child_runs(self, parent_run_id: str) -> List[Run]:
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM runs
                WHERE parent_run_id = ?
                ORDER BY created_at ASC
                """,
                (parent_run_id,),
            ).fetchall()
            return self._rows_to_runs(conn, rows)

    @classmethod
    def _rows_to_runs(cls, conn: Any, rows: Any) -> List[Run]:
        """批量装配 Run，避免列表刷新时逐条读取事件。"""

        if not rows:
            return []
        run_ids = [row["id"] for row in rows]
        events_by_run = {run_id: [] for run_id in run_ids}
        # 保持低于旧版 SQLite 常见的 999 个绑定参数上限。
        for start in range(0, len(run_ids), 500):
            chunk = run_ids[start : start + 500]
            placeholders = ", ".join("?" for _ in chunk)
            event_rows = conn.execute(
                f"""
                SELECT run_id, sequence, type, timestamp, data_json
                FROM run_events
                WHERE run_id IN ({placeholders})
                ORDER BY run_id, sequence ASC
                """,
                chunk,
            ).fetchall()
            for event in event_rows:
                events_by_run[event["run_id"]].append(event)
        return [cls._row_to_run(row, events_by_run.get(row["id"], [])) for row in rows]

    @staticmethod
    def _fetch_run_events(conn: Any, run_id: str) -> Any:
        return conn.execute(
            """
            SELECT sequence, type, timestamp, data_json
            FROM run_events
            WHERE run_id = ?
            ORDER BY sequence ASC
            """,
            (run_id,),
        ).fetchall()

    @staticmethod
    def _row_to_run(row: Any, event_rows: Any) -> Run:
        now = datetime.now(timezone.utc)
        events = [
            RunEvent(
                sequence=event["sequence"],
                type=event["type"],
                timestamp=_parse_datetime(event["timestamp"]) or now,
                data=_load_json(event["data_json"], {}),
            )
            for event in event_rows
        ]
        return Run(
            id=row["id"],
            parent_run_id=row["parent_run_id"],
            type=RunType(row["type"]),
            status=RunStatus(row["status"]),
            conversation_id=row["conversation_id"],
            input=_load_json(row["input_json"], {}),
            result=_load_json(row["result_json"], None),
            error=row["error"],
            metadata=_load_json(row["metadata_json"], {}),
            created_at=_parse_datetime(row["created_at"]) or now,
            started_at=_parse_datetime(row["started_at"]),
            finished_at=_parse_datetime(row["finished_at"]),
            events=events,
        )

    def save_action_proposal(self, proposal: ActionProposal) -> None:
        """新增或更新审批提案。"""

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO action_proposals (
                    id, run_id, conversation_id, tool_name, arguments_json,
                    capabilities_json, reason, impact, risk, reversible, status,
                    created_at, decided_at, finished_at, result_json, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    run_id = excluded.run_id,
                    conversation_id = excluded.conversation_id,
                    tool_name = excluded.tool_name,
                    arguments_json = excluded.arguments_json,
                    capabilities_json = excluded.capabilities_json,
                    reason = excluded.reason,
                    impact = excluded.impact,
                    risk = excluded.risk,
                    reversible = excluded.reversible,
                    status = excluded.status,
                    decided_at = excluded.decided_at,
                    finished_at = excluded.finished_at,
                    result_json = excluded.result_json,
                    error = excluded.error
                """,
                (
                    proposal.id,
                    proposal.run_id,
                    proposal.conversation_id,
                    proposal.tool_name,
                    _dump_json(proposal.arguments),
                    _dump_json(sorted(item.value for item in proposal.capabilities)),
                    proposal.reason,
                    proposal.impact,
                    proposal.risk,
                    int(proposal.reversible),
                    proposal.status.value,
                    proposal.created_at.isoformat(),
                    proposal.decided_at.isoformat() if proposal.decided_at else None,
                    proposal.finished_at.isoformat() if proposal.finished_at else None,
                    _dump_json(proposal.result),
                    proposal.error,
                ),
            )

    def get_action_proposal(self, proposal_id: str) -> Optional[ActionProposal]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM action_proposals WHERE id = ?", (proposal_id,)
            ).fetchone()
        return self._row_to_action_proposal(row) if row is not None else None

    def list_action_proposals(
        self,
        limit: int = 100,
        *,
        offset: int = 0,
        status: Optional[ActionStatus] = None,
        run_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> List[ActionProposal]:
        clauses = []
        params: List[Any] = []
        if status is not None:
            clauses.append("status = ?")
            params.append(status.value if isinstance(status, ActionStatus) else str(status))
        if run_id is not None:
            clauses.append("run_id = ?")
            params.append(run_id)
        if conversation_id is not None:
            clauses.append("conversation_id = ?")
            params.append(conversation_id)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend((max(1, limit), max(0, offset)))
        with self._get_connection() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM action_proposals
                {where}
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                params,
            ).fetchall()
        return [self._row_to_action_proposal(row) for row in rows]

    @staticmethod
    def _row_to_action_proposal(row: Any) -> ActionProposal:
        return ActionProposal(
            id=row["id"],
            run_id=row["run_id"],
            conversation_id=row["conversation_id"],
            tool_name=row["tool_name"],
            arguments=_load_json(row["arguments_json"], {}),
            capabilities={Capability(value) for value in _load_json(row["capabilities_json"], [])},
            reason=row["reason"],
            impact=row["impact"],
            risk=row["risk"],
            reversible=bool(row["reversible"]),
            status=ActionStatus(row["status"]),
            created_at=_parse_datetime(row["created_at"]) or datetime.now(timezone.utc),
            decided_at=_parse_datetime(row["decided_at"]),
            finished_at=_parse_datetime(row["finished_at"]),
            result=_load_json(row["result_json"], None),
            error=row["error"],
        )
