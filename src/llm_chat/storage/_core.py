"""Storage 核心基础设施：单例/连接管理/schema 初始化"""

import sqlite3
import json
import os
import logging
from typing import Optional, Dict, Any, List
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class StorageCore:
    """Storage 核心基类

    职责：
    - 单例模式管理
    - SQLite 连接 (contextmanager)
    - 数据库 schema 初始化 (7 张表)
    - _row_to_dict 工具方法
    """

    _instance: Optional["StorageCore"] = None
    _db_path: str = ".vb/vermilion_bird.db"

    def __new__(cls, db_path: Optional[str] = None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            if db_path:
                cls._db_path = db_path
        return cls._instance

    def __init__(self, db_path: Optional[str] = None):
        if db_path:
            self._db_path = db_path
        self._init_db()

    # ------------------------------------------------------------------
    # 连接管理
    # ------------------------------------------------------------------

    @contextmanager
    def _get_connection(self):
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

    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        result = dict(row)
        if "metadata" in result and result["metadata"]:
            try:
                result["metadata"] = json.loads(result["metadata"])
            except json.JSONDecodeError:
                pass
        return result

    # ------------------------------------------------------------------
    # Schema 初始化
    # ------------------------------------------------------------------

    def _init_db(self):
        """初始化数据库 schema，使用单个连接确保 :memory: 模式兼容"""
        db_dir = os.path.dirname(self._db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        with self._get_connection() as conn:
            self._create_conversations_table_in(conn)
            self._create_messages_table_in(conn)
            self._create_fts_index_in(conn)
            self._apply_pragmas_in(conn)
            self._create_tasks_tables_in(conn)
            self._create_feishu_table_in(conn)
            self._create_context_cache_table_in(conn)

    def _create_conversations_table_in(self, conn):
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                metadata TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_conversations_updated_at
                ON conversations(updated_at);
        """)

    def _create_messages_table_in(self, conn):
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                metadata TEXT,
                FOREIGN KEY (conversation_id)
                    REFERENCES conversations(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_messages_conversation_id
                ON messages(conversation_id);
            CREATE INDEX IF NOT EXISTS idx_messages_created_at
                ON messages(created_at);
        """)

    def _create_fts_index_in(self, conn):
        try:
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                    content,
                    content='messages',
                    content_rowid='id'
                )
            """)
        except sqlite3.OperationalError:
            pass

    def _apply_pragmas_in(self, conn):
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")

    def _create_tasks_tables_in(self, conn):
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                task_type TEXT NOT NULL,
                trigger_config TEXT NOT NULL,
                params TEXT NOT NULL,
                enabled INTEGER DEFAULT 1,
                max_retries INTEGER DEFAULT 3,
                notify_enabled INTEGER DEFAULT 1,
                notify_targets TEXT,
                notify_on_success INTEGER DEFAULT 1,
                notify_on_failure INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS task_executions (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                finished_at TIMESTAMP,
                result TEXT,
                error TEXT,
                retry_count INTEGER DEFAULT 0,
                FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_task_executions_task_id
                ON task_executions(task_id);
            CREATE INDEX IF NOT EXISTS idx_task_executions_started_at
                ON task_executions(started_at);
        """)
        self._migrate_tasks_columns(conn)

    def _migrate_tasks_columns(self, conn):
        cursor = conn.execute("PRAGMA table_info(tasks)")
        columns = [row[1] for row in cursor.fetchall()]

        def add_if_missing(col_name, col_def):
            if col_name not in columns:
                try:
                    conn.execute(
                        f"ALTER TABLE tasks ADD COLUMN {col_name} {col_def}"
                    )
                except sqlite3.OperationalError:
                    pass

        add_if_missing("notify_enabled", "INTEGER DEFAULT 1")
        add_if_missing("notify_targets", "TEXT")
        add_if_missing("notify_on_success", "INTEGER DEFAULT 1")
        add_if_missing("notify_on_failure", "INTEGER DEFAULT 1")

    def _create_feishu_table_in(self, conn):
        conn.execute("""
            CREATE TABLE IF NOT EXISTS recent_feishu_chat (
                id INTEGER PRIMARY KEY,
                chat_id TEXT NOT NULL,
                chat_id_type TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

    def _create_context_cache_table_in(self, conn):
        conn.execute("""
            CREATE TABLE IF NOT EXISTS context_cache (
                cache_key TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                compression_level INTEGER NOT NULL,
                messages_json TEXT NOT NULL,
                token_count INTEGER NOT NULL,
                created_at REAL NOT NULL,
                last_accessed REAL NOT NULL,
                access_count INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_context_conversation_id "
            "ON context_cache(conversation_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_context_last_accessed "
            "ON context_cache(last_accessed)"
        )
