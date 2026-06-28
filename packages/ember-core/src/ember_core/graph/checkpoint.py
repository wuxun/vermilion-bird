"""Checkpointer — persist state graph execution for resume.

Abstract interface + two implementations:
    MemoryCheckpointer  — in-memory dict (tests, transient use)
    SQLiteCheckpointer  — persistent (production)
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Tuple

from ember_core.storage.sqlite import SQLiteStore


class Checkpointer(ABC):
    """Abstract checkpointer for state graph execution."""

    @abstractmethod
    def save(
        self, thread_id: str, step: int, node_name: str, state: Dict[str, Any]
    ) -> None:
        """Save a checkpoint snapshot."""

    @abstractmethod
    def load(self, thread_id: str) -> Optional[Tuple[int, str, Dict[str, Any]]]:
        """Load the latest checkpoint for a thread.

        Returns (step, node_name, state_dict) or None.
        """

    @abstractmethod
    def delete(self, thread_id: str) -> None:
        """Remove all checkpoints for a thread."""


class MemoryCheckpointer(Checkpointer):
    """In-memory checkpointer. All data lost on process exit."""

    def __init__(self):
        self._store: Dict[str, Tuple[int, str, Dict[str, Any]]] = {}

    def save(
        self, thread_id: str, step: int, node_name: str, state: Dict[str, Any]
    ) -> None:
        self._store[thread_id] = (step, node_name, state)

    def load(self, thread_id: str) -> Optional[Tuple[int, str, Dict[str, Any]]]:
        return self._store.get(thread_id)

    def delete(self, thread_id: str) -> None:
        self._store.pop(thread_id, None)


class SQLiteCheckpointer(Checkpointer):
    """Persistent SQLite-backed checkpointer.

    Uses the ember-core SQLiteStore for connection management.
    """

    CREATE_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS graph_checkpoints (
        thread_id TEXT NOT NULL,
        step INTEGER NOT NULL,
        node_name TEXT NOT NULL,
        state_json TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (thread_id)
    );
    """

    def __init__(self, store: SQLiteStore):
        self._store = store
        with self._store.connection() as conn:
            conn.executescript(self.CREATE_TABLE_SQL)

    def save(
        self, thread_id: str, step: int, node_name: str, state: Dict[str, Any]
    ) -> None:
        state_json = json.dumps(state, default=str, ensure_ascii=False)
        with self._store.connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO graph_checkpoints
                (thread_id, step, node_name, state_json)
                VALUES (?, ?, ?, ?)""",
                (thread_id, step, node_name, state_json),
            )

    def load(self, thread_id: str) -> Optional[Tuple[int, str, Dict[str, Any]]]:
        with self._store.connection() as conn:
            row = conn.execute(
                "SELECT step, node_name, state_json FROM graph_checkpoints "
                "WHERE thread_id = ?",
                (thread_id,),
            ).fetchone()
            if row is None:
                return None
            return (
                row["step"],
                row["node_name"],
                json.loads(row["state_json"]),
            )

    def delete(self, thread_id: str) -> None:
        with self._store.connection() as conn:
            conn.execute(
                "DELETE FROM graph_checkpoints WHERE thread_id = ?",
                (thread_id,),
            )
