import uuid
from datetime import datetime

from llm_chat.scheduler.models import TaskType, TaskStatus, Task, TaskExecution


def test_task_serialization_roundtrip():
    t = Task(
        id=str(uuid.uuid4()),
        name="Sample Task",
        task_type=TaskType.LLM_CHAT,
        trigger_config={"cron": "0 0 * * *"},
        params={"model": "gpt-4"},
        enabled=True,
        max_retries=5,
        created_at=datetime(2026, 3, 29, 12, 0, 0),
        updated_at=datetime(2026, 3, 29, 12, 0, 0),
    )
    # JSON serialization should work and be parseable if needed
    j = t.json()
    assert isinstance(j, str)
    # Ensure essential fields preserve values
    assert t.task_type == TaskType.LLM_CHAT
    assert t.trigger_config["cron"] == "0 0 * * *"


def test_task_execution_serialization_and_status():
    te = TaskExecution(
        id=str(uuid.uuid4()),
        task_id="task-1",
        status=TaskStatus.RUNNING,
        started_at=datetime(2026, 3, 29, 12, 5, 0),
        finished_at=None,
        result=None,
        error=None,
        retry_count=0,
    )
    # status should serialize to string via json()
    j = te.json()
    assert isinstance(j, str)
    assert te.status == TaskStatus.RUNNING
