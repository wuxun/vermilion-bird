import time

from llm_chat.runtime import RunLeaseHeartbeat, RunManager, RunType
from llm_chat.storage import Storage


def test_heartbeat_renews_claimed_run_during_long_operation(tmp_path):
    Storage.set_instance(None)
    storage = Storage(str(tmp_path / "heartbeat.db"))
    manager = RunManager(repository=storage, owner_id="worker-a")
    run = manager.start(RunType.WORKFLOW)
    assert manager.claim(run.id, lease_seconds=1)
    claimed = manager.get(run.id)

    with RunLeaseHeartbeat(
        manager,
        run.id,
        lease_seconds=1,
        interval_seconds=0.02,
    ):
        time.sleep(0.08)

    renewed = manager.get(run.id)
    assert renewed.heartbeat_at > claimed.heartbeat_at
    assert renewed.lease_expires_at > claimed.lease_expires_at

    competitor = RunManager(
        repository=storage,
        owner_id="worker-b",
        recover_interrupted=False,
    )
    assert competitor.claim(run.id, lease_seconds=1) is False
    manager.complete(run.id)
    Storage.set_instance(None)
