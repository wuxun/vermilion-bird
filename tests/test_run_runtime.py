"""Tests for the first unified Run runtime slice."""

import threading

import pytest

from llm_chat.runtime import RecoveryPolicy, RunManager, RunStatus, RunType


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


def test_retry_increments_attempt_and_preserves_logical_run():
    manager = RunManager()
    run = manager.start(
        RunType.WORKFLOW,
        recovery_policy=RecoveryPolicy.RETRY,
        max_attempts=3,
    )
    manager.fail(run.id, "temporary")

    retried = manager.retry(run.id)

    assert retried.id == run.id
    assert retried.status == RunStatus.RUNNING
    assert retried.attempt == 2
    assert retried.error is None
    assert retried.events[-1].type == "run.retried"


def test_resume_requires_checkpoint_and_checks_version():
    manager = RunManager()
    run = manager.start(
        RunType.WORKFLOW,
        recovery_policy=RecoveryPolicy.RESUME,
    )

    with pytest.raises(ValueError, match="no checkpoint"):
        manager.pause(run.id)
        manager.resume(run.id)

    checkpointed = manager.checkpoint(
        run.id,
        cursor="review",
        state={"draft": "v1"},
    )
    assert checkpointed.checkpoint.version == 1
    with pytest.raises(ValueError, match="version conflict"):
        manager.checkpoint(
            run.id,
            cursor="review",
            state={"draft": "stale"},
            expected_version=0,
        )

    resumed = manager.resume(run.id)
    assert resumed.status == RunStatus.RUNNING
    assert resumed.checkpoint.state == {"draft": "v1"}


def test_cancel_request_is_visible_until_worker_acknowledges():
    manager = RunManager()
    run = manager.start(RunType.CHAT)
    cancel_event = threading.Event()
    pause_event = threading.Event()
    manager.register_control(
        run.id,
        cancel_event=cancel_event,
        pause_event=pause_event,
    )

    requested = manager.request_cancel(run.id)

    assert requested.status == RunStatus.CANCEL_REQUESTED
    assert cancel_event.is_set()
    assert requested.events[-1].type == "run.cancel_requested"

    cancelled = manager.acknowledge_cancel(run.id)
    assert cancelled.status == RunStatus.CANCELLED


def test_pause_request_requires_checkpoint_before_acknowledgement():
    manager = RunManager()
    run = manager.start(RunType.WORKFLOW)
    cancel_event = threading.Event()
    pause_event = threading.Event()
    manager.register_control(
        run.id,
        cancel_event=cancel_event,
        pause_event=pause_event,
    )

    requested = manager.request_pause(run.id)

    assert requested.status == RunStatus.PAUSE_REQUESTED
    assert pause_event.is_set()
    with pytest.raises(ValueError, match="without a checkpoint"):
        manager.acknowledge_pause(run.id)

    manager.checkpoint(run.id, cursor="safe", state={"step": 1})
    paused = manager.acknowledge_pause(run.id)
    assert paused.status == RunStatus.PAUSED
    assert manager.resume(run.id).status == RunStatus.RUNNING


def test_control_request_cascades_to_running_children():
    manager = RunManager()
    parent = manager.start(RunType.WORKFLOW)
    child = manager.start(RunType.TOOL, parent_run_id=parent.id)
    child_cancel = threading.Event()
    manager.register_control(
        child.id,
        cancel_event=child_cancel,
        pause_event=threading.Event(),
    )

    manager.request_cancel(parent.id)

    assert manager.get(parent.id).status == RunStatus.CANCEL_REQUESTED
    assert manager.get(child.id).status == RunStatus.CANCEL_REQUESTED
    assert child_cancel.is_set()
