"""Generic SQLite store — thread-safe, WAL mode, no business schema.

This is a low-level storage primitive. It provides:
- Thread-safe connection management (contextmanager)
- WAL journal mode
- Row-to-dict conversion with JSON metadata deserialization

It does NOT create any application-specific tables.
"""

import sqlite3
import json
import os
import logging
from typing import Optional, Dict, Any
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class SQLiteStore:
    """Thread-safe SQLite storage with WAL mode.

    Usage:
        store = SQLiteStore("path/to/db.sqlite")
        with store.connection() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS ...")
    """

    def __init__(self, db_path: str):
        self._db_path = db_path
        db_dir = os.path.dirname(db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        self._apply_pragmas()

    def _apply_pragmas(self) -> None:
        """Enable WAL mode and foreign keys."""
        with self.connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")

    @contextmanager
    def connection(self):
        """Get a thread-safe connection context.

        Commits on success, rolls back on exception, always closes.
        """
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        """Convert a sqlite3.Row to a dict, deserializing JSON 'metadata'."""
        result = dict(row)
        if "metadata" in result and result["metadata"]:
            try:
                result["metadata"] = json.loads(result["metadata"])
            except json.JSONDecodeError:
                pass
        return result

    @property
    def db_path(self) -> str:
        """The filesystem path to the SQLite database file."""
        return self._db_path
