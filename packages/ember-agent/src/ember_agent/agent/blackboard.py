"""SharedBlackboard — inter-agent shared workspace.

Agents post facts, findings, hypotheses, and questions to a shared
namespace. Other agents can query and discover context without
direct message passing.

Uses ember-core's SQLiteStore for optional persistence.
"""

from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from ember_core.storage.sqlite import SQLiteStore


class EntryType(str, Enum):
    FACT = "fact"              # Verified piece of information
    FINDING = "finding"        # Discovery with moderate confidence
    HYPOTHESIS = "hypothesis"  # Speculative claim needing verification
    QUESTION = "question"      # Open question for other agents


class BlackboardEntry(BaseModel):
    """A single entry on the shared blackboard."""

    id: str = Field(default_factory=lambda: f"bbe_{uuid.uuid4().hex[:12]}")
    agent_id: str = Field(description="Agent that posted this entry")
    key: str = Field(description="Short key summarizing the entry")
    value: Any = Field(description="The entry content (string, dict, etc.)")
    entry_type: EntryType = Field(default=EntryType.FINDING)
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    timestamp: float = Field(default_factory=time.time)
    tags: List[str] = Field(default_factory=list)


class SharedBlackboard:
    """In-memory shared workspace with optional SQLite persistence.

    Usage:
        bb = SharedBlackboard()
        bb.post(BlackboardEntry(agent_id="agent-1", key="auth_path",
                value="/src/auth.py", entry_type=EntryType.FACT, confidence=0.95))

        # Other agent queries
        results = bb.query("authentication")
        snapshot = bb.snapshot()
    """

    CREATE_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS blackboard_entries (
        id TEXT PRIMARY KEY,
        agent_id TEXT NOT NULL,
        key TEXT NOT NULL,
        value_json TEXT NOT NULL,
        entry_type TEXT NOT NULL,
        confidence REAL NOT NULL,
        timestamp REAL NOT NULL,
        tags_json TEXT NOT NULL DEFAULT '[]'
    );
    CREATE INDEX IF NOT EXISTS idx_bb_agent ON blackboard_entries(agent_id);
    CREATE INDEX IF NOT EXISTS idx_bb_type ON blackboard_entries(entry_type);
    CREATE INDEX IF NOT EXISTS idx_bb_timestamp ON blackboard_entries(timestamp);
    """

    def __init__(self, store: Optional[SQLiteStore] = None):
        self._entries: Dict[str, BlackboardEntry] = {}
        self._store = store
        if store:
            with store.connection() as conn:
                conn.executescript(self.CREATE_TABLE_SQL)

    def post(self, entry: BlackboardEntry) -> str:
        """Post an entry. Returns the entry ID."""
        self._entries[entry.id] = entry
        if self._store:
            self._persist(entry)
        return entry.id

    def get(self, entry_id: str) -> Optional[BlackboardEntry]:
        """Get an entry by ID."""
        return self._entries.get(entry_id)

    def query(
        self,
        query: str,
        entry_type: Optional[EntryType] = None,
        agent_id: Optional[str] = None,
        min_confidence: float = 0.0,
        top_k: int = 10,
    ) -> List[BlackboardEntry]:
        """Simple keyword query over keys and string values.

        Matches query against entry.key and str(entry.value).
        Filters by entry_type, agent_id, and min_confidence.
        Returns up to top_k entries, sorted by confidence (highest first).
        """
        results = []
        query_lower = query.lower()

        for entry in self._entries.values():
            if entry_type and entry.entry_type != entry_type:
                continue
            if agent_id and entry.agent_id != agent_id:
                continue
            if entry.confidence < min_confidence:
                continue

            # Match against key and string value
            searchable = f"{entry.key} {str(entry.value)}".lower()
            if query_lower in searchable:
                results.append(entry)

        results.sort(key=lambda e: e.confidence, reverse=True)
        return results[:top_k]

    def snapshot(
        self,
        entry_type: Optional[EntryType] = None,
        agent_id: Optional[str] = None,
    ) -> List[BlackboardEntry]:
        """Get all entries, optionally filtered."""
        entries = list(self._entries.values())
        if entry_type:
            entries = [e for e in entries if e.entry_type == entry_type]
        if agent_id:
            entries = [e for e in entries if e.agent_id == agent_id]
        return sorted(entries, key=lambda e: e.timestamp)

    def clear(self) -> None:
        """Remove all entries."""
        self._entries.clear()

    def remove(self, entry_id: str) -> bool:
        """Remove a specific entry."""
        return self._entries.pop(entry_id, None) is not None

    def __len__(self) -> int:
        return len(self._entries)

    # ── Persistence ──────────────────────────────────────────────

    def _persist(self, entry: BlackboardEntry) -> None:
        if not self._store:
            return
        import json
        with self._store.connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO blackboard_entries
                (id, agent_id, key, value_json, entry_type, confidence, timestamp, tags_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry.id,
                    entry.agent_id,
                    entry.key,
                    json.dumps(entry.value, default=str, ensure_ascii=False),
                    entry.entry_type.value,
                    entry.confidence,
                    entry.timestamp,
                    json.dumps(entry.tags, ensure_ascii=False),
                ),
            )
