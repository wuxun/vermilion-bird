import sqlite3
import json
import os
import time
from typing import List, Dict, Any, Optional
from datetime import datetime
from contextlib import contextmanager


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
            
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
    
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
    
    def create_conversation(self, conversation_id: str, title: Optional[str] = None, metadata: Optional[Dict] = None) -> Dict[str, Any]:
        with self._get_connection() as conn:
            now = datetime.now().isoformat()
            conn.execute(
                "INSERT OR REPLACE INTO conversations (id, title, created_at, updated_at, metadata) VALUES (?, ?, ?, ?, ?)",
                (conversation_id, title, now, now, json.dumps(metadata) if metadata else None)
            )
            return {
                "id": conversation_id,
                "title": title,
                "created_at": now,
                "updated_at": now,
                "metadata": metadata
            }
    
    def get_conversation(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM conversations WHERE id = ?",
                (conversation_id,)
            ).fetchone()
            if row:
                return self._row_to_dict(row)
            return None
    
    def list_conversations(self, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM conversations ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (limit, offset)
            ).fetchall()
            return [self._row_to_dict(row) for row in rows]
    
    def update_conversation(self, conversation_id: str, title: Optional[str] = None, metadata: Optional[Dict] = None) -> bool:
        with self._get_connection() as conn:
            now = datetime.now().isoformat()
            if title is not None:
                conn.execute(
                    "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
                    (title, now, conversation_id)
                )
            if metadata is not None:
                conn.execute(
                    "UPDATE conversations SET metadata = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(metadata), now, conversation_id)
                )
            return True
    
    def delete_conversation(self, conversation_id: str) -> bool:
        with self._get_connection() as conn:
            conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
            return True
    
    def add_message(self, conversation_id: str, role: str, content: str, metadata: Optional[Dict] = None) -> int:
        with self._get_connection() as conn:
            now = datetime.now().isoformat()
            cursor = conn.execute(
                "INSERT INTO messages (conversation_id, role, content, created_at, metadata) VALUES (?, ?, ?, ?, ?)",
                (conversation_id, role, content, now, json.dumps(metadata) if metadata else None)
            )
            message_id = cursor.lastrowid
            
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now, conversation_id)
            )
            
            return message_id
    
    def get_messages(self, conversation_id: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            if limit:
                rows = conn.execute(
                    "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at ASC LIMIT ?",
                    (conversation_id, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at ASC",
                    (conversation_id,)
                ).fetchall()
            return [self._row_to_dict(row) for row in rows]
    
    def clear_messages(self, conversation_id: str) -> bool:
        with self._get_connection() as conn:
            conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
            now = datetime.now().isoformat()
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now, conversation_id)
            )
            return True
    
    def search_messages(self, query: str, conversation_id: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
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
                        (query, conversation_id, limit)
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT m.* FROM messages m
                        JOIN messages_fts fts ON m.id = fts.rowid
                        WHERE messages_fts MATCH ?
                        ORDER BY m.created_at DESC LIMIT ?
                        """,
                        (query, limit)
                    ).fetchall()
                return [self._row_to_dict(row) for row in rows]
            except sqlite3.OperationalError:
                rows = conn.execute(
                    "SELECT * FROM messages WHERE content LIKE ? ORDER BY created_at DESC LIMIT ?",
                    (f"%{query}%", limit)
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
                
                first_user_msg = next((m for m in messages if m.get("role") == "user"), None)
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
                
                for i, msg in enumerate(messages[existing_count:], start=existing_count):
                    self.add_message(
                        conversation_id,
                        msg.get("role", "user"),
                        msg.get("content", ""),
                        msg.get("metadata")
                    )
                
                migrated += 1
                
            except Exception as e:
                print(f"迁移 {filename} 失败: {e}")
        
        return migrated
