"""决策日志持久化。

将用户做出的决策记录到 SQLite，形成可检索的决策历史。

用法:
    from llm_chat.decision.log import DecisionLogStore

    store = DecisionLogStore()
    store.record("card_xxx", "A", "连接池扩容")
    history = store.get_history(limit=20)
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from llm_chat.decision.schema import CardType, DecisionRecord

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


# ── Store ────────────────────────────────────────────────────────────


class DecisionLogStore:
    """决策日志存储。"""

    def __init__(self):
        self._storage = None

    def _get_storage(self):
        if self._storage is None:
            from llm_chat.storage import Storage
            self._storage = Storage()
        return self._storage

    def ensure_table(self):
        """确保 decision_log 表存在（幂等）。"""
        storage = self._get_storage()
        with storage._get_connection() as conn:
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
        """记录一条决策。

        Returns:
            记录 ID。
        """
        self.ensure_table()

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

        storage = self._get_storage()
        with storage._get_connection() as conn:
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
                    None,  # execution_result — 执行后回填
                    None,  # executed_at
                ),
            )

        logger.info(
            f"决策已记录: card={card_id} -> {selected_option_id} ({selected_option_label})"
        )
        return record.id

    def record_from_card(self, card: "DecisionCard", option_id: str) -> str:
        """从已决策的卡片创建日志记录。

        Args:
            card: 已决策的 DecisionCard 实例。
            option_id: 被选择的选项 ID。
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
        """获取最近的决策历史。"""
        self.ensure_table()

        storage = self._get_storage()
        with storage._get_connection() as conn:
            rows = conn.execute(
                """SELECT * FROM decision_log
                ORDER BY created_at DESC
                LIMIT ?""",
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def update_execution_result(
        self, record_id: str, result: str, success: bool = True
    ):
        """回填 action 执行结果。

        Args:
            record_id: 决策记录 ID。
            result: 执行结果摘要。
            success: 是否成功。
        """
        import json
        self.ensure_table()
        payload = json.dumps({
            "success": success,
            "result": result,
            "executed_at": datetime.now().isoformat(),
        }, ensure_ascii=False)
        storage = self._get_storage()
        with storage._get_connection() as conn:
            conn.execute(
                "UPDATE decision_log SET execution_result = ?, executed_at = ? WHERE id = ?",
                (payload, datetime.now(), record_id),
            )
        logger.info(f"执行结果已记录: {record_id} (success={success})")

    def get_statistics(self) -> Dict[str, Any]:
        """获取决策统计。"""
        self.ensure_table()

        storage = self._get_storage()
        with storage._get_connection() as conn:
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
