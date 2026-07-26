import sqlite3

import pytest

from llm_chat.runtime import (
    ActionProposalManager,
    ActionStatus,
    Capability,
    EffectOutbox,
    EffectRecord,
    EffectReconciliationService,
    EffectResolution,
    EffectStatus,
    RunManager,
    RunStatus,
    RunType,
    UncertainEffectError,
)
from llm_chat.storage import Storage


@pytest.fixture
def storage(tmp_path):
    Storage.set_instance(None)
    instance = Storage(str(tmp_path / "effects.db"))
    yield instance
    Storage.set_instance(None)


def test_completed_effect_returns_saved_result_without_reexecution(storage):
    outbox = EffectOutbox(storage)
    outbox.prepare(
        effect_key="action:1",
        kind="tool",
        payload={"path": "report.md"},
    )
    calls = []

    first = outbox.execute(
        effect_key="action:1",
        executor=lambda: calls.append("called") or "done",
    )
    repeated = outbox.execute(
        effect_key="action:1",
        executor=lambda: calls.append("duplicate") or "wrong",
    )

    assert first.status == EffectStatus.COMPLETED
    assert repeated.result == "done"
    assert calls == ["called"]


def test_interrupted_effect_becomes_uncertain_and_cannot_auto_retry(storage):
    storage.create_effect(
        EffectRecord(
            effect_key="action:uncertain",
            kind="external_message",
            status=EffectStatus.EXECUTING,
            attempts=1,
        )
    )
    outbox = EffectOutbox(storage)

    reconciled = outbox.reconcile_interrupted()

    assert [item.effect_key for item in reconciled] == ["action:uncertain"]
    assert storage.get_effect("action:uncertain").status == EffectStatus.UNCERTAIN
    with pytest.raises(UncertainEffectError):
        outbox.execute(
            effect_key="action:uncertain",
            executor=lambda: "must not run",
        )


def test_failed_retry_safe_effect_can_run_again(storage):
    outbox = EffectOutbox(storage)
    outbox.prepare(
        effect_key="cache:1",
        kind="cache_write",
        payload={},
        retry_safe=True,
    )
    with pytest.raises(RuntimeError):
        outbox.execute(
            effect_key="cache:1",
            executor=lambda: (_ for _ in ()).throw(RuntimeError("temporary")),
        )

    completed = outbox.execute(
        effect_key="cache:1",
        executor=lambda: {"ok": True},
    )

    assert completed.status == EffectStatus.COMPLETED
    assert completed.attempts == 2


def test_uncertain_resolution_is_persisted_with_audit_fields(storage):
    outbox = EffectOutbox(storage)
    storage.create_effect(
        EffectRecord(
            effect_key="message:1",
            kind="external_message",
            status=EffectStatus.UNCERTAIN,
        )
    )

    resolved = outbox.resolve_uncertain(
        effect_key="message:1",
        resolution=EffectResolution.SUCCEEDED,
        note="已在外部系统核对消息 ID",
        result={"message_id": "m-1"},
        actor="tester",
    )
    restored = storage.get_effect("message:1")

    assert resolved.status == EffectStatus.COMPLETED
    assert restored.resolution == EffectResolution.SUCCEEDED
    assert restored.reconciliation_note == "已在外部系统核对消息 ID"
    assert restored.reconciled_by == "tester"
    assert restored.reconciled_at is not None


def test_unsafe_uncertain_effect_cannot_be_approved_for_retry(storage):
    outbox = EffectOutbox(storage)
    storage.create_effect(
        EffectRecord(
            effect_key="shell:1",
            kind="tool",
            status=EffectStatus.UNCERTAIN,
            retry_safe=False,
        )
    )

    with pytest.raises(ValueError, match="not declared safe"):
        outbox.resolve_uncertain(
            effect_key="shell:1",
            resolution=EffectResolution.RETRY_APPROVED,
            note="想要重试",
        )


def test_reconciliation_service_aligns_effect_action_and_run(storage):
    runs = RunManager(repository=storage)
    proposals = ActionProposalManager(repository=storage)
    run = runs.start(RunType.TOOL)
    proposal = proposals.propose(
        run_id=run.id,
        tool_name="write_file",
        arguments={"path": "report.md"},
        capabilities={Capability.WORKSPACE_WRITE},
    )
    proposals.approve(proposal.id)
    storage.create_effect(
        EffectRecord(
            effect_key="tool-action:1",
            run_id=run.id,
            kind="tool",
            payload={"proposal_id": proposal.id},
            status=EffectStatus.UNCERTAIN,
        )
    )
    service = EffectReconciliationService(
        outbox=EffectOutbox(storage),
        proposals=proposals,
        runs=runs,
    )

    service.resolve(
        "tool-action:1",
        resolution=EffectResolution.SUCCEEDED,
        note="目标文件存在且内容校验一致",
        result="written",
    )

    assert proposals.get(proposal.id).status == ActionStatus.COMPLETED
    assert runs.get(run.id).status == RunStatus.COMPLETED
    assert runs.get(run.id).events[-1].type == "run.effect_reconciled"


def test_existing_effect_table_is_migrated_with_reconciliation_audit_columns(tmp_path):
    db_path = tmp_path / "legacy-effects.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE effect_outbox (
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
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                finished_at TEXT
            )
            """
        )

    Storage.set_instance(None)
    migrated = Storage(str(db_path))
    with migrated._get_connection() as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(effect_outbox)").fetchall()}

    assert {
        "resolution",
        "reconciliation_note",
        "reconciled_by",
        "reconciled_at",
    } <= columns
    Storage.set_instance(None)


def test_repair_linked_state_closes_post_resolution_crash_window(storage):
    runs = RunManager(repository=storage)
    proposals = ActionProposalManager(repository=storage)
    run = runs.start(RunType.TOOL)
    proposal = proposals.propose(
        run_id=run.id,
        tool_name="write_file",
        arguments={"path": "report.md"},
        capabilities={Capability.WORKSPACE_WRITE},
    )
    proposals.approve(proposal.id)
    storage.create_effect(
        EffectRecord(
            effect_key="tool-action:repair",
            run_id=run.id,
            kind="tool",
            payload={"proposal_id": proposal.id},
            status=EffectStatus.COMPLETED,
            resolution=EffectResolution.SUCCEEDED,
            reconciliation_note="已核对文件摘要",
            reconciled_by="tester",
            reconciled_at=run.created_at,
            result="written",
        )
    )
    service = EffectReconciliationService(
        outbox=EffectOutbox(storage),
        proposals=proposals,
        runs=runs,
    )

    repaired = service.repair_linked_state()

    assert [item.effect_key for item in repaired] == ["tool-action:repair"]
    assert proposals.get(proposal.id).status == ActionStatus.COMPLETED
    assert runs.get(run.id).status == RunStatus.COMPLETED
    assert service.repair_linked_state() == []
