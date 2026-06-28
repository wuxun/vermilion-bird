"""DecisionLogStore — persist user decisions for audit trail and analytics.

Uses ember-core's SQLiteStore for storage, accepting it via constructor
dependency injection (no hard dependency on any specific Storage class).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from ember_core.storage.sqlite import SQLiteStore
from ember_agent.consensus.card import DecisionRecord

logger = logging.getLogger(__name__)

# ── SQL ─────────────────────────────────────────────────────────────

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS decision_log (
    id TEXT PRIMARY KEY,
    card_id TEXT NOT NULL,
    card_type TEXT NOT NULL,
    title TEXT NOT NULL,
    selected_option_id TEXT,
    selected_option_label TEXT,
    recommendation TEXT,
    context_snapshot TEXT,
    conversation_id TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    decided_at TIMESTAMP,
    execution_result TEXT,
    executed_at TIMESTAMP
);
"""

CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_decision_log_card_id ON decision_log(card_id);
CREATE INDEX IF NOT EXISTS idx_decision_log_created_at ON decision_log(created_at);
"""


class DecisionLogStore:
    """Persistent decision log backed by any SQLiteStore.

    Usage:
        store = SQLiteStore("path/to/db.sqlite")
        log = DecisionLogStore(store)
        log.record(card_id="...", selected_option_id="A", ...)
        history = log.get_history(limit=20)
    """

    def __init__(self, store: SQLiteStore):
        self._store = store
        self._ensure_table()

    def _ensure_table(self) -> None:
        """Ensure decision_log table exists (idempotent)."""
        with self._store.connection() as conn:
            conn.executescript(CREATE_TABLE_SQL + CREATE_INDEX_SQL)

    def record(
        self,
        card_id: str,
        card_type: str,
        title: str,
        selected_option_id: str,
        selected_option_label: Optional[str] = None,
        recommendation: Optional[str] = None,
        context_snapshot: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> str:
        """Record a decision. Returns the record ID."""
        record = DecisionRecord(
            card_id=card_id,
            card_type=card_type,
            title=title,
            selected_option_id=selected_option_id,
            selected_option_label=selected_option_label,
            recommendation=recommendation,
            context_snapshot=context_snapshot,
            conversation_id=conversation_id,
        )

        with self._store.connection() as conn:
            conn.execute(
                """INSERT INTO decision_log
                (id, card_id, card_type, title,
                 selected_option_id, selected_option_label,
                 recommendation, context_snapshot,
                 conversation_id, created_at, decided_at,
                 execution_result, executed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record.id,
                    record.card_id,
                    record.card_type.value,
                    record.title,
                    record.selected_option_id,
                    record.selected_option_label,
                    record.recommendation,
                    record.context_snapshot,
                    record.conversation_id,
                    record.created_at,
                    record.decided_at or datetime.now(),
                    None,
                    None,
                ),
            )

        logger.info(
            f"Decision recorded: card={card_id} → "
            f"{selected_option_id} ({selected_option_label})"
        )
        return record.id

    def record_from_card(self, card, option_id: str) -> str:
        """Record a decision from a DecisionCard that has been decided.

        Args:
            card: Decided DecisionCard instance.
            option_id: The selected option ID.
        """
        selected = next(
            (o for o in card.options if o.id == option_id), None
        )
        return self.record(
            card_id=card.id,
            card_type=card.card_type.value,
            title=card.title,
            selected_option_id=option_id,
            selected_option_label=selected.label if selected else None,
            recommendation=card.recommendation,
            conversation_id=card.conversation_id,
        )

    def get_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent decision history."""
        with self._store.connection() as conn:
            rows = conn.execute(
                """SELECT * FROM decision_log
                ORDER BY created_at DESC
                LIMIT ?""",
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def update_execution_result(
        self, record_id: str, result: str, success: bool = True
    ) -> None:
        """Backfill action execution result.

        Args:
            record_id: Decision record ID.
            result: Execution result summary.
            success: Whether execution succeeded.
        """
        payload = json.dumps(
            {
                "success": success,
                "result": result,
                "executed_at": datetime.now().isoformat(),
            },
            ensure_ascii=False,
        )
        with self._store.connection() as conn:
            conn.execute(
                "UPDATE decision_log SET execution_result = ?, "
                "executed_at = ? WHERE id = ?",
                (payload, datetime.now(), record_id),
            )
        logger.info(f"Execution result recorded: {record_id} (success={success})")

    def get_statistics(self) -> Dict[str, Any]:
        """Get decision statistics."""
        with self._store.connection() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM decision_log"
            ).fetchone()[0]

            by_type = conn.execute(
                """SELECT card_type, COUNT(*) as cnt
                FROM decision_log
                GROUP BY card_type
                ORDER BY cnt DESC"""
            ).fetchall()

            accepted = conn.execute(
                """SELECT COUNT(*) FROM decision_log
                WHERE selected_option_id = recommendation"""
            ).fetchone()[0]

            return {
                "total": total,
                "by_type": [dict(r) for r in by_type],
                "accepted": accepted,
                "acceptance_rate": round(accepted / total, 3) if total > 0 else 0,
            }
