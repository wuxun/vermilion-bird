import pytest

from llm_chat.runtime import (
    EffectOutbox,
    EffectRecord,
    EffectStatus,
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
