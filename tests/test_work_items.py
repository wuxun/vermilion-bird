import sqlite3

import pytest

from llm_chat.runtime import RecoveryPolicy, Run, RunManager, RunStatus, RunType
from llm_chat.storage import Storage
from llm_chat.work import (
    ArtifactKind,
    WorkItem,
    WorkItemKind,
    WorkItemService,
    WorkItemStatus,
)


@pytest.fixture
def storage(tmp_path):
    Storage.set_instance(None)
    instance = Storage(str(tmp_path / "work-items.db"))
    yield instance
    Storage.set_instance(None)


def test_work_item_repository_round_trip_and_idempotency(storage):
    runs = RunManager(repository=storage)
    service = WorkItemService(repository=storage, runs=runs)

    created = service.create(
        title="架构调研",
        objective="调研三个执行框架并形成报告",
        kind=WorkItemKind.TASK,
        conversation_id="conversation-1",
        workspace="/workspace/project",
        idempotency_key="research:frameworks",
        metadata={"source": "test"},
    )
    duplicate = service.create(
        objective="不会覆盖原任务",
        idempotency_key="research:frameworks",
    )
    restored = storage.get_work_item(created.id)

    assert duplicate.id == created.id
    assert restored.title == "架构调研"
    assert restored.objective == "调研三个执行框架并形成报告"
    assert restored.kind == WorkItemKind.TASK
    assert restored.metadata == {"source": "test"}
    assert storage.list_work_items(kind=WorkItemKind.TASK) == [restored]


def test_work_item_tracks_primary_run_and_artifacts(storage):
    runs = RunManager(repository=storage)
    service = WorkItemService(repository=storage, runs=runs)
    item = service.create(objective="生成架构报告")

    run = service.start(
        item.id,
        run_type=RunType.WORKFLOW,
        recovery_policy=RecoveryPolicy.RESUME,
        max_attempts=2,
    )
    child = runs.start(
        RunType.TOOL,
        parent_run_id=run.id,
        input={"tool": "write_file"},
    )
    artifact = service.add_artifact(
        item.id,
        run_id=child.id,
        kind=ArtifactKind.REPORT,
        name="architecture-report.md",
        uri="/workspace/architecture-report.md",
        content="# Architecture",
        checksum="sha256:test",
        idempotency_key=f"{child.id}:report",
    )
    duplicate_artifact = service.add_artifact(
        item.id,
        run_id=child.id,
        name="不会重复创建",
        idempotency_key=f"{child.id}:report",
    )
    runs.complete(child.id, {"path": artifact.uri})
    runs.complete(run.id, {"artifact_id": artifact.id})
    detail = service.detail(item.id)

    assert child.work_item_id == item.id
    assert detail.work_item.status == WorkItemStatus.COMPLETED
    assert detail.work_item.root_run_id == run.id
    assert detail.work_item.latest_run_id == run.id
    assert {candidate.id for candidate in detail.runs} == {run.id, child.id}
    assert detail.artifacts == [artifact]
    assert duplicate_artifact.id == artifact.id
    assert detail.artifacts[0].content == "# Architecture"


def test_only_primary_run_projects_work_item_status(storage):
    runs = RunManager(repository=storage)
    service = WorkItemService(repository=storage, runs=runs)
    item = service.create(objective="运行带子任务的工作流")
    root = service.start(item.id)
    child = runs.start(RunType.TOOL, parent_run_id=root.id)

    runs.fail(child.id, "子任务失败但主流程会处理")
    assert service.get(item.id).status == WorkItemStatus.RUNNING

    runs.fail(root.id, "主流程失败")
    assert service.get(item.id).status == WorkItemStatus.FAILED


def test_new_root_run_becomes_latest_work_item_execution(storage):
    runs = RunManager(repository=storage)
    service = WorkItemService(repository=storage, runs=runs)
    item = service.create(objective="允许新的执行尝试")
    first = service.start(item.id)
    runs.complete(first.id, "first")

    second = runs.start(RunType.WORKFLOW, work_item_id=item.id)

    restored = service.get(item.id)
    assert restored.root_run_id == first.id
    assert restored.latest_run_id == second.id
    assert restored.status == WorkItemStatus.RUNNING


def test_artifact_rejects_run_from_another_work_item(storage):
    runs = RunManager(repository=storage)
    service = WorkItemService(repository=storage, runs=runs)
    first = service.create(objective="任务一")
    second = service.create(objective="任务二")
    run = service.start(first.id)

    with pytest.raises(ValueError, match="does not belong"):
        service.add_artifact(
            second.id,
            run_id=run.id,
            name="wrong.txt",
        )


def test_restart_reconciles_work_item_from_recovered_run(storage):
    first_runs = RunManager(repository=storage)
    first_service = WorkItemService(repository=storage, runs=first_runs)
    item = first_service.create(objective="可恢复任务")
    run = first_service.start(
        item.id,
        recovery_policy=RecoveryPolicy.FAIL,
    )
    first_service.close()

    restored_runs = RunManager(repository=storage)
    restored_service = WorkItemService(repository=storage, runs=restored_runs)
    restored = restored_service.get(item.id)

    assert restored_runs.get(run.id).status == RunStatus.FAILED
    assert restored.status == WorkItemStatus.FAILED
    assert restored.completed_at is not None


def test_reconcile_repairs_crash_between_run_and_work_item_link(storage):
    runs = RunManager(repository=storage)
    item = WorkItem(title="崩溃窗口", objective="修复任务投影")
    assert storage.create_work_item(item) is True
    run = runs.start(
        RunType.WORKFLOW,
        work_item_id=item.id,
        recovery_policy=RecoveryPolicy.MANUAL,
    )

    service = WorkItemService(repository=storage, runs=runs)
    repaired = service.get(item.id)

    assert repaired.root_run_id == run.id
    assert repaired.latest_run_id == run.id
    assert repaired.status == WorkItemStatus.RUNNING


def test_existing_runtime_database_is_migrated_for_work_items(tmp_path):
    db_path = tmp_path / "legacy-runtime.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE runs (
                id TEXT PRIMARY KEY,
                parent_run_id TEXT,
                type TEXT NOT NULL,
                status TEXT NOT NULL,
                conversation_id TEXT,
                input_json TEXT NOT NULL DEFAULT '{}',
                result_json TEXT,
                error TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT
            )
            """
        )

    Storage.set_instance(None)
    migrated = Storage(str(db_path))
    with migrated._get_connection() as conn:
        run_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(runs)").fetchall()
        }
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    assert "work_item_id" in run_columns
    assert {"work_items", "artifacts"} <= tables
    Storage.set_instance(None)


def test_existing_artifact_table_gets_content_and_idempotency_columns(tmp_path):
    db_path = tmp_path / "legacy-artifacts.db"
    Storage.set_instance(None)
    initial = Storage(str(db_path))
    with initial._get_connection() as conn:
        conn.execute("DROP INDEX IF EXISTS idx_artifacts_idempotency")
        conn.execute("ALTER TABLE artifacts RENAME TO artifacts_old")
        conn.execute(
            """
            CREATE TABLE artifacts (
                id TEXT PRIMARY KEY,
                work_item_id TEXT NOT NULL,
                run_id TEXT,
                kind TEXT NOT NULL,
                name TEXT NOT NULL,
                uri TEXT,
                content_preview TEXT,
                checksum TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute("DROP TABLE artifacts_old")

    Storage.set_instance(None)
    migrated = Storage(str(db_path))
    with migrated._get_connection() as conn:
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(artifacts)").fetchall()
        }

    assert {"content", "idempotency_key"} <= columns
    Storage.set_instance(None)


def test_run_work_item_id_round_trip(storage):
    run = Run(
        id="run-with-work-item",
        work_item_id="work-existing",
        type=RunType.WORKFLOW,
        status=RunStatus.COMPLETED,
    )
    storage.save_run(run)

    restored = storage.get_run(run.id)

    assert restored.work_item_id == "work-existing"
