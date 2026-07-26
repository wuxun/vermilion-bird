from types import SimpleNamespace

import pytest

from llm_chat.runtime import (
    RecoveryPolicy,
    RunDispatcher,
    RunHandlerRegistry,
    RunManager,
    RunStatus,
    RunType,
)


class RecordingHandler:
    def __init__(self, runs):
        self.runs = runs
        self.calls = []

    def resume(self, run_id, value=None):
        self.calls.append(("resume", run_id, value))
        return self.runs.complete(run_id, value)

    def retry(self, run_id):
        self.calls.append(("retry", run_id))
        return self.runs.complete(run_id, "retried")

    def replay(self, run_id):
        self.calls.append(("replay", run_id))
        return self.runs.replay(run_id)


def test_dispatcher_routes_operations_by_persisted_handler_name():
    runs = RunManager()
    registry = RunHandlerRegistry()
    handler = RecordingHandler(runs)
    registry.register("chat", handler)
    dispatcher = RunDispatcher(run_manager=runs, registry=registry)

    paused = runs.start(
        RunType.CHAT,
        metadata={"run_handler": "chat"},
        recovery_policy=RecoveryPolicy.RESUME,
    )
    runs.checkpoint(paused.id, cursor="llm", state={"thread_id": paused.id})
    runs.pause(paused.id)

    completed = dispatcher.resume(paused.id, {"continue": True})

    assert completed.status == RunStatus.COMPLETED
    assert handler.calls == [("resume", paused.id, {"continue": True})]


def test_dispatcher_respects_handler_capability_guards():
    runs = RunManager()
    registry = RunHandlerRegistry()
    handler = RecordingHandler(runs)
    handler.can_replay = lambda _run: False
    registry.register("action", handler)
    dispatcher = RunDispatcher(run_manager=runs, registry=registry)
    run = runs.start(
        RunType.TOOL,
        metadata={"run_handler": "action"},
    )
    runs.complete(run.id)

    assert dispatcher.can_replay(run.id) is False
    with pytest.raises(ValueError, match="does not allow replay"):
        dispatcher.replay(run.id)


def test_registry_rejects_duplicates_and_dispatcher_unknown_handlers():
    runs = RunManager()
    registry = RunHandlerRegistry()
    handler = SimpleNamespace()
    registry.register("chat", handler)
    with pytest.raises(ValueError, match="already registered"):
        registry.register("chat", handler)

    run = runs.start(
        RunType.WORKFLOW,
        metadata={"run_handler": "missing"},
    )
    runs.complete(run.id)
    dispatcher = RunDispatcher(run_manager=runs, registry=registry)

    assert dispatcher.can_replay(run.id) is False
    with pytest.raises(ValueError, match="unavailable"):
        dispatcher.replay(run.id)
