import sqlite3
import json
import os
import time
import logging
from typing import List, Dict, Any, Optional
from .scheduler.models import Task, TaskExecution, TaskType, TaskStatus
from datetime import datetime
from contextlib import contextmanager


logger = logging.getLogger(__name__)


class Storage:
    _instance: Optional["Storage"] = None
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

    def _init_db(self):
        db_dir = os.path.dirname(self._db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

            with self._get_connection() as conn:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    title TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    metadata TEXT
                );
                
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    metadata TEXT,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
                );
                
                CREATE INDEX IF NOT EXISTS idx_messages_conversation_id ON messages(conversation_id);
                CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages(created_at);
                CREATE INDEX IF NOT EXISTS idx_conversations_updated_at ON conversations(updated_at);
            """)

            # Perform optional FT index creation in a fresh connection
            with self._get_connection() as conn:
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

            with self._get_connection() as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA foreign_keys=ON")

            # Extend schema: tasks and task_executions tables for scheduling
            with self._get_connection() as conn:
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
                
                CREATE INDEX IF NOT EXISTS idx_task_executions_task_id ON task_executions(task_id);
                CREATE INDEX IF NOT EXISTS idx_task_executions_started_at ON task_executions(started_at);
                """)

                # Check and add missing columns for existing databases
                cursor = conn.execute("PRAGMA table_info(tasks)")
                columns = [row[1] for row in cursor.fetchall()]

                def add_column_if_missing(col_name, col_def):
                    if col_name not in columns:
                        try:
                            conn.execute(
                                f"ALTER TABLE tasks ADD COLUMN {col_name} {col_def}"
                            )
                        except sqlite3.OperationalError:
                            pass

                add_column_if_missing("notify_enabled", "INTEGER DEFAULT 1")
                add_column_if_missing("notify_targets", "TEXT")
                add_column_if_missing("notify_on_success", "INTEGER DEFAULT 1")
                add_column_if_missing("notify_on_failure", "INTEGER DEFAULT 1")

            # 创建表来保存最近的飞书对话
            with self._get_connection() as conn:
                conn.execute("""
                CREATE TABLE IF NOT EXISTS recent_feishu_chat (
                    id INTEGER PRIMARY KEY,
                    chat_id TEXT NOT NULL,
                    chat_id_type TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """)

            # 创建上下文缓存表
            with self._get_connection() as conn:
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

                # 创建索引
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_context_conversation_id ON context_cache(conversation_id)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_context_last_accessed ON context_cache(last_accessed)"
                )

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

    def create_conversation(
        self,
        conversation_id: str,
        title: Optional[str] = None,
        metadata: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        with self._get_connection() as conn:
            now = datetime.now().isoformat()
            conn.execute(
                "INSERT OR REPLACE INTO conversations (id, title, created_at, updated_at, metadata) VALUES (?, ?, ?, ?, ?)",
                (
                    conversation_id,
                    title,
                    now,
                    now,
                    json.dumps(metadata) if metadata else None,
                ),
            )
            return {
                "id": conversation_id,
                "title": title,
                "created_at": now,
                "updated_at": now,
                "metadata": metadata,
            }

    def get_conversation(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
            ).fetchone()
            if row:
                return self._row_to_dict(row)
            return None

    def list_conversations(
        self, limit: int = 50, offset: int = 0
    ) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM conversations ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            return [self._row_to_dict(row) for row in rows]

    def update_conversation(
        self,
        conversation_id: str,
        title: Optional[str] = None,
        metadata: Optional[Dict] = None,
    ) -> bool:
        with self._get_connection() as conn:
            now = datetime.now().isoformat()
            if title is not None:
                conn.execute(
                    "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
                    (title, now, conversation_id),
                )
            if metadata is not None:
                conn.execute(
                    "UPDATE conversations SET metadata = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(metadata), now, conversation_id),
                )
            return True

    def delete_conversation(self, conversation_id: str) -> bool:
        with self._get_connection() as conn:
            conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
            return True

    # ===== Task scheduling extensions =====
    def save_task(self, task: "Task") -> str:
        # Persist task definition
        with self._get_connection() as conn:
            trigger_config = (
                json.dumps(task.trigger_config)
                if task.trigger_config is not None
                else json.dumps({})
            )
            params = (
                json.dumps(task.params) if task.params is not None else json.dumps({})
            )
            created_at = (
                task.created_at.isoformat() if hasattr(task, "created_at") else None
            )
            updated_at = (
                task.updated_at.isoformat() if hasattr(task, "updated_at") else None
            )
            notify_targets = getattr(task, "notify_targets", None)
            notify_targets_json = json.dumps(notify_targets) if notify_targets else None
            conn.execute(
                "INSERT OR REPLACE INTO tasks (id, name, task_type, trigger_config, params, enabled, max_retries, notify_enabled, notify_targets, notify_on_success, notify_on_failure, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    task.id,
                    task.name,
                    task.task_type.value
                    if isinstance(task.task_type, TaskType)
                    else str(task.task_type),
                    trigger_config,
                    params,
                    int(getattr(task, "enabled", True)),
                    int(getattr(task, "max_retries", 3)),
                    int(getattr(task, "notify_enabled", True)),
                    notify_targets_json,
                    int(getattr(task, "notify_on_success", True)),
                    int(getattr(task, "notify_on_failure", True)),
                    created_at,
                    updated_at,
                ),
            )
            return task.id

    def load_task(self, task_id: str) -> Optional["Task"]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
            if not row:
                return None
            trigger_config = (
                json.loads(row["trigger_config"]) if row["trigger_config"] else {}
            )
            params = json.loads(row["params"]) if row["params"] else {}
            created_at = (
                datetime.fromisoformat(row["created_at"]) if row["created_at"] else None
            )
            updated_at = (
                datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None
            )
            notify_targets = None
            if "notify_targets" in row.keys() and row["notify_targets"]:
                try:
                    notify_targets = json.loads(row["notify_targets"])
                except (json.JSONDecodeError, TypeError):
                    pass
            # 将 Row 转换为字典以便使用 get()
            row_dict = dict(row)
            return Task(
                id=row_dict["id"],
                name=row_dict["name"],
                task_type=TaskType(row_dict["task_type"])
                if isinstance(row_dict["task_type"], str)
                else row_dict["task_type"],
                trigger_config=trigger_config,
                params=params,
                enabled=bool(row_dict["enabled"]),
                max_retries=row_dict["max_retries"]
                if row_dict["max_retries"] is not None
                else 3,
                created_at=created_at,
                updated_at=updated_at,
                notify_enabled=bool(row_dict.get("notify_enabled", True)),
                notify_targets=notify_targets,
                notify_on_success=bool(row_dict.get("notify_on_success", True)),
                notify_on_failure=bool(row_dict.get("notify_on_failure", True)),
            )

    def load_all_tasks(self) -> List["Task"]:
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM tasks ORDER BY updated_at DESC"
            ).fetchall()
            tasks: List["Task"] = []
            for row in rows:
                t = self.load_task(row["id"])
                if t:
                    tasks.append(t)
            return tasks

    def delete_task(self, task_id: str) -> bool:
        with self._get_connection() as conn:
            conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            return True

    def save_execution(self, execution: "TaskExecution") -> str:
        with self._get_connection() as conn:
            started_at = (
                execution.started_at.isoformat()
                if isinstance(execution.started_at, datetime)
                else None
            )
            finished_at = (
                execution.finished_at.isoformat()
                if isinstance(execution.finished_at, datetime)
                else None
            )
            status = (
                execution.status.value
                if isinstance(execution.status, TaskStatus)
                else str(execution.status)
            )
            conn.execute(
                "INSERT OR REPLACE INTO task_executions (id, task_id, status, started_at, finished_at, result, error, retry_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    execution.id,
                    execution.task_id,
                    status,
                    started_at,
                    finished_at,
                    execution.result,
                    execution.error,
                    getattr(execution, "retry_count", 0),
                ),
            )
            return execution.id

    def load_executions(self, task_id: str, limit: int = 100) -> List["TaskExecution"]:
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM task_executions WHERE task_id = ? ORDER BY started_at DESC LIMIT ?",
                (task_id, limit),
            ).fetchall()
            executions: List["TaskExecution"] = []
            for row in rows:
                started_at = (
                    datetime.fromisoformat(row["started_at"])
                    if row["started_at"]
                    else None
                )
                finished_at = (
                    datetime.fromisoformat(row["finished_at"])
                    if row["finished_at"]
                    else None
                )
                exec_obj = TaskExecution(
                    id=row["id"],
                    task_id=row["task_id"],
                    status=TaskStatus(row["status"])
                    if isinstance(row["status"], str)
                    else row["status"],
                    started_at=started_at,
                    finished_at=finished_at,
                    result=row["result"],
                    error=row["error"],
                    retry_count=row["retry_count"]
                    if row["retry_count"] is not None
                    else 0,
                )
                executions.append(exec_obj)
            return executions

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        metadata: Optional[Dict] = None,
    ) -> int:
        with self._get_connection() as conn:
            now = datetime.now().isoformat()
            cursor = conn.execute(
                "INSERT INTO messages (conversation_id, role, content, created_at, metadata) VALUES (?, ?, ?, ?, ?)",
                (
                    conversation_id,
                    role,
                    content,
                    now,
                    json.dumps(metadata) if metadata else None,
                ),
            )
            message_id = cursor.lastrowid

            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now, conversation_id),
            )

            return message_id

    def get_messages(
        self, conversation_id: str, limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            if limit:
                rows = conn.execute(
                    "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at ASC LIMIT ?",
                    (conversation_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at ASC",
                    (conversation_id,),
                ).fetchall()
            return [self._row_to_dict(row) for row in rows]

    def clear_messages(self, conversation_id: str) -> bool:
        with self._get_connection() as conn:
            conn.execute(
                "DELETE FROM messages WHERE conversation_id = ?", (conversation_id,)
            )
            now = datetime.now().isoformat()
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now, conversation_id),
            )
            return True

    def search_messages(
        self, query: str, conversation_id: Optional[str] = None, limit: int = 20
    ) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            try:
                if conversation_id:
                    rows = conn.execute(
                        """
                        SELECT m.* FROM messages m
                        JOIN messages_fts fts ON m.id = fts.rowid
                        WHERE messages_fts MATCH ? AND m.conversation_id = ?
                        ORDER BY m.created_at DESC LIMIT ?
                        """,
                        (query, conversation_id, limit),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT m.* FROM messages m
                        JOIN messages_fts fts ON m.id = fts.rowid
                        WHERE messages_fts MATCH ?
                        ORDER BY m.created_at DESC LIMIT ?
                        """,
                        (query, limit),
                    ).fetchall()
                return [self._row_to_dict(row) for row in rows]
            except sqlite3.OperationalError:
                rows = conn.execute(
                    "SELECT * FROM messages WHERE content LIKE ? ORDER BY created_at DESC LIMIT ?",
                    (f"%{query}%", limit),
                ).fetchall()
                return [self._row_to_dict(row) for row in rows]

    def get_conversation_count(self) -> int:
        with self._get_connection() as conn:
            row = conn.execute("SELECT COUNT(*) as count FROM conversations").fetchone()
            return row["count"] if row else 0

    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        result = dict(row)
        if "metadata" in result and result["metadata"]:
            try:
                result["metadata"] = json.loads(result["metadata"])
            except json.JSONDecodeError:
                pass
        return result

    def migrate_from_json(self, json_dir: str = ".vb/history") -> int:
        migrated = 0
        if not os.path.exists(json_dir):
            return migrated

        for filename in os.listdir(json_dir):
            if not filename.endswith(".json"):
                continue

            filepath = os.path.join(json_dir, filename)
            conversation_id = filename[:-5]

            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    messages = json.load(f)

                if not messages:
                    continue

                first_user_msg = next(
                    (m for m in messages if m.get("role") == "user"), None
                )
                title = None
                if first_user_msg and first_user_msg.get("content"):
                    title = first_user_msg["content"][:30]
                    if len(first_user_msg["content"]) > 30:
                        title += "..."

                existing = self.get_conversation(conversation_id)
                if not existing:
                    self.create_conversation(conversation_id, title)

                existing_messages = self.get_messages(conversation_id)
                existing_count = len(existing_messages)

                for i, msg in enumerate(
                    messages[existing_count:], start=existing_count
                ):
                    self.add_message(
                        conversation_id,
                        msg.get("role", "user"),
                        msg.get("content", ""),
                        msg.get("metadata"),
                    )

                migrated += 1

            except Exception as e:
                print(f"迁移 {filename} 失败: {e}")

        return migrated

    def set_recent_feishu_chat(self, chat_id: str, chat_id_type: str = "chat_id"):
        """保存最近的飞书对话到数据库。

        Args:
            chat_id: 群聊 ID 或用户 ID
            chat_id_type: ID 类型，'chat_id' 或 'open_id' 或 'user_id'
        """
        with self._get_connection() as conn:
            # 先删除旧记录
            conn.execute("DELETE FROM recent_feishu_chat")
            # 插入新记录
            conn.execute(
                "INSERT INTO recent_feishu_chat (chat_id, chat_id_type) VALUES (?, ?)",
                (chat_id, chat_id_type),
            )
            logger.info(f"Saved recent Feishu chat: {chat_id_type}={chat_id}")

    def get_recent_feishu_chat(self) -> Optional[Dict[str, str]]:
        """从数据库查询最近的飞书对话。

        Returns:
            飞书对话信息字典，格式为 {"type": "feishu", "chat_id": "xxx"} 或 None
        """
        with self._get_connection() as conn:
            # 先从专门的表查询
            row = conn.execute(
                "SELECT chat_id, chat_id_type FROM recent_feishu_chat ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()

            if row:
                logger.info(
                    f"Found recent Feishu chat from recent_feishu_chat: {row['chat_id_type']}={row['chat_id']}"
                )
                return {
                    "type": "feishu",
                    row["chat_id_type"]: row["chat_id"],
                }

            # 如果专门表中没有，尝试从会话表中查找（向后兼容）
            rows = conn.execute(
                "SELECT id FROM conversations ORDER BY updated_at DESC LIMIT 20"
            ).fetchall()

            for row in rows:
                conv_id = row["id"]
                # 检查是否是飞书会话
                if conv_id.startswith("feishu_p2p_") or conv_id.startswith(
                    "feishu_group_"
                ):
                    # 从会话 ID 中提取原始 ID
                    try:
                        if conv_id.startswith("feishu_p2p_"):
                            rest = conv_id[len("feishu_p2p_") :]
                        else:  # feishu_group_
                            rest = conv_id[len("feishu_group_") :]

                        # 移除会话编号部分（如果有）
                        parts = rest.rsplit("_", 1)
                        if len(parts) == 2 and parts[1].isdigit():
                            original_id = parts[0]
                        else:
                            original_id = rest

                        # 将下划线还原回原始字符（SessionMapper 会替换非字母数字字符为下划线）
                        # 注意：这里我们无法完全还原原始 ID，但大多数情况下飞书 ID 只包含字母数字和下划线
                        logger.info(
                            f"Found recent Feishu chat from conversations: {original_id}"
                        )
                        return {
                            "type": "feishu",
                            "chat_id": original_id,
                        }
                    except Exception as e:
                        logger.warning(
                            f"Failed to parse Feishu conversation ID {conv_id}: {e}"
                        )
                        continue

            logger.info("No recent Feishu chat found in database")
            return None
