"""Task output persistence (daily_digest table).

Records LLM_CHAT task outputs for historical querying
and cross-task reference (e.g. weekly review reads daily digests).
"""

import json
import logging
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)


class StorageDigestMixin:
    """Daily news digest CRUD operations.

    Follows the StorageTaskMixin pattern (_task.py).
    Uses _get_connection() from StorageCore.
    """

    def save_digest(
        self,
        digest_date: str,
        items: list,
        raw_context: str = "",
        source: str = "",
    ) -> str:
        """Save or replace digest for a given date + source.

        Args:
            digest_date: ISO date string, e.g. '2026-05-23'
            items: list of dicts with keys (title, summary, source, source_url, relevance)
            raw_context: raw collected context or task prompt
            source: task name or identifier — same (date, source) will be replaced

        Returns:
            digest id (UUID hex)
        """
        import hashlib
        digest_id = hashlib.md5(f"{digest_date}|{source}".encode()).hexdigest()[:12]
        items_json = json.dumps(items, ensure_ascii=False)
        raw_json = json.dumps(
            {"context": raw_context}, ensure_ascii=False
        ) if raw_context else "{}"

        with self._get_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO daily_digest "
                "(id, date, source, items_json, raw_context_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (digest_id, digest_date, source, items_json, raw_json),
            )
            logger.info(
                f"Digest saved: {digest_id} date={digest_date} "
                f"source={source} items={len(items)}"
            )
            return digest_id

    def get_today_digest(self, source: Optional[str] = None) -> Optional[dict]:
        """Retrieve today's digest, optionally filtered by source."""
        today = date.today().isoformat()
        with self._get_connection() as conn:
            if source:
                row = conn.execute(
                    "SELECT * FROM daily_digest WHERE date = ? AND source = ?",
                    (today, source),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM daily_digest WHERE date = ?",
                    (today,),
                ).fetchone()
            if not row:
                return None

            items = []
            try:
                items = json.loads(row["items_json"])
            except (json.JSONDecodeError, TypeError):
                logger.warning(
                    f"Failed to parse items_json for date={today}"
                )

            raw_context = ""
            try:
                raw_data = json.loads(
                    row["raw_context_json"] or "{}"
                )
                raw_context = raw_data.get("context", "")
            except (json.JSONDecodeError, TypeError):
                pass

            return {
                "id": row["id"],
                "date": row["date"],
                "items": items,
                "raw_context": raw_context,
            }

    def get_digest_by_date(
        self, digest_date: str, source: Optional[str] = None
    ) -> Optional[dict]:
        """Retrieve digest for a specific date, optionally filtered by source."""
        with self._get_connection() as conn:
            if source:
                row = conn.execute(
                    "SELECT * FROM daily_digest WHERE date = ? AND source = ?",
                    (digest_date, source),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM daily_digest WHERE date = ?",
                    (digest_date,),
                ).fetchone()
            if not row:
                return None
            items = []
            try:
                items = json.loads(row["items_json"])
            except (json.JSONDecodeError, TypeError):
                pass
            raw_context = ""
            try:
                raw_data = json.loads(row["raw_context_json"] or "{}")
                raw_context = raw_data.get("context", "")
            except (json.JSONDecodeError, TypeError):
                pass
            return {
                "id": row["id"],
                "date": row["date"],
                "items": items,
                "raw_context": raw_context,
            }
