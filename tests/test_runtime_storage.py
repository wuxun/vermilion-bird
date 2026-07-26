from datetime import datetime, timezone

import pytest

from llm_chat.runtime import (
    ActionProposal,
    ActionProposalManager,
    ActionStatus,
    Capability,
    RecoveryPolicy,
    Run,
    RunEvent,
    RunManager,
    RunStatus,
    RunType,
)
from llm_chat.storage import Storage


@pytest.fixture
def storage(tmp_path):
    Storage.set_instance(None)
    instance = Storage(str(tmp_path / "runtime.db"))
    yield instance
    Storage.set_instance(None)


def test_run_and_events_round_trip(storage):
    now = datetime.now(timezone.utc)
    run = Run(
        id="run_persisted",
        type=RunType.WORKFLOW,
        status=RunStatus.RUNNING,
        conversation_id="conversation-1",
        input={"topic": "架构审查"},
        metadata={"owner": "gui"},
        created_at=now,
        started_at=now,
    )
    storage.save_run(run)
    storage.append_run_event(
        run.id,
        RunEvent(sequence=1, type="run.started", data={"source": "test"}),
    )

    run.status = RunStatus.COMPLETED
    run.result = {"summary": "done"}
    run.finished_at = now
    storage.save_run(run)

    restored = storage.get_run(run.id)
    assert restored is not None
    assert restored.status == RunStatus.COMPLETED
    assert restored.result == {"summary": "done"}
    assert restored.events[0].type == "run.started"
    assert restored.events[0].data == {"source": "test"}


def test_run_filters_and_children(storage):
    parent = Run(id="parent", type=RunType.CHAT, status=RunStatus.COMPLETED)
    child = Run(
        id="child",
        parent_run_id=parent.id,
        type=RunType.TOOL,
        status=RunStatus.FAILED,
        conversation_id="conversation-2",
    )
    storage.save_run(parent)
    storage.save_run(child)

    assert [item.id for item in storage.list_child_runs(parent.id)] == ["child"]
    assert [
        item.id
        for item in storage.list_runs(
            status=RunStatus.FAILED,
            run_type=RunType.TOOL,
            conversation_id="conversation-2",
        )
    ] == ["child"]


def test_action_proposal_round_trip_and_filters(storage):
    proposal = ActionProposal(
        id="action_persisted",
        run_id="run-origin",
        conversation_id="conversation-3",
        tool_name="write_file",
        arguments={"path": "notes.md", "content": "hello"},
        capabilities={Capability.WORKSPACE_WRITE},
        reason="保存结果",
        impact="将修改 notes.md",
        risk="high",
        reversible=True,
    )
    storage.save_action_proposal(proposal)

    proposal.status = ActionStatus.REJECTED
    proposal.decided_at = datetime.now(timezone.utc)
    proposal.finished_at = proposal.decided_at
    storage.save_action_proposal(proposal)

    restored = storage.get_action_proposal(proposal.id)
    assert restored is not None
    assert restored.status == ActionStatus.REJECTED
    assert restored.capabilities == {Capability.WORKSPACE_WRITE}
    assert restored.arguments["path"] == "notes.md"
    assert restored.reversible is True
    assert [
        item.id
        for item in storage.list_action_proposals(
            status=ActionStatus.REJECTED,
            conversation_id="conversation-3",
        )
    ] == [proposal.id]


def test_run_manager_restores_history_and_recovers_interrupted_run(storage):
    first_manager = RunManager(repository=storage)
    completed = first_manager.start(RunType.CHAT, input={"message": "done"})
    first_manager.complete(completed.id, "ok")
    interrupted = first_manager.start(RunType.WORKFLOW, input={"task": "pending"})

    restored_manager = RunManager(repository=storage)

    restored_completed = restored_manager.get(completed.id)
    restored_interrupted = restored_manager.get(interrupted.id)
    assert restored_completed is not None
    assert restored_completed.result == "ok"
    assert restored_interrupted is not None
    assert restored_interrupted.status == RunStatus.FAILED
    assert restored_interrupted.error == "应用重启前运行未正常结束"
    assert restored_interrupted.events[-1].type == "run.recovered"
    assert restored_interrupted.events[-1].data["previous_status"] == RunStatus.RUNNING.value


def test_pending_action_survives_restart_and_updates_observers(storage):
    origin = Run(id="origin", type=RunType.CHAT, status=RunStatus.COMPLETED)
    storage.save_run(origin)
    first_manager = ActionProposalManager(repository=storage)
    proposal = first_manager.propose(
        run_id=origin.id,
        conversation_id="conversation-4",
        tool_name="write_file",
        arguments={"path": "result.md"},
        capabilities={Capability.WORKSPACE_WRITE},
    )

    restored_manager = ActionProposalManager(repository=storage)
    observed = []
    restored_manager.subscribe(lambda item: observed.append(item.status))
    rejected = restored_manager.reject(
        proposal.id,
        conversation_id="conversation-4",
    )

    assert rejected.status == ActionStatus.REJECTED
    assert observed == [ActionStatus.REJECTED]
    assert storage.get_action_proposal(proposal.id).status == ActionStatus.REJECTED


def test_inflight_action_is_failed_during_restart_recovery(storage):
    proposal = ActionProposal(
        run_id="origin",
        tool_name="shell_exec",
        capabilities={Capability.PROCESS},
        reason="执行命令",
        impact="启动子进程",
        status=ActionStatus.EXECUTING,
    )
    storage.save_action_proposal(proposal)

    restored_manager = ActionProposalManager(repository=storage)

    restored = restored_manager.get(proposal.id)
    assert restored is not None
    assert restored.status == ActionStatus.FAILED
    assert "应用重启" in restored.error


def test_idempotency_key_returns_the_original_run_across_managers(storage):
    first = RunManager(repository=storage)
    original = first.start(
        RunType.SCHEDULED,
        idempotency_key="daily-report:2026-07-27",
    )
    first.complete(original.id, "done")

    second = RunManager(repository=storage)
    duplicate = second.start(
        RunType.SCHEDULED,
        idempotency_key="daily-report:2026-07-27",
    )

    assert duplicate.id == original.id
    assert duplicate.status == RunStatus.COMPLETED
    assert len(storage.list_runs()) == 1


def test_checkpoint_and_resume_policy_survive_restart(storage):
    first = RunManager(repository=storage)
    run = first.start(
        RunType.WORKFLOW,
        recovery_policy=RecoveryPolicy.RESUME,
        max_attempts=2,
    )
    first.checkpoint(run.id, cursor="approval", state={"approved": False})

    restored_manager = RunManager(repository=storage)
    interrupted = restored_manager.get(run.id)

    assert interrupted.status == RunStatus.PAUSED
    assert interrupted.can_resume is True
    assert interrupted.checkpoint.cursor == "approval"
    assert interrupted.metadata["recovery_action"] == "resume"

    resumed = restored_manager.resume(run.id)
    assert resumed.status == RunStatus.RUNNING
    assert resumed.checkpoint.state == {"approved": False}


def test_unexpired_lease_prevents_competing_manager_claim(storage):
    first = RunManager(repository=storage, owner_id="runner-a")
    run = first.start(
        RunType.WORKFLOW,
        recovery_policy=RecoveryPolicy.MANUAL,
    )
    assert first.claim(run.id, lease_seconds=120) is True

    second = RunManager(
        repository=storage,
        owner_id="runner-b",
        recover_interrupted=False,
    )

    assert second.claim(run.id, lease_seconds=120) is False
    assert storage.get_run(run.id).lease_owner == "runner-a"
