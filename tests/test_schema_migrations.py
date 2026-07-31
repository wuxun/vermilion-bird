import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from llm_chat.cli import cli
from llm_chat.storage import Storage
from llm_chat.storage._core import StorageCore
from llm_chat.storage.migrations import SchemaMigration, SchemaMigrationError


@pytest.fixture(autouse=True)
def reset_storage():
    Storage.set_instance(None)
    yield
    Storage.set_instance(None)


def test_fresh_database_records_all_schema_versions(tmp_path):
    storage = Storage(str(tmp_path / "fresh.db"))

    info = storage.get_schema_info()

    assert info["current_version"] == Storage.CURRENT_SCHEMA_VERSION
    assert [item["version"] for item in info["migrations"]] == list(
        range(1, Storage.CURRENT_SCHEMA_VERSION + 1)
    )
    assert info["last_report"]["from_version"] == 0
    assert info["last_report"]["applied"] == list(range(1, Storage.CURRENT_SCHEMA_VERSION + 1))
    assert info["last_report"]["backup_path"] is None
    assert storage.verify_integrity()["ok"] is True


def test_legacy_database_is_backed_up_and_upgraded_without_data_loss(tmp_path):
    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE conversations("
            "id TEXT PRIMARY KEY, title TEXT, created_at TEXT, "
            "updated_at TEXT, metadata TEXT)"
        )
        conn.execute("INSERT INTO conversations(id, title) VALUES ('legacy', '保留数据')")

    storage = Storage(str(db_path))
    report = storage.last_migration_report

    assert report.from_version == 0
    assert report.to_version == Storage.CURRENT_SCHEMA_VERSION
    assert report.backup_path is not None
    assert Path(report.backup_path).exists()
    with sqlite3.connect(db_path) as conn:
        assert (
            conn.execute("SELECT title FROM conversations WHERE id = 'legacy'").fetchone()[0]
            == "保留数据"
        )
        assert conn.execute("PRAGMA user_version").fetchone()[0] == Storage.CURRENT_SCHEMA_VERSION


def test_v7_scheduler_items_gain_series_and_optional_review_policy(tmp_path):
    db_path = tmp_path / "v7-automation.db"
    Storage(str(db_path))
    Storage.set_instance(None)
    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP INDEX idx_work_items_series_key")
        conn.execute("ALTER TABLE work_items DROP COLUMN series_key")
        conn.execute("ALTER TABLE work_items DROP COLUMN artifact_review_policy")
        rows = [
            (
                "work_old",
                "每日摘要",
                "生成摘要",
                "automation",
                "completed",
                '{"source":"scheduler","scheduled_task_id":"daily"}',
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
            ),
            (
                "work_latest",
                "每日摘要",
                "生成摘要",
                "automation",
                "completed",
                '{"source":"scheduler","scheduled_task_id":"daily"}',
                "2026-01-02T00:00:00+00:00",
                "2026-01-02T00:00:00+00:00",
            ),
        ]
        conn.executemany(
            """
            INSERT INTO work_items(
                id, title, objective, kind, status, metadata_json,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.execute("PRAGMA user_version=7")

    storage = Storage(str(db_path))

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        restored = conn.execute(
            """
            SELECT id, series_key, artifact_review_policy
            FROM work_items
            ORDER BY updated_at DESC
            """
        ).fetchall()
        assert restored[0]["id"] == "work_latest"
        assert restored[0]["series_key"] == "scheduler:daily"
        assert restored[1]["series_key"] is None
        assert {row["artifact_review_policy"] for row in restored} == {"optional"}
        assert (
            conn.execute("PRAGMA user_version").fetchone()[0]
            == Storage.CURRENT_SCHEMA_VERSION
        )
    assert storage.get_work_item_by_series_key("scheduler:daily").id == "work_latest"


def test_failed_migration_restores_upgrade_backup_and_writes_diagnostic(
    tmp_path,
    monkeypatch,
):
    db_path = tmp_path / "rollback.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE sentinel(value TEXT)")
        conn.execute("INSERT INTO sentinel VALUES ('original')")

    original_registry = StorageCore._schema_migrations

    def failing_registry(self):
        def fail(conn):
            conn.execute("CREATE TABLE partial_change(value TEXT)")
            raise RuntimeError("injected migration failure")

        return [
            *original_registry(self),
            SchemaMigration(5, "injected_failure", fail),
        ]

    monkeypatch.setattr(StorageCore, "CURRENT_SCHEMA_VERSION", 5)
    monkeypatch.setattr(StorageCore, "_schema_migrations", failing_registry)

    with pytest.raises(SchemaMigrationError, match="injected_failure"):
        Storage(str(db_path))

    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT value FROM sentinel").fetchone()[0] == "original"
        assert (
            conn.execute("SELECT name FROM sqlite_master WHERE name = 'partial_change'").fetchone()
            is None
        )
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
    diagnostic = Path(f"{db_path}.migration-failure.json")
    assert diagnostic.exists()
    assert json.loads(diagnostic.read_text(encoding="utf-8"))["version"] == 5


def test_newer_database_version_is_rejected_before_mutation(tmp_path):
    db_path = tmp_path / "future.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE future_data(value TEXT)")
        conn.execute("PRAGMA user_version=999")

    with pytest.raises(RuntimeError, match="newer than supported"):
        Storage(str(db_path))

    with sqlite3.connect(db_path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 999


def test_database_cli_reports_version_and_creates_backup(tmp_path):
    db_path = tmp_path / "cli.db"
    Storage(str(db_path))
    Storage.set_instance(None)

    with patch.dict("os.environ", {"VB_DB_PATH": str(db_path)}):
        status = CliRunner().invoke(cli, ["database", "status", "--json-output"])
        backup = CliRunner().invoke(
            cli,
            ["database", "backup", "--label", "before-test"],
        )

    assert status.exit_code == 0
    assert f'"current_version": {Storage.CURRENT_SCHEMA_VERSION}' in status.output
    assert backup.exit_code == 0
    assert Path(backup.output.strip()).exists()
