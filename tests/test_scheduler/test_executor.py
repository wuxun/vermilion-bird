"""Tests for TaskExecutor class."""

import uuid
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, call

import pytest

from llm_chat.scheduler.models import Task, TaskType, TaskStatus, TaskExecution
from llm_chat.scheduler.task_executor import TaskExecutor
from llm_chat.runtime import RunManager, RunStatus, RunType
from llm_chat.storage import Storage
from llm_chat.work import WorkItemKind, WorkItemService, WorkItemStatus


@pytest.fixture
def mock_app():
    """Create a mock App instance."""
    app = MagicMock()
    app.client = MagicMock()
    app.client.chat = MagicMock(return_value="LLM response")
    app.chat_core = None
    app.storage = MagicMock()
    return app


@pytest.fixture
def mock_storage():
    """Create a mock Storage instance."""
    storage = MagicMock()
    storage.save_execution = MagicMock(return_value="exec-id")
    return storage


@pytest.fixture
def executor(mock_app, mock_storage):
    """Create a TaskExecutor instance."""
    return TaskExecutor(app=mock_app, task_storage=mock_storage)


@pytest.fixture
def llm_chat_task():
    """Create a sample LLM chat task."""
    return Task(
        id=str(uuid.uuid4()),
        name="Daily Summary",
        task_type=TaskType.LLM_CHAT,
        trigger_config={"cron": "0 9 * * *"},
        params={
            "message": "Summarize recent activity",
            "conversation_id": "conv-123",
        },
        enabled=True,
        max_retries=3,
        created_at=datetime(2026, 3, 29, 12, 0, 0),
        updated_at=datetime(2026, 3, 29, 12, 0, 0),
    )


@pytest.fixture
def skill_task():
    """Create a sample skill execution task."""
    return Task(
        id=str(uuid.uuid4()),
        name="Web Search Task",
        task_type=TaskType.SKILL_EXECUTION,
        trigger_config={"cron": "0 10 * * *"},
        params={
            "skill_name": "web_search",
            "tool_name": "search",
            "arguments": {"query": "latest news"},
        },
        enabled=True,
        max_retries=3,
        created_at=datetime(2026, 3, 29, 12, 0, 0),
        updated_at=datetime(2026, 3, 29, 12, 0, 0),
    )


@pytest.fixture
def maintenance_task():
    """Create a sample system maintenance task."""
    return Task(
        id=str(uuid.uuid4()),
        name="Memory Cleanup",
        task_type=TaskType.SYSTEM_MAINTENANCE,
        trigger_config={"cron": "0 2 * * *"},
        params={
            "action": "cleanup_memory",
            "max_days": 30,
        },
        enabled=True,
        max_retries=3,
        created_at=datetime(2026, 3, 29, 12, 0, 0),
        updated_at=datetime(2026, 3, 29, 12, 0, 0),
    )


class TestTaskExecutorInit:
    """Tests for TaskExecutor initialization."""

    def test_init_with_app_and_storage(self, mock_app, mock_storage):
        """Test executor initialization with app and storage."""
        executor = TaskExecutor(app=mock_app, task_storage=mock_storage)
        assert executor.app == mock_app
        assert executor.task_storage == mock_storage

    def test_default_max_retries(self, mock_app, mock_storage):
        """Test default max retries configuration."""
        executor = TaskExecutor(app=mock_app, task_storage=mock_storage)
        assert executor.max_retries == 3

    def test_default_base_delay(self, mock_app, mock_storage):
        """Test default base delay for exponential backoff."""
        executor = TaskExecutor(app=mock_app, task_storage=mock_storage)
        assert executor.base_delay == 1.0

    def test_executor_records_parent_and_forwards_it_to_chat(
        self, mock_app, mock_storage, llm_chat_task
    ):
        mock_app.run_manager = RunManager()
        mock_app.chat_core = MagicMock()
        mock_app.chat_core.send_message.return_value = "done"
        executor = TaskExecutor(app=mock_app, task_storage=mock_storage)

        execution = executor.execute(llm_chat_task)

        parent = mock_app.run_manager.list(limit=1)[0]
        children = mock_app.run_manager.children(parent.id)
        assert execution.status == TaskStatus.COMPLETED
        assert parent.type == RunType.SCHEDULED
        assert parent.status == RunStatus.COMPLETED
        # ChatCore owns the child in production; verify the parent identity is
        # forwarded across the scheduler boundary.
        assert children == []
        assert mock_app.chat_core.send_message.call_args.kwargs["parent_run_id"] == parent.id

    def test_failed_scheduled_run_can_retry_through_its_handler(
        self,
        mock_app,
        mock_storage,
        llm_chat_task,
    ):
        task = llm_chat_task.model_copy(update={"max_retries": 0})
        mock_app.run_manager = RunManager()
        mock_storage.load_task.return_value = task
        mock_app.client.chat.side_effect = [RuntimeError("transient"), "recovered"]
        executor = TaskExecutor(app=mock_app, task_storage=mock_storage)

        failed_execution = executor.execute(task)
        failed_run = mock_app.run_manager.list(limit=1)[0]
        completed_run = executor.retry(failed_run.id)

        assert failed_execution.status == TaskStatus.FAILED
        assert failed_run.metadata["run_handler"] == "scheduled"
        assert completed_run.status == RunStatus.COMPLETED
        assert completed_run.result == "recovered"
        assert completed_run.attempt == 2

    def test_scheduled_execution_creates_product_work_item_and_artifact(
        self,
        tmp_path,
        llm_chat_task,
    ):
        Storage.set_instance(None)
        storage = Storage(str(tmp_path / "scheduled-work-item.db"))
        runs = RunManager(repository=storage)
        work_items = WorkItemService(repository=storage, runs=runs)
        client = MagicMock()
        client.chat.return_value = "scheduled result"
        app = SimpleNamespace(
            run_manager=runs,
            work_items=work_items,
            client=client,
            chat_core=None,
            storage=storage,
        )
        executor = TaskExecutor(app=app, task_storage=storage)
        task = llm_chat_task.model_copy(update={"max_retries": 0})
        storage.save_task(task)

        execution = executor.execute(task)
        item = work_items.list(limit=1)[0]
        detail = work_items.detail(item.id)

        assert execution.status == TaskStatus.COMPLETED
        assert item.kind == WorkItemKind.AUTOMATION
        assert item.status == WorkItemStatus.COMPLETED
        assert detail.runs[0].work_item_id == item.id
        assert detail.artifacts[0].content == "scheduled result"

        work_items.close()
        Storage.set_instance(None)


class TestExecuteLLMChat:
    """Tests for LLM chat task execution."""

    def test_execute_llm_chat_success(self, executor, llm_chat_task, mock_app):
        """Test successful LLM chat execution."""
        mock_app.client.chat.return_value = "Summary of activity"

        result = executor._execute_llm_chat(llm_chat_task)

        assert result == "Summary of activity"
        mock_app.client.chat.assert_called_once()
        _args, _kwargs = mock_app.client.chat.call_args
        assert _kwargs.get("message") == "Summarize recent activity"
        assert _kwargs.get("history") == []

    def test_execute_llm_chat_with_history(self, executor, llm_chat_task, mock_app):
        """Test LLM chat execution with conversation history."""
        mock_app.client.chat.return_value = "Response with context"
        llm_chat_task.params["history"] = [{"role": "user", "content": "Previous question"}]

        result = executor._execute_llm_chat(llm_chat_task)

        assert result == "Response with context"
        mock_app.client.chat.assert_called_once()
        _args, _kwargs = mock_app.client.chat.call_args
        assert _kwargs.get("history") == [{"role": "user", "content": "Previous question"}]

    def test_execute_llm_chat_with_custom_params(self, executor, mock_app, mock_storage):
        """Test LLM chat execution with custom model params."""
        task = Task(
            id="task-1",
            name="Custom Chat",
            task_type=TaskType.LLM_CHAT,
            trigger_config={},
            params={
                "message": "Hello",
                "model_params": {"temperature": 0.5, "max_tokens": 100},
            },
            enabled=True,
            max_retries=3,
            created_at=datetime(2026, 3, 29, 12, 0, 0),
            updated_at=datetime(2026, 3, 29, 12, 0, 0),
        )
        mock_app.client.chat.return_value = "Hi there"

        result = executor._execute_llm_chat(task)

        assert result == "Hi there"
        mock_app.client.chat.assert_called()
        _args, _kwargs = mock_app.client.chat.call_args
        # Ensure temperature/max_tokens are passed via model_params
        assert _kwargs.get("temperature") == 0.5
        assert _kwargs.get("max_tokens") == 100


class TestExecuteSkill:
    """Tests for skill execution tasks."""

    def test_execute_skill_success(self, executor, skill_task, mock_app):
        """Test successful skill execution."""
        skill_manager = MagicMock()
        skill_manager.execute_builtin_tool = MagicMock(return_value="Search results")
        mock_app.client.get_skill_manager = MagicMock(return_value=skill_manager)
        mock_app.client.execute_builtin_tool = MagicMock(return_value="Search results")

        result = executor._execute_skill(skill_task)

        assert result == "Search results"

    def test_execute_skill_with_tool_registry(self, executor, skill_task, mock_app):
        """Test skill execution using tool registry."""
        mock_app.client.execute_builtin_tool = MagicMock(return_value="Tool result")

        result = executor._execute_skill(skill_task)

        assert result == "Tool result"
        mock_app.client.execute_builtin_tool.assert_called_once()

    def test_execute_skill_unknown_skill(self, executor, mock_app, mock_storage):
        """Test handling of unknown skill."""
        task = Task(
            id="task-1",
            name="Unknown Skill",
            task_type=TaskType.SKILL_EXECUTION,
            trigger_config={},
            params={
                "skill_name": "nonexistent_skill",
                "arguments": {},
            },
            enabled=True,
            max_retries=3,
            created_at=datetime(2026, 3, 29, 12, 0, 0),
            updated_at=datetime(2026, 3, 29, 12, 0, 0),
        )
        mock_app.client.execute_builtin_tool = MagicMock(side_effect=ValueError("Skill not found"))

        with pytest.raises(ValueError, match="Skill not found"):
            executor._execute_skill(task)


class TestExecuteMaintenance:
    """Tests for system maintenance tasks."""

    def test_execute_maintenance_cleanup_memory(self, executor, maintenance_task, mock_app):
        """Test memory cleanup maintenance task."""
        memory_manager = MagicMock()
        memory_manager.compress_mid_term = MagicMock()
        mock_app.conversation_manager = MagicMock()
        mock_app.conversation_manager._memory_manager = memory_manager

        result = executor._execute_maintenance(maintenance_task)

        assert "cleanup_memory" in result.lower() or "completed" in result.lower()

    def test_execute_maintenance_archive_sessions(self, executor, mock_app, mock_storage):
        """Test session archival maintenance task."""
        task = Task(
            id="task-1",
            name="Archive Sessions",
            task_type=TaskType.SYSTEM_MAINTENANCE,
            trigger_config={},
            params={
                "action": "archive_sessions",
                "days_old": 7,
            },
            enabled=True,
            max_retries=3,
            created_at=datetime(2026, 3, 29, 12, 0, 0),
            updated_at=datetime(2026, 3, 29, 12, 0, 0),
        )

        result = executor._execute_maintenance(task)

        assert result is not None

    def test_execute_maintenance_unknown_action(self, executor, mock_app, mock_storage):
        """Test handling of unknown maintenance action."""
        task = Task(
            id="task-1",
            name="Unknown Action",
            task_type=TaskType.SYSTEM_MAINTENANCE,
            trigger_config={},
            params={
                "action": "unknown_action",
            },
            enabled=True,
            max_retries=3,
            created_at=datetime(2026, 3, 29, 12, 0, 0),
            updated_at=datetime(2026, 3, 29, 12, 0, 0),
        )

        result = executor._execute_maintenance(task)

        # Should return gracefully with a message
        assert "unknown" in result.lower() or "unsupported" in result.lower()


class TestExecute:
    """Tests for the main execute method."""

    def test_execute_llm_chat_task(self, executor, llm_chat_task, mock_app, mock_storage):
        """Test execute method with LLM chat task type."""
        mock_app.client.chat.return_value = "Response"

        execution = executor.execute(llm_chat_task)

        assert execution.task_id == llm_chat_task.id
        assert execution.status == TaskStatus.COMPLETED
        assert execution.result == "Response"
        assert execution.error is None
        mock_storage.save_execution.assert_called()

    def test_execute_skill_task(self, executor, skill_task, mock_app, mock_storage):
        """Test execute method with skill execution task type."""
        mock_app.client.execute_builtin_tool = MagicMock(return_value="Skill result")

        execution = executor.execute(skill_task)

        assert execution.task_id == skill_task.id
        assert execution.status == TaskStatus.COMPLETED
        assert execution.result == "Skill result"
        mock_storage.save_execution.assert_called()

    def test_execute_maintenance_task(self, executor, maintenance_task, mock_app, mock_storage):
        """Test execute method with maintenance task type."""
        execution = executor.execute(maintenance_task)

        assert execution.task_id == maintenance_task.id
        assert execution.status == TaskStatus.COMPLETED
        mock_storage.save_execution.assert_called()

    def test_execute_records_start_and_end_time(
        self, executor, llm_chat_task, mock_app, mock_storage
    ):
        """Test that execution records start and end times."""
        mock_app.client.chat.return_value = "Response"

        execution = executor.execute(llm_chat_task)

        assert execution.started_at is not None
        assert execution.finished_at is not None
        assert execution.finished_at >= execution.started_at

    def test_execute_disabled_task(self, executor, mock_app, mock_storage):
        """Test that disabled tasks are not executed."""
        task = Task(
            id="disabled-task",
            name="Disabled Task",
            task_type=TaskType.LLM_CHAT,
            trigger_config={},
            params={"message": "Test"},
            enabled=False,
            max_retries=3,
            created_at=datetime(2026, 3, 29, 12, 0, 0),
            updated_at=datetime(2026, 3, 29, 12, 0, 0),
        )

        execution = executor.execute(task)

        # Disabled tasks should be skipped
        assert execution.status == TaskStatus.FAILED or execution.result is None


class TestRetryLogic:
    """Tests for retry logic with exponential backoff."""

    def test_retry_on_failure(self, executor, llm_chat_task, mock_app, mock_storage):
        """Test that failed tasks are retried."""
        # First two calls fail, third succeeds
        mock_app.client.chat.side_effect = [
            Exception("Network error"),
            Exception("Timeout"),
            "Success on retry",
        ]

        execution = executor.execute(llm_chat_task)

        assert execution.status == TaskStatus.COMPLETED
        assert execution.result == "Success on retry"
        assert execution.retry_count == 2
        assert mock_app.client.chat.call_count == 3

    def test_max_retries_exceeded(self, executor, llm_chat_task, mock_app, mock_storage):
        """Test that retries stop after max attempts."""
        mock_app.client.chat.side_effect = Exception("Persistent error")

        execution = executor.execute(llm_chat_task)

        assert execution.status == TaskStatus.FAILED
        assert execution.error is not None
        assert "Persistent error" in execution.error
        # max_retries=3 means 4 attempts total (1 initial + 3 retries)
        assert mock_app.client.chat.call_count == 4

    def test_custom_max_retries(self, mock_app, mock_storage):
        """Test custom max retries from task configuration."""
        task = Task(
            id="task-1",
            name="Custom Retry Task",
            task_type=TaskType.LLM_CHAT,
            trigger_config={},
            params={"message": "Test"},
            enabled=True,
            max_retries=1,  # Only 1 retry
            created_at=datetime(2026, 3, 29, 12, 0, 0),
            updated_at=datetime(2026, 3, 29, 12, 0, 0),
        )
        executor = TaskExecutor(app=mock_app, task_storage=mock_storage)
        mock_app.client.chat.side_effect = Exception("Error")

        execution = executor.execute(task)

        assert execution.status == TaskStatus.FAILED
        # max_retries=1 means 2 attempts total
        assert mock_app.client.chat.call_count == 2

    @patch("time.sleep")
    def test_exponential_backoff(self, mock_sleep, executor, llm_chat_task, mock_app, mock_storage):
        """Test that exponential backoff is applied between retries."""
        mock_app.client.chat.side_effect = [
            Exception("Error 1"),
            Exception("Error 2"),
            "Success",
        ]

        executor.execute(llm_chat_task)

        # Should have called sleep twice with exponential backoff
        assert mock_sleep.call_count == 2
        # First delay: base_delay (1.0)
        # Second delay: base_delay * 2 (2.0)
        calls = [call(1.0), call(2.0)]
        mock_sleep.assert_has_calls(calls)

    @patch("time.sleep")
    def test_exponential_backoff_caps_at_max(self, mock_sleep, mock_app, mock_storage):
        """Test that backoff is capped at maximum delay."""
        task = Task(
            id="task-1",
            name="High Retry Task",
            task_type=TaskType.LLM_CHAT,
            trigger_config={},
            params={"message": "Test"},
            enabled=True,
            max_retries=10,  # Many retries
            created_at=datetime(2026, 3, 29, 12, 0, 0),
            updated_at=datetime(2026, 3, 29, 12, 0, 0),
        )
        executor = TaskExecutor(app=mock_app, task_storage=mock_storage)
        executor.max_delay = 10.0  # Cap at 10 seconds
        mock_app.client.chat.side_effect = Exception("Error")

        executor.execute(task)

        # Check that no sleep exceeds max_delay
        for call_args in mock_sleep.call_args_list:
            assert call_args[0][0] <= 10.0


class TestExecutionHistory:
    """Tests for execution history recording."""

    def test_save_execution_on_success(self, executor, llm_chat_task, mock_app, mock_storage):
        """Test that successful executions are saved."""
        mock_app.client.chat.return_value = "Response"

        executor.execute(llm_chat_task)

        mock_storage.save_execution.assert_called()
        saved_execution = mock_storage.save_execution.call_args[0][0]
        assert isinstance(saved_execution, TaskExecution)
        assert saved_execution.status == TaskStatus.COMPLETED

    def test_save_execution_on_failure(self, executor, llm_chat_task, mock_app, mock_storage):
        """Test that failed executions are saved with error."""
        mock_app.client.chat.side_effect = Exception("API Error")

        executor.execute(llm_chat_task)

        mock_storage.save_execution.assert_called()
        saved_execution = mock_storage.save_execution.call_args[0][0]
        assert saved_execution.status == TaskStatus.FAILED
        assert "API Error" in saved_execution.error

    def test_execution_id_generated(self, executor, llm_chat_task, mock_app, mock_storage):
        """Test that execution ID is generated."""
        mock_app.client.chat.return_value = "Response"

        execution = executor.execute(llm_chat_task)

        assert execution.id is not None
        assert len(execution.id) > 0

    def test_execution_links_to_task(self, executor, llm_chat_task, mock_app, mock_storage):
        """Test that execution is linked to its task."""
        mock_app.client.chat.return_value = "Response"

        execution = executor.execute(llm_chat_task)

        assert execution.task_id == llm_chat_task.id
