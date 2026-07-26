from llm_chat.runtime import (
    RecoveryPolicy,
    RunDispatcher,
    RunHandlerRegistry,
    RunManager,
    RunRecoveryCoordinator,
    RunType,
)


class RecoveryHandler:
    def __init__(self, runs):
        self.runs = runs

    def resume(self, run_id, value=None):
        self.runs.resume(run_id)
        return self.runs.complete(run_id, "resumed")

    def retry(self, run_id):
        self.runs.retry(run_id)
        return self.runs.complete(run_id, "retried")

    def replay(self, run_id):
        return self.runs.replay(run_id)


def test_recovery_coordinator_resumes_and_retries_only_safe_handlers():
    runs = RunManager()
    registry = RunHandlerRegistry()
    registry.register("safe", RecoveryHandler(runs))
    dispatcher = RunDispatcher(run_manager=runs, registry=registry)

    paused = runs.start(
        RunType.CHAT,
        metadata={"run_handler": "safe"},
        recovery_policy=RecoveryPolicy.RESUME,
        max_attempts=2,
    )
    runs.checkpoint(paused.id, cursor="llm", state={"checkpoint_id": "cp"})
    runs.pause(paused.id, "restart")

    retryable = runs.start(
        RunType.SCHEDULED,
        metadata={"run_handler": "safe", "recovery_action": "retry"},
        max_attempts=2,
    )
    runs.fail(retryable.id, "restart")

    action = runs.start(
        RunType.TOOL,
        metadata={"run_handler": "action"},
        recovery_policy=RecoveryPolicy.RESUME,
    )
    runs.checkpoint(action.id, cursor="approval", state={"checkpoint_id": "cp"})
    runs.pause(action.id, "approval")

    report = RunRecoveryCoordinator(
        run_manager=runs,
        dispatcher=dispatcher,
    ).recover_once()

    assert report.resumed == [paused.id]
    assert report.retried == [retryable.id]
    assert report.skipped == [action.id]
    assert report.errors == {}
    assert runs.get(paused.id).result == "resumed"
    assert runs.get(retryable.id).result == "retried"
