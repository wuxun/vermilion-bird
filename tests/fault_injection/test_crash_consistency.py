"""关键持久化边界的故障注入回归测试。"""

import pytest

from llm_chat.runtime import (
    EffectOutbox,
    EffectRecord,
    EffectStatus,
    RecoveryPolicy,
    RunManager,
    RunStatus,
    RunType,
    UncertainEffectError,
)
from llm_chat.storage import Storage
from llm_chat.work import ArtifactKind, WorkItemService


class _FailAfterCommitRepository:
    """让指定写操作在数据库提交后模拟进程异常。"""

    def __init__(self, delegate, method_name):
        self.delegate = delegate
        self.method_name = method_name
        self.failed = False

    def __getattr__(self, name):
        return getattr(self.delegate, name)

    def create_work_item(self, item):
        created = self.delegate.create_work_item(item)
        self._fail_once("create_work_item")
        return created

    def create_artifact(self, artifact):
        created = self.delegate.create_artifact(artifact)
        self._fail_once("create_artifact")
        return created

    def _fail_once(self, method_name):
        if method_name == self.method_name and not self.failed:
            self.failed = True
            raise RuntimeError(f"injected crash after {method_name} commit")


@pytest.fixture
def storage(tmp_path):
    Storage.set_instance(None)
    instance = Storage(str(tmp_path / "fault-injection.db"))
    yield instance
    Storage.set_instance(None)


def test_work_item_retry_converges_after_commit_then_crash(storage):
    repository = _FailAfterCommitRepository(storage, "create_work_item")
    service = WorkItemService(
        repository=repository,
        runs=RunManager(repository=storage),
    )

    with pytest.raises(RuntimeError, match="injected crash"):
        service.create(
            objective="生成研究报告",
            idempotency_key="fault:work-item",
        )

    recovered = service.create(
        objective="生成研究报告",
        idempotency_key="fault:work-item",
    )

    assert recovered.idempotency_key == "fault:work-item"
    assert len(storage.list_work_items()) == 1


def test_artifact_retry_converges_after_commit_then_crash(storage):
    repository = _FailAfterCommitRepository(storage, "create_artifact")
    runs = RunManager(repository=storage)
    service = WorkItemService(repository=repository, runs=runs)
    item = service.create(objective="生成研究报告")

    with pytest.raises(RuntimeError, match="injected crash"):
        service.add_artifact(
            item.id,
            name="report.md",
            kind=ArtifactKind.REPORT,
            idempotency_key="fault:artifact",
        )

    recovered = service.add_artifact(
        item.id,
        name="report.md",
        kind=ArtifactKind.REPORT,
        idempotency_key="fault:artifact",
    )

    assert recovered.idempotency_key == "fault:artifact"
    assert len(storage.list_artifacts(item.id)) == 1


def test_restart_converges_cancel_request_to_terminal_state(storage):
    first = RunManager(repository=storage)
    run = first.start(
        RunType.WORKFLOW,
        recovery_policy=RecoveryPolicy.RESUME,
    )
    first.request_cancel(run.id, reason="fault-injection")

    restored = RunManager(repository=storage)

    assert restored.get(run.id).status == RunStatus.CANCELLED
    assert storage.get_run(run.id).status == RunStatus.CANCELLED


def test_restart_converges_pause_request_when_checkpoint_exists(storage):
    first = RunManager(repository=storage)
    run = first.start(
        RunType.WORKFLOW,
        recovery_policy=RecoveryPolicy.RESUME,
    )
    first.checkpoint(
        run.id,
        cursor="deliver",
        state={"artifact_id": "artifact_fault"},
    )
    first.request_pause(run.id, reason="fault-injection")

    restored = RunManager(repository=storage)

    recovered = restored.get(run.id)
    assert recovered.status == RunStatus.PAUSED
    assert recovered.checkpoint.cursor == "deliver"


def test_restart_never_replays_an_interrupted_external_effect(storage):
    assert storage.create_effect(
        EffectRecord(
            effect_key="fault:external-message",
            kind="external_message",
            status=EffectStatus.EXECUTING,
            attempts=1,
        )
    )
    outbox = EffectOutbox(storage)
    calls = []

    reconciled = outbox.reconcile_interrupted()

    assert [effect.status for effect in reconciled] == [EffectStatus.UNCERTAIN]
    with pytest.raises(UncertainEffectError):
        outbox.execute(
            effect_key="fault:external-message",
            executor=lambda: calls.append("duplicate"),
        )
    assert calls == []
