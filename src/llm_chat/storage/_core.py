"""Storage 核心基础设施：单例/连接管理/schema 初始化"""

import sqlite3
import json
import os
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List
from contextlib import contextmanager

from llm_chat.storage.migrations import (
    MigrationReport,
    SchemaMigration,
    SchemaMigrationError,
)

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
    DEFAULT_DB_PATH: str = os.path.expanduser("~/.vermilion-bird/vermilion_bird.db")
    _db_path: str = DEFAULT_DB_PATH
    CURRENT_SCHEMA_VERSION = 7

    def __new__(cls, db_path: Optional[str] = None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            if db_path:
                cls._db_path = db_path
        return cls._instance

    @classmethod
    def set_instance(cls, instance: Optional["StorageCore"]) -> None:
        """注入自定义实例（App 初始化 / 测试 mock）。"""
        cls._instance = instance
        if instance is None:
            cls._db_path = cls.DEFAULT_DB_PATH

    @classmethod
    def get_instance(cls) -> "StorageCore":
        return cls()

    def __init__(self, db_path: Optional[str] = None):
        if db_path:
            self._db_path = db_path
        self.last_migration_report = MigrationReport(
            from_version=self.CURRENT_SCHEMA_VERSION,
            to_version=self.CURRENT_SCHEMA_VERSION,
        )
        self._init_db()

    # ------------------------------------------------------------------
    # 连接管理
    # ------------------------------------------------------------------

    @contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        # foreign_keys is connection-scoped in SQLite. Setting it only during
        # schema initialization leaves every CRUD connection without cascade
        # enforcement.
        conn.execute("PRAGMA foreign_keys=ON")
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
        """按显式版本初始化或升级数据库，失败时恢复升级前备份。"""

        db_dir = os.path.dirname(self._db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        from_version, has_schema = self._inspect_schema()
        if from_version > self.CURRENT_SCHEMA_VERSION:
            raise RuntimeError(
                f"database schema {from_version} is newer than supported "
                f"{self.CURRENT_SCHEMA_VERSION}"
            )
        backup_path = None
        needs_repair = has_schema and self._schema_needs_repair()
        if has_schema and (from_version < self.CURRENT_SCHEMA_VERSION or needs_repair):
            backup_path = self._create_upgrade_backup(from_version)

        report = MigrationReport(
            from_version=from_version,
            to_version=from_version,
            backup_path=backup_path,
        )
        active_migration: Optional[SchemaMigration] = None
        try:
            with self._get_connection() as conn:
                self._create_schema_history_in(conn)
                for migration in self._schema_migrations():
                    if migration.version <= from_version:
                        continue
                    active_migration = migration
                    migration.apply(conn)
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO schema_migrations(
                            version, name, applied_at
                        ) VALUES (?, ?, ?)
                        """,
                        (
                            migration.version,
                            migration.name,
                            datetime.now(timezone.utc).isoformat(),
                        ),
                    )
                    conn.execute(f"PRAGMA user_version={migration.version}")
                    report.applied.append(migration.version)
                    report.to_version = migration.version
                self._validate_current_schema_in(conn)
                self._apply_pragmas_in(conn)
        except Exception as exc:
            if backup_path:
                self._restore_upgrade_backup(backup_path)
            self._write_migration_failure(active_migration, exc, backup_path)
            if active_migration is None:
                raise
            raise SchemaMigrationError(
                version=active_migration.version,
                name=active_migration.name,
                cause=exc,
                backup_path=backup_path,
            ) from exc
        self.last_migration_report = report

    def _schema_migrations(self) -> List[SchemaMigration]:
        return [
            SchemaMigration(1, "base_schema", self._migrate_base_schema),
            SchemaMigration(2, "durable_runtime", self._create_runtime_tables_in),
            SchemaMigration(3, "work_items_and_artifacts", self._create_work_tables_in),
            SchemaMigration(4, "cooperative_run_control", self._migrate_run_control),
            SchemaMigration(5, "plans_and_resource_grants", self._create_planning_tables_in),
            SchemaMigration(6, "artifact_feedback", self._create_artifact_feedback_table_in),
            SchemaMigration(7, "workflow_definitions", self._create_workflow_tables_in),
        ]

    def _migrate_base_schema(self, conn) -> None:
        self._create_conversations_table_in(conn)
        self._create_messages_table_in(conn)
        self._create_fts_index_in(conn)
        self._create_tasks_tables_in(conn)
        self._create_feishu_table_in(conn)
        self._create_context_cache_table_in(conn)
        self._create_decision_log_table_in(conn)
        self._create_digest_tables_in(conn)

    @staticmethod
    def _migrate_run_control(conn) -> None:
        # Run/WorkItem status 使用 TEXT，无需重建表；版本用于声明语义边界。
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_runs_work_item_status "
            "ON runs(work_item_id, status, created_at DESC)"
        )

    @staticmethod
    def _create_schema_history_in(conn) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """
        )

    def _inspect_schema(self) -> tuple[int, bool]:
        if self._db_path == ":memory:":
            return 0, False
        path = Path(self._db_path)
        if not path.exists() or path.stat().st_size == 0:
            return 0, False
        with sqlite3.connect(self._db_path) as conn:
            version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            has_schema = (
                conn.execute(
                    """
                    SELECT 1 FROM sqlite_master
                    WHERE type = 'table'
                      AND name NOT LIKE 'sqlite_%'
                    LIMIT 1
                    """
                ).fetchone()
                is not None
            )
        return version, has_schema

    def _schema_needs_repair(self) -> bool:
        required = {
            "messages": {"execution_key"},
            "runs": {
                "work_item_id",
                "checkpoint_json",
                "lease_owner",
                "lease_expires_at",
            },
            "action_proposals": {"execution_run_id"},
            "artifacts": {"content", "idempotency_key"},
            "plan_revisions": {"work_item_id", "version", "status"},
            "plan_steps": {"plan_revision_id", "position", "depends_on_json"},
            "resource_grants": {
                "capability",
                "resource_type",
                "resource",
                "scope",
                "status",
            },
            "artifact_feedback": {"artifact_id", "work_item_id", "decision"},
            "workflow_definitions": {"latest_version", "status"},
            "workflow_versions": {"workflow_id", "version", "objective_template"},
        }
        with sqlite3.connect(self._db_path) as conn:
            for table, columns in required.items():
                existing = {
                    row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
                }
                if not existing or not columns <= existing:
                    return True
        return False

    def _validate_current_schema_in(self, conn) -> None:
        """幂等修复历史版本曾支持的列漂移，并重建关键索引。"""

        self._create_conversations_table_in(conn)
        self._create_messages_table_in(conn)
        self._create_tasks_tables_in(conn)
        self._create_decision_log_table_in(conn)
        self._create_runtime_tables_in(conn)
        self._create_work_tables_in(conn)
        self._create_planning_tables_in(conn)
        self._create_artifact_feedback_table_in(conn)
        self._create_workflow_tables_in(conn)
        self._migrate_run_control(conn)

    def _create_upgrade_backup(self, from_version: int) -> str:
        return self.create_backup(label=f"v{from_version}")

    def create_backup(self, *, label: str = "manual") -> str:
        """使用 SQLite backup API 创建 WAL 一致的可恢复副本。"""

        if self._db_path == ":memory:":
            raise ValueError("in-memory database cannot be backed up")
        source = Path(self._db_path)
        backup_dir = source.parent / f"{source.name}.backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        safe_label = (
            "".join(
                character for character in label if character.isalnum() or character in {"-", "_"}
            )[:40]
            or "manual"
        )
        target = backup_dir / (f"{source.stem}-{safe_label}-{timestamp}{source.suffix or '.db'}")
        with sqlite3.connect(self._db_path) as source_conn:
            with sqlite3.connect(str(target)) as target_conn:
                source_conn.backup(target_conn)
        return str(target)

    def verify_integrity(self) -> Dict[str, Any]:
        with self._get_connection() as conn:
            integrity_rows = [row[0] for row in conn.execute("PRAGMA integrity_check").fetchall()]
            foreign_key_rows = [
                tuple(row) for row in conn.execute("PRAGMA foreign_key_check").fetchall()
            ]
        return {
            "ok": integrity_rows == ["ok"] and not foreign_key_rows,
            "integrity": integrity_rows,
            "foreign_key_violations": foreign_key_rows,
        }

    def _restore_upgrade_backup(self, backup_path: str) -> None:
        with sqlite3.connect(backup_path) as source_conn:
            with sqlite3.connect(self._db_path) as target_conn:
                source_conn.backup(target_conn)

    def _write_migration_failure(
        self,
        migration: Optional[SchemaMigration],
        error: Exception,
        backup_path: Optional[str],
    ) -> None:
        if self._db_path == ":memory:":
            return
        failure_path = Path(f"{self._db_path}.migration-failure.json")
        payload = {
            "failed_at": datetime.now(timezone.utc).isoformat(),
            "version": migration.version if migration else None,
            "name": migration.name if migration else None,
            "error": str(error),
            "backup_path": backup_path,
        }
        temporary = failure_path.with_suffix(f"{failure_path.suffix}.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(failure_path)

    def get_schema_info(self) -> Dict[str, Any]:
        with self._get_connection() as conn:
            version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            rows = conn.execute(
                """
                SELECT version, name, applied_at
                FROM schema_migrations
                ORDER BY version
                """
            ).fetchall()
        return {
            "current_version": version,
            "supported_version": self.CURRENT_SCHEMA_VERSION,
            "migrations": [dict(row) for row in rows],
            "last_report": {
                "from_version": self.last_migration_report.from_version,
                "to_version": self.last_migration_report.to_version,
                "applied": list(self.last_migration_report.applied),
                "backup_path": self.last_migration_report.backup_path,
            },
        }

    def _create_conversations_table_in(self, conn):
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                metadata TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_conversations_updated_at
                ON conversations(updated_at);
        """
        )

    def _create_messages_table_in(self, conn):
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                metadata TEXT,
                execution_key TEXT,
                FOREIGN KEY (conversation_id)
                    REFERENCES conversations(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_messages_conversation_id
                ON messages(conversation_id);
            CREATE INDEX IF NOT EXISTS idx_messages_created_at
                ON messages(created_at);
        """
        )
        columns = {
            row["name"] if isinstance(row, sqlite3.Row) else row[1]
            for row in conn.execute("PRAGMA table_info(messages)").fetchall()
        }
        if "execution_key" not in columns:
            conn.execute("ALTER TABLE messages ADD COLUMN execution_key TEXT")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_execution_key "
            "ON messages(execution_key) WHERE execution_key IS NOT NULL"
        )

    def _create_fts_index_in(self, conn):
        try:
            conn.executescript(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                    content,
                    content='messages',
                    content_rowid='id'
                );

                CREATE TRIGGER IF NOT EXISTS messages_fts_ai
                AFTER INSERT ON messages BEGIN
                    INSERT INTO messages_fts(rowid, content)
                    VALUES (new.id, new.content);
                END;

                CREATE TRIGGER IF NOT EXISTS messages_fts_ad
                AFTER DELETE ON messages BEGIN
                    INSERT INTO messages_fts(messages_fts, rowid, content)
                    VALUES ('delete', old.id, old.content);
                END;

                CREATE TRIGGER IF NOT EXISTS messages_fts_au
                AFTER UPDATE OF content ON messages BEGIN
                    INSERT INTO messages_fts(messages_fts, rowid, content)
                    VALUES ('delete', old.id, old.content);
                    INSERT INTO messages_fts(rowid, content)
                    VALUES (new.id, new.content);
                END;
            """
            )
            # Repair databases created before the synchronization triggers
            # existed. FTS5 rebuild is idempotent.
            conn.execute("INSERT INTO messages_fts(messages_fts) VALUES ('rebuild')")
        except sqlite3.OperationalError:
            pass

    def _apply_pragmas_in(self, conn):
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")

    def _create_tasks_tables_in(self, conn):
        conn.executescript(
            """
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
        """
        )
        self._migrate_tasks_columns(conn)
        self._migrate_decision_log_columns(conn)

    def _migrate_tasks_columns(self, conn):
        cursor = conn.execute("PRAGMA table_info(tasks)")
        columns = [row[1] for row in cursor.fetchall()]

        def add_if_missing(col_name, col_def):
            if col_name not in columns:
                try:
                    conn.execute(f"ALTER TABLE tasks ADD COLUMN {col_name} {col_def}")
                except sqlite3.OperationalError:
                    pass

        add_if_missing("notify_enabled", "INTEGER DEFAULT 1")
        add_if_missing("notify_targets", "TEXT")
        add_if_missing("notify_on_success", "INTEGER DEFAULT 1")
        add_if_missing("notify_on_failure", "INTEGER DEFAULT 1")

    def _migrate_decision_log_columns(self, conn):
        """为旧 decision_log 表添加新列（灰度兼容）。"""
        cursor = conn.execute("PRAGMA table_info(decision_log)")
        columns = [row[1] for row in cursor.fetchall()]

        def add_if_missing(col_name, col_def):
            if col_name not in columns:
                try:
                    conn.execute(f"ALTER TABLE decision_log ADD COLUMN {col_name} {col_def}")
                except sqlite3.OperationalError:
                    pass

        add_if_missing("execution_result", "TEXT")
        add_if_missing("executed_at", "TIMESTAMP")

    def _create_feishu_table_in(self, conn):
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS recent_feishu_chat (
                id INTEGER PRIMARY KEY,
                chat_id TEXT NOT NULL,
                chat_id_type TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        )

    def _create_context_cache_table_in(self, conn):
        conn.execute(
            """
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
        """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_context_conversation_id "
            "ON context_cache(conversation_id)"
        )

    def _create_decision_log_table_in(self, conn):
        conn.executescript(
            """
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
            CREATE INDEX IF NOT EXISTS idx_decision_log_card_id
                ON decision_log(card_id);
            CREATE INDEX IF NOT EXISTS idx_decision_log_created_at
                ON decision_log(created_at);
        """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_context_last_accessed "
            "ON context_cache(last_accessed)"
        )

    def _create_digest_tables_in(self, conn):
        """Create daily_digest table for scheduled task output recording.

        Supports multiple tasks per day via (date, source) composite key.
        Migrates from old schema (date UNIQUE alone) if needed.
        """
        # Check if old schema exists (date UNIQUE, no source column)
        cursor = conn.execute("PRAGMA table_info(daily_digest)")
        columns = {row[1] for row in cursor.fetchall()}

        if not columns:
            # Fresh install — create with correct schema
            conn.executescript(
                """
                CREATE TABLE daily_digest (
                    id TEXT PRIMARY KEY,
                    date TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT '',
                    items_json TEXT NOT NULL,
                    raw_context_json TEXT DEFAULT '{}',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(date, source)
                );
                CREATE INDEX IF NOT EXISTS idx_daily_digest_date
                    ON daily_digest(date);
                CREATE INDEX IF NOT EXISTS idx_daily_digest_source
                    ON daily_digest(source);
            """
            )
            return

        if "source" not in columns:
            # Migrate: add source column, remove old UNIQUE on date
            logger.info("Migrating daily_digest schema: adding source column")
            conn.executescript(
                """
                ALTER TABLE daily_digest ADD COLUMN source TEXT NOT NULL DEFAULT '';
                CREATE TABLE daily_digest_new (
                    id TEXT PRIMARY KEY,
                    date TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT '',
                    items_json TEXT NOT NULL,
                    raw_context_json TEXT DEFAULT '{}',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(date, source)
                );
                INSERT INTO daily_digest_new
                    SELECT id, date, source, items_json, raw_context_json, created_at
                    FROM daily_digest;
                DROP TABLE daily_digest;
                ALTER TABLE daily_digest_new RENAME TO daily_digest;
                CREATE INDEX IF NOT EXISTS idx_daily_digest_date
                    ON daily_digest(date);
                CREATE INDEX IF NOT EXISTS idx_daily_digest_source
                    ON daily_digest(source);
            """
            )
            logger.info("daily_digest migration complete")

    def _create_runtime_tables_in(self, conn):
        """创建跨会话保留的运行与动作审批表。"""

        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                parent_run_id TEXT,
                work_item_id TEXT,
                type TEXT NOT NULL,
                status TEXT NOT NULL,
                conversation_id TEXT,
                input_json TEXT NOT NULL DEFAULT '{}',
                result_json TEXT,
                error TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                attempt INTEGER NOT NULL DEFAULT 1,
                max_attempts INTEGER NOT NULL DEFAULT 1,
                idempotency_key TEXT,
                recovery_policy TEXT NOT NULL DEFAULT 'fail',
                checkpoint_json TEXT,
                heartbeat_at TEXT,
                lease_owner TEXT,
                lease_expires_at TEXT,
                created_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_runs_status_created
                ON runs(status, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_runs_type_created
                ON runs(type, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_runs_parent
                ON runs(parent_run_id);
            CREATE INDEX IF NOT EXISTS idx_runs_conversation
                ON runs(conversation_id, created_at DESC);

            CREATE TABLE IF NOT EXISTS run_events (
                run_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                type TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                data_json TEXT NOT NULL DEFAULT '{}',
                PRIMARY KEY (run_id, sequence),
                FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS action_proposals (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                execution_run_id TEXT,
                conversation_id TEXT,
                tool_name TEXT NOT NULL,
                arguments_json TEXT NOT NULL DEFAULT '{}',
                capabilities_json TEXT NOT NULL DEFAULT '[]',
                reason TEXT NOT NULL DEFAULT '',
                impact TEXT NOT NULL DEFAULT '',
                risk TEXT NOT NULL DEFAULT 'medium',
                reversible INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                decided_at TEXT,
                finished_at TEXT,
                result_json TEXT,
                error TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_action_proposals_status_created
                ON action_proposals(status, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_action_proposals_run
                ON action_proposals(run_id);
            CREATE INDEX IF NOT EXISTS idx_action_proposals_conversation
                ON action_proposals(conversation_id, created_at DESC);

            CREATE TABLE IF NOT EXISTS effect_outbox (
                id TEXT PRIMARY KEY,
                effect_key TEXT NOT NULL UNIQUE,
                run_id TEXT,
                kind TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL,
                retry_safe INTEGER NOT NULL DEFAULT 0,
                attempts INTEGER NOT NULL DEFAULT 0,
                result_json TEXT,
                error TEXT,
                resolution TEXT,
                reconciliation_note TEXT,
                reconciled_by TEXT,
                reconciled_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                finished_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_effect_outbox_status_updated
                ON effect_outbox(status, updated_at);
            CREATE INDEX IF NOT EXISTS idx_effect_outbox_run
                ON effect_outbox(run_id);
        """
        )
        self._migrate_runtime_columns(conn)

    def _migrate_runtime_columns(self, conn):
        """为已有运行时表增量补齐恢复控制字段。"""

        columns = {row[1] for row in conn.execute("PRAGMA table_info(runs)").fetchall()}
        additions = {
            "work_item_id": "TEXT",
            "attempt": "INTEGER NOT NULL DEFAULT 1",
            "max_attempts": "INTEGER NOT NULL DEFAULT 1",
            "idempotency_key": "TEXT",
            "recovery_policy": "TEXT NOT NULL DEFAULT 'fail'",
            "checkpoint_json": "TEXT",
            "heartbeat_at": "TEXT",
            "lease_owner": "TEXT",
            "lease_expires_at": "TEXT",
        }
        for name, definition in additions.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE runs ADD COLUMN {name} {definition}")
        action_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(action_proposals)").fetchall()
        }
        if "execution_run_id" not in action_columns:
            conn.execute("ALTER TABLE action_proposals ADD COLUMN execution_run_id TEXT")
        effect_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(effect_outbox)").fetchall()
        }
        effect_additions = {
            "resolution": "TEXT",
            "reconciliation_note": "TEXT",
            "reconciled_by": "TEXT",
            "reconciled_at": "TEXT",
        }
        for name, definition in effect_additions.items():
            if name not in effect_columns:
                conn.execute(f"ALTER TABLE effect_outbox ADD COLUMN {name} {definition}")
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_runs_idempotency_key
            ON runs(idempotency_key)
            WHERE idempotency_key IS NOT NULL
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_runs_lease
            ON runs(status, lease_expires_at)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_runs_work_item
            ON runs(work_item_id, created_at DESC)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_action_proposals_execution_run
            ON action_proposals(execution_run_id)
            """
        )

    def _create_work_tables_in(self, conn):
        """创建产品级用户任务与交付物表。"""

        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS work_items (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                objective TEXT NOT NULL,
                kind TEXT NOT NULL,
                status TEXT NOT NULL,
                conversation_id TEXT,
                workflow_id TEXT,
                workspace TEXT,
                root_run_id TEXT,
                latest_run_id TEXT,
                idempotency_key TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_work_items_idempotency
                ON work_items(idempotency_key)
                WHERE idempotency_key IS NOT NULL;
            CREATE INDEX IF NOT EXISTS idx_work_items_status_updated
                ON work_items(status, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_work_items_kind_updated
                ON work_items(kind, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_work_items_conversation
                ON work_items(conversation_id, updated_at DESC);

            CREATE TABLE IF NOT EXISTS artifacts (
                id TEXT PRIMARY KEY,
                work_item_id TEXT NOT NULL,
                run_id TEXT,
                kind TEXT NOT NULL,
                name TEXT NOT NULL,
                uri TEXT,
                content TEXT,
                content_preview TEXT,
                checksum TEXT,
                idempotency_key TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                FOREIGN KEY (work_item_id)
                    REFERENCES work_items(id) ON DELETE CASCADE,
                FOREIGN KEY (run_id)
                    REFERENCES runs(id) ON DELETE SET NULL
            );
            CREATE INDEX IF NOT EXISTS idx_artifacts_work_item_created
                ON artifacts(work_item_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_artifacts_run
                ON artifacts(run_id);
            """
        )
        artifact_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(artifacts)").fetchall()
        }
        if "content" not in artifact_columns:
            conn.execute("ALTER TABLE artifacts ADD COLUMN content TEXT")
        if "idempotency_key" not in artifact_columns:
            conn.execute("ALTER TABLE artifacts ADD COLUMN idempotency_key TEXT")
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_artifacts_idempotency
            ON artifacts(idempotency_key)
            WHERE idempotency_key IS NOT NULL
            """
        )

    @staticmethod
    def _create_planning_tables_in(conn):
        """创建版本化计划与资源级授权表。"""

        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS plan_revisions (
                id TEXT PRIMARY KEY,
                work_item_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                summary TEXT NOT NULL,
                status TEXT NOT NULL,
                change_summary TEXT NOT NULL DEFAULT '',
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                approved_at TEXT,
                UNIQUE(work_item_id, version),
                FOREIGN KEY (work_item_id)
                    REFERENCES work_items(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_plan_revisions_work_version
                ON plan_revisions(work_item_id, version DESC);
            CREATE INDEX IF NOT EXISTS idx_plan_revisions_status
                ON plan_revisions(status, created_at DESC);

            CREATE TABLE IF NOT EXISTS plan_steps (
                id TEXT PRIMARY KEY,
                plan_revision_id TEXT NOT NULL,
                position INTEGER NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                depends_on_json TEXT NOT NULL DEFAULT '[]',
                expected_artifact_kind TEXT,
                required_capabilities_json TEXT NOT NULL DEFAULT '[]',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                UNIQUE(plan_revision_id, position),
                FOREIGN KEY (plan_revision_id)
                    REFERENCES plan_revisions(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_plan_steps_revision
                ON plan_steps(plan_revision_id, position);

            CREATE TABLE IF NOT EXISTS resource_grants (
                id TEXT PRIMARY KEY,
                work_item_id TEXT,
                workflow_id TEXT,
                capability TEXT NOT NULL,
                resource_type TEXT NOT NULL,
                resource TEXT NOT NULL,
                scope TEXT NOT NULL,
                status TEXT NOT NULL,
                created_by TEXT NOT NULL,
                reason TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                expires_at TEXT,
                revoked_at TEXT,
                last_used_at TEXT,
                FOREIGN KEY (work_item_id)
                    REFERENCES work_items(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_resource_grants_work_item
                ON resource_grants(work_item_id, status, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_resource_grants_workflow
                ON resource_grants(workflow_id, status, created_at DESC);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_resource_grants_active_boundary
                ON resource_grants(
                    IFNULL(work_item_id, ''),
                    IFNULL(workflow_id, ''),
                    capability,
                    resource_type,
                    resource,
                    scope
                )
                WHERE status = 'active';
            """
        )

    @staticmethod
    def _create_artifact_feedback_table_in(conn):
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS artifact_feedback (
                id TEXT PRIMARY KEY,
                artifact_id TEXT NOT NULL,
                work_item_id TEXT NOT NULL,
                decision TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (artifact_id)
                    REFERENCES artifacts(id) ON DELETE CASCADE,
                FOREIGN KEY (work_item_id)
                    REFERENCES work_items(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_artifact_feedback_work
                ON artifact_feedback(work_item_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_artifact_feedback_artifact
                ON artifact_feedback(artifact_id, created_at DESC);
            """
        )

    @staticmethod
    def _create_workflow_tables_in(conn):
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS workflow_definitions (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                latest_version INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_workflow_definitions_status
                ON workflow_definitions(status, updated_at DESC);

            CREATE TABLE IF NOT EXISTS workflow_versions (
                id TEXT PRIMARY KEY,
                workflow_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                objective_template TEXT NOT NULL,
                parameters_json TEXT NOT NULL DEFAULT '[]',
                plan_steps_json TEXT NOT NULL DEFAULT '[]',
                expected_artifact_kinds_json TEXT NOT NULL DEFAULT '[]',
                required_resources_json TEXT NOT NULL DEFAULT '[]',
                budget_json TEXT NOT NULL DEFAULT '{}',
                approval_policy_json TEXT NOT NULL DEFAULT '{}',
                failure_policy_json TEXT NOT NULL DEFAULT '{}',
                source_work_item_id TEXT,
                change_summary TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                UNIQUE(workflow_id, version),
                FOREIGN KEY (workflow_id)
                    REFERENCES workflow_definitions(id) ON DELETE CASCADE,
                FOREIGN KEY (source_work_item_id)
                    REFERENCES work_items(id) ON DELETE SET NULL
            );
            CREATE INDEX IF NOT EXISTS idx_workflow_versions_definition
                ON workflow_versions(workflow_id, version DESC);
            """
        )
