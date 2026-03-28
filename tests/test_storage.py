import os
from datetime import datetime

import pytest

from llm_chat.storage import Storage
from llm_chat.scheduler.models import Task, TaskType, TaskExecution, TaskStatus


DB_PATH = "tests/test_vermilion_tasks.db"


def setup_module(module):
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)


def test_task_and_execution_storage_crud():
    storage = Storage(db_path=DB_PATH)

    # Prepare a sample task
    task = Task(
        id="task1",
        name="Test Task",
        task_type=TaskType.LLM_CHAT,
        trigger_config={"cron": "* * * * *"},
        params={"param": "value"},
        enabled=True,
        max_retries=2,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    # Save task
    storage.save_task(task)

    # Load and verify
    loaded = storage.load_task("task1")
    assert loaded is not None
    assert loaded.id == "task1"
    assert loaded.trigger_config == {"cron": "* * * * *"}

    # Load all tasks
    all_tasks = storage.load_all_tasks()
    assert any(t.id == "task1" for t in all_tasks)

    # Create and save an execution record
    exec_record = TaskExecution(
        id="exec1",
        task_id="task1",
        status=TaskStatus.PENDING,
        started_at=datetime.now(),
        finished_at=None,
        result=None,
        error=None,
        retry_count=0,
    )
    storage.save_execution(exec_record)

    execs = storage.load_executions("task1", limit=10)
    assert any(e.id == "exec1" for e in execs)

    storage.delete_task("task1")
    assert storage.load_task("task1") is None
