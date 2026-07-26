from datetime import datetime, timezone

import pytest

from llm_chat.runtime import (
    ActionProposal,
    ActionStatus,
    Capability,
    Run,
    RunEvent,
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
