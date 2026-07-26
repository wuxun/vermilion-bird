"""Tests for the first unified Run runtime slice."""

from llm_chat.runtime import RunManager, RunStatus, RunType


def test_run_lifecycle_emits_ordered_events():
    manager = RunManager()
    observed = []
    manager.subscribe(lambda run, event: observed.append((run.id, event.sequence, event.type)))

    run = manager.start(
        RunType.CHAT,
        conversation_id="conv-1",
        input={"message": "hello"},
    )
    manager.emit(run.id, "model.started", {"model": "test"})
    completed = manager.complete(run.id, "world")

    assert completed.status == RunStatus.COMPLETED
    assert completed.result == "world"
    assert [event.type for event in completed.events] == [
        "run.started",
        "model.started",
        "run.completed",
    ]
    assert [sequence for _, sequence, _ in observed] == [1, 2, 3]


def test_run_snapshots_cannot_mutate_manager_state():
    manager = RunManager()
    run = manager.start(RunType.WEBHOOK, input={"payload": {"safe": True}})

    run.input["payload"]["safe"] = False

    stored = manager.get(run.id)
    assert stored.input["payload"]["safe"] is True


def test_terminal_run_is_idempotent():
    manager = RunManager()
    run = manager.start(RunType.TOOL)

    manager.fail(run.id, "boom")
    manager.complete(run.id, "should not overwrite failure")

    stored = manager.get(run.id)
    assert stored.status == RunStatus.FAILED
    assert stored.error == "boom"
    assert stored.result is None


def test_parent_child_runs_are_queryable_in_creation_order():
    manager = RunManager()
    parent = manager.start(RunType.SCHEDULED)
    first = manager.start(RunType.CHAT, parent_run_id=parent.id)
    second = manager.start(RunType.WORKFLOW, parent_run_id=parent.id)

    assert [run.id for run in manager.children(parent.id)] == [
        first.id,
        second.id,
    ]
