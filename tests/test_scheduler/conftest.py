import sqlite3
from datetime import datetime
import json

import pytest

from llm_chat.scheduler.models import Task, TaskType, TaskStatus, TaskExecution


@pytest.fixture
def temp_db():
    # Create an in-memory SQLite database for test isolation
    conn = sqlite3.connect(":memory:")
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def db_schema(temp_db):
    # Create basic schema for tasks and executions
    cur = temp_db.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            name TEXT,
            task_type TEXT,
            trigger_config TEXT,
            params TEXT,
            enabled BOOLEAN,
            max_retries INTEGER,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS task_executions (
            id TEXT PRIMARY KEY,
            task_id TEXT,
            status TEXT,
            started_at TEXT,
            finished_at TEXT,
            result TEXT,
            error TEXT,
            retry_count INTEGER,
            FOREIGN KEY (task_id) REFERENCES tasks(id)
        )
        """
    )
    temp_db.commit()
    yield cur
    cur.execute("DROP TABLE IF EXISTS task_executions")
    cur.execute("DROP TABLE IF EXISTS tasks")
    temp_db.commit()


@pytest.fixture
def db_with_sample_data(temp_db, db_schema, sample_task, sample_execution):
    # Insert sample data into the in-memory DB to simulate real usage
    cur = temp_db.cursor()
    cur.execute(
        "INSERT INTO tasks (id, name, task_type, trigger_config, params, enabled, max_retries, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            sample_task.id,
            sample_task.name,
            sample_task.task_type.value,
            json.dumps(sample_task.trigger_config),
            json.dumps(sample_task.params),
            sample_task.enabled,
            sample_task.max_retries,
            sample_task.created_at.isoformat(),
            sample_task.updated_at.isoformat(),
        ),
    )
    cur.execute(
        "INSERT INTO task_executions (id, task_id, status, started_at, finished_at, result, error, retry_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            sample_execution.id,
            sample_execution.task_id,
            sample_execution.status.value,
            sample_execution.started_at.isoformat(),
            sample_execution.finished_at.isoformat()
            if sample_execution.finished_at
            else None,
            sample_execution.result,
            sample_execution.error,
            sample_execution.retry_count,
        ),
    )
    temp_db.commit()
    yield temp_db
    cur.execute("DROP TABLE IF EXISTS task_executions")
    cur.execute("DROP TABLE IF EXISTS tasks")
    temp_db.commit()


@pytest.fixture
def sample_task() -> Task:
    # A representative Task instance for tests
    t = Task(
        id="sample-task",
        name="Sample Task",
        task_type=TaskType.LLM_CHAT,
        trigger_config={"cron": "0 0 * * *"},
        params={"model": "gpt-4"},
        enabled=True,
        max_retries=5,
        created_at=datetime(2026, 3, 29, 12, 0, 0),
        updated_at=datetime(2026, 3, 29, 12, 0, 0),
    )
    return t


@pytest.fixture
def sample_execution() -> TaskExecution:
    # A representative TaskExecution instance for tests
    te = TaskExecution(
        id="sample-exec",
        task_id="sample-task",
        status=TaskStatus.RUNNING,
        started_at=datetime(2026, 3, 29, 12, 5, 0),
        finished_at=None,
        result=None,
        error=None,
        retry_count=0,
    )
    return te
