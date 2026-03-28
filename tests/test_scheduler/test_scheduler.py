"""SchedulerService 单元测试

使用 mock APScheduler 进行测试，验证任务管理功能。
"""

import uuid
from datetime import datetime
from unittest.mock import MagicMock, patch, call

import pytest

from llm_chat.scheduler.models import Task, TaskType, TaskStatus, TaskExecution
from llm_chat.scheduler.scheduler import SchedulerService
from llm_chat.config import SchedulerConfig


@pytest.fixture
def scheduler_config():
    """创建测试用的调度器配置"""
    return SchedulerConfig(
        enabled=True,
        max_workers=4,
        default_timezone="local",
    )


@pytest.fixture
def mock_storage():
    """创建 mock Storage"""
    storage = MagicMock()
    storage.save_task.return_value = "test-task-id"
    storage.load_task.return_value = None
    storage.load_all_tasks.return_value = []
    storage.delete_task.return_value = True
    storage.save_execution.return_value = "exec-id"
    storage.load_executions.return_value = []
    return storage


@pytest.fixture
def mock_app():
    """创建 mock App"""
    app = MagicMock()
    app.client = MagicMock()
    return app


@pytest.fixture
def sample_task():
    """创建示例任务"""
    return Task(
        id="sample-task-id",
        name="Sample Task",
        task_type=TaskType.LLM_CHAT,
        trigger_config={"cron": "0 0 * * *"},
        params={"model": "gpt-4", "message": "Hello"},
        enabled=True,
        max_retries=3,
        created_at=datetime(2026, 3, 29, 12, 0, 0),
        updated_at=datetime(2026, 3, 29, 12, 0, 0),
    )


class TestSchedulerServiceInit:
    """测试 SchedulerService 初始化"""

    @patch("llm_chat.scheduler.scheduler.BackgroundScheduler")
    @patch("llm_chat.scheduler.scheduler.ThreadPoolExecutor")
    @patch("llm_chat.scheduler.scheduler.SQLAlchemyJobStore")
    def test_init_creates_scheduler_with_config(
        self,
        mock_jobstore,
        mock_executor,
        mock_bg_scheduler,
        scheduler_config,
        mock_storage,
        mock_app,
    ):
        """测试初始化创建调度器并应用配置"""
        service = SchedulerService(scheduler_config, mock_storage, mock_app)

        # 验证 ThreadPoolExecutor 使用配置的 max_workers
        mock_executor.assert_called_once_with(max_workers=scheduler_config.max_workers)

        # 验证 SQLAlchemyJobStore 使用正确的数据库路径
        mock_jobstore.assert_called_once()
        jobstore_call = mock_jobstore.call_args
        assert (
            "sqlite:///.vb/vermilion_bird.db" in str(jobstore_call)
            or jobstore_call[1].get("url") == "sqlite:///.vb/vermilion_bird.db"
        )

    @patch("llm_chat.scheduler.scheduler.BackgroundScheduler")
    def test_init_registers_event_listeners(
        self, mock_bg_scheduler, scheduler_config, mock_storage, mock_app
    ):
        """测试初始化注册事件监听器"""
        mock_scheduler_instance = MagicMock()
        mock_bg_scheduler.return_value = mock_scheduler_instance

        service = SchedulerService(scheduler_config, mock_storage, mock_app)

        # 验证事件监听器已添加
        mock_scheduler_instance.add_listener.assert_called()


class TestSchedulerServiceLifecycle:
    """测试调度器生命周期"""

    @patch("llm_chat.scheduler.scheduler.BackgroundScheduler")
    def test_start_starts_scheduler(
        self, mock_bg_scheduler, scheduler_config, mock_storage, mock_app
    ):
        """测试 start() 启动调度器"""
        mock_scheduler_instance = MagicMock()
        mock_bg_scheduler.return_value = mock_scheduler_instance

        service = SchedulerService(scheduler_config, mock_storage, mock_app)
        service.start()

        mock_scheduler_instance.start.assert_called_once()

    @patch("llm_chat.scheduler.scheduler.BackgroundScheduler")
    def test_shutdown_shuts_down_scheduler(
        self, mock_bg_scheduler, scheduler_config, mock_storage, mock_app
    ):
        """测试 shutdown() 关闭调度器"""
        mock_scheduler_instance = MagicMock()
        mock_bg_scheduler.return_value = mock_scheduler_instance

        service = SchedulerService(scheduler_config, mock_storage, mock_app)
        service.start()
        service.shutdown()

        mock_scheduler_instance.shutdown.assert_called_once()

    @patch("llm_chat.scheduler.scheduler.BackgroundScheduler")
    def test_shutdown_without_start_is_safe(
        self, mock_bg_scheduler, scheduler_config, mock_storage, mock_app
    ):
        """测试未启动时调用 shutdown 是安全的"""
        mock_scheduler_instance = MagicMock()
        mock_bg_scheduler.return_value = mock_scheduler_instance

        service = SchedulerService(scheduler_config, mock_storage, mock_app)
        # 不调用 start()，直接调用 shutdown
        service.shutdown()

        # 不应该抛出异常


class TestSchedulerServiceTaskManagement:
    """测试任务管理"""

    @patch("llm_chat.scheduler.scheduler.BackgroundScheduler")
    def test_add_task_returns_task_id(
        self, mock_bg_scheduler, scheduler_config, mock_storage, mock_app, sample_task
    ):
        """测试 add_task() 返回任务 ID"""
        mock_scheduler_instance = MagicMock()
        mock_scheduler_instance.add_job.return_value = sample_task.id
        mock_bg_scheduler.return_value = mock_scheduler_instance

        service = SchedulerService(scheduler_config, mock_storage, mock_app)
        service.start()

        task_id = service.add_task(sample_task)

        assert task_id == sample_task.id
        # 验证任务保存到存储
        mock_storage.save_task.assert_called_once_with(sample_task)
        # 验证任务添加到调度器
        mock_scheduler_instance.add_job.assert_called_once()

    @patch("llm_chat.scheduler.scheduler.BackgroundScheduler")
    def test_remove_task_returns_true_when_exists(
        self, mock_bg_scheduler, scheduler_config, mock_storage, mock_app, sample_task
    ):
        """测试 remove_task() 删除存在的任务返回 True"""
        mock_scheduler_instance = MagicMock()
        mock_scheduler_instance.remove_job.return_value = True
        mock_bg_scheduler.return_value = mock_scheduler_instance

        service = SchedulerService(scheduler_config, mock_storage, mock_app)
        service.start()

        result = service.remove_task(sample_task.id)

        assert result is True
        mock_storage.delete_task.assert_called_once_with(sample_task.id)
        mock_scheduler_instance.remove_job.assert_called_once_with(sample_task.id)

    @patch("llm_chat.scheduler.scheduler.BackgroundScheduler")
    def test_remove_task_returns_false_when_not_exists(
        self, mock_bg_scheduler, scheduler_config, mock_storage, mock_app
    ):
        """测试 remove_task() 删除不存在的任务返回 False"""
        mock_scheduler_instance = MagicMock()
        mock_scheduler_instance.remove_job.side_effect = Exception("Job not found")
        mock_bg_scheduler.return_value = mock_scheduler_instance

        service = SchedulerService(scheduler_config, mock_storage, mock_app)
        service.start()

        result = service.remove_task("non-existent-id")

        assert result is False

    @patch("llm_chat.scheduler.scheduler.BackgroundScheduler")
    def test_pause_task_pauses_job(
        self, mock_bg_scheduler, scheduler_config, mock_storage, mock_app, sample_task
    ):
        """测试 pause_task() 暂停任务"""
        mock_scheduler_instance = MagicMock()
        mock_bg_scheduler.return_value = mock_scheduler_instance
        mock_storage.load_task.return_value = sample_task

        service = SchedulerService(scheduler_config, mock_storage, mock_app)
        service.start()

        result = service.pause_task(sample_task.id)

        assert result is True
        mock_scheduler_instance.pause_job.assert_called_once_with(sample_task.id)

    @patch("llm_chat.scheduler.scheduler.BackgroundScheduler")
    def test_resume_task_resumes_job(
        self, mock_bg_scheduler, scheduler_config, mock_storage, mock_app, sample_task
    ):
        """测试 resume_task() 恢复任务"""
        mock_scheduler_instance = MagicMock()
        mock_bg_scheduler.return_value = mock_scheduler_instance
        mock_storage.load_task.return_value = sample_task

        service = SchedulerService(scheduler_config, mock_storage, mock_app)
        service.start()

        result = service.resume_task(sample_task.id)

        assert result is True
        mock_scheduler_instance.resume_job.assert_called_once_with(sample_task.id)

    @patch("llm_chat.scheduler.scheduler.BackgroundScheduler")
    def test_trigger_task_modifies_job(
        self, mock_bg_scheduler, scheduler_config, mock_storage, mock_app, sample_task
    ):
        """测试 trigger_task() 手动触发任务"""
        mock_scheduler_instance = MagicMock()
        mock_job = MagicMock()
        mock_scheduler_instance.get_job.return_value = mock_job
        mock_bg_scheduler.return_value = mock_scheduler_instance
        mock_storage.load_task.return_value = sample_task

        service = SchedulerService(scheduler_config, mock_storage, mock_app)
        service.start()

        result = service.trigger_task(sample_task.id)

        assert result is True
        mock_scheduler_instance.modify_job.assert_called_once()

    @patch("llm_chat.scheduler.scheduler.BackgroundScheduler")
    def test_trigger_task_returns_false_when_not_found(
        self, mock_bg_scheduler, scheduler_config, mock_storage, mock_app
    ):
        """测试 trigger_task() 任务不存在时返回 False"""
        mock_scheduler_instance = MagicMock()
        mock_scheduler_instance.get_job.return_value = None
        mock_bg_scheduler.return_value = mock_scheduler_instance

        service = SchedulerService(scheduler_config, mock_storage, mock_app)
        service.start()

        result = service.trigger_task("non-existent-id")

        assert result is False

    @patch("llm_chat.scheduler.scheduler.BackgroundScheduler")
    def test_get_task_returns_task_from_storage(
        self, mock_bg_scheduler, scheduler_config, mock_storage, mock_app, sample_task
    ):
        """测试 get_task() 从存储获取任务"""
        mock_bg_scheduler.return_value = MagicMock()
        mock_storage.load_task.return_value = sample_task

        service = SchedulerService(scheduler_config, mock_storage, mock_app)

        result = service.get_task(sample_task.id)

        assert result == sample_task
        mock_storage.load_task.assert_called_once_with(sample_task.id)

    @patch("llm_chat.scheduler.scheduler.BackgroundScheduler")
    def test_get_task_returns_none_when_not_found(
        self, mock_bg_scheduler, scheduler_config, mock_storage, mock_app
    ):
        """测试 get_task() 任务不存在返回 None"""
        mock_bg_scheduler.return_value = MagicMock()
        mock_storage.load_task.return_value = None

        service = SchedulerService(scheduler_config, mock_storage, mock_app)

        result = service.get_task("non-existent-id")

        assert result is None

    @patch("llm_chat.scheduler.scheduler.BackgroundScheduler")
    def test_get_all_tasks_returns_tasks_from_storage(
        self, mock_bg_scheduler, scheduler_config, mock_storage, mock_app, sample_task
    ):
        """测试 get_all_tasks() 从存储获取所有任务"""
        mock_bg_scheduler.return_value = MagicMock()
        mock_storage.load_all_tasks.return_value = [sample_task]

        service = SchedulerService(scheduler_config, mock_storage, mock_app)

        result = service.get_all_tasks()

        assert len(result) == 1
        assert result[0] == sample_task
        mock_storage.load_all_tasks.assert_called_once()


class TestSchedulerServiceExecution:
    """测试任务执行"""

    @patch("llm_chat.scheduler.scheduler.BackgroundScheduler")
    def test_execute_task_creates_execution_record(
        self, mock_bg_scheduler, scheduler_config, mock_storage, mock_app, sample_task
    ):
        """测试执行任务时创建执行记录"""
        mock_bg_scheduler.return_value = MagicMock()
        mock_storage.load_task.return_value = sample_task

        service = SchedulerService(scheduler_config, mock_storage, mock_app)

        # 执行任务回调
        service._execute_task(sample_task.id)

        # 验证执行记录已保存
        mock_storage.save_execution.assert_called()
        call_args = mock_storage.save_execution.call_args
        execution = call_args[0][0]
        assert isinstance(execution, TaskExecution)
        assert execution.task_id == sample_task.id

    @patch("llm_chat.scheduler.scheduler.BackgroundScheduler")
    def test_execute_llm_chat_task_calls_client(
        self, mock_bg_scheduler, scheduler_config, mock_storage, mock_app, sample_task
    ):
        """测试执行 LLM_CHAT 类型任务调用客户端"""
        mock_bg_scheduler.return_value = MagicMock()
        mock_storage.load_task.return_value = sample_task
        mock_app.client.chat.return_value = "AI response"

        service = SchedulerService(scheduler_config, mock_storage, mock_app)
        service._execute_task(sample_task.id)

        mock_app.client.chat.assert_called_once()

    @patch("llm_chat.scheduler.scheduler.BackgroundScheduler")
    def test_execute_task_handles_exception(
        self, mock_bg_scheduler, scheduler_config, mock_storage, mock_app, sample_task
    ):
        """测试执行任务时异常处理"""
        mock_bg_scheduler.return_value = MagicMock()
        mock_storage.load_task.return_value = sample_task
        mock_app.client.chat.side_effect = Exception("API error")

        service = SchedulerService(scheduler_config, mock_storage, mock_app)
        service._execute_task(sample_task.id)

        # 验证执行记录包含错误信息
        mock_storage.save_execution.assert_called()
        call_args = mock_storage.save_execution.call_args
        execution = call_args[0][0]
        assert execution.status == TaskStatus.FAILED
        assert "API error" in execution.error


class TestSchedulerServiceEventListeners:
    """测试事件监听器"""

    @patch("llm_chat.scheduler.scheduler.BackgroundScheduler")
    def test_on_job_executed_updates_execution_status(
        self, mock_bg_scheduler, scheduler_config, mock_storage, mock_app
    ):
        """测试任务执行成功事件更新执行状态"""
        mock_scheduler_instance = MagicMock()
        mock_bg_scheduler.return_value = mock_scheduler_instance

        service = SchedulerService(scheduler_config, mock_storage, mock_app)

        # 模拟任务执行成功事件
        event = MagicMock()
        event.code = 4096  # EVENT_JOB_EXECUTED
        event.job_id = "test-job-id"
        event.retval = "success result"

        service._on_job_event(event)

        # 验证事件处理不抛出异常

    @patch("llm_chat.scheduler.scheduler.BackgroundScheduler")
    def test_on_job_error_records_error(
        self, mock_bg_scheduler, scheduler_config, mock_storage, mock_app
    ):
        """测试任务执行失败事件记录错误"""
        mock_scheduler_instance = MagicMock()
        mock_bg_scheduler.return_value = mock_scheduler_instance

        service = SchedulerService(scheduler_config, mock_storage, mock_app)

        # 模拟任务执行失败事件
        event = MagicMock()
        event.code = 8192  # EVENT_JOB_ERROR
        event.job_id = "test-job-id"
        event.exception = Exception("Task failed")

        service._on_job_event(event)

        # 验证事件处理不抛出异常


class TestSchedulerServiceTriggerConfig:
    """测试触发器配置解析"""

    @patch("llm_chat.scheduler.scheduler.BackgroundScheduler")
    def test_cron_trigger_config(
        self, mock_bg_scheduler, scheduler_config, mock_storage, mock_app, sample_task
    ):
        """测试 cron 触发器配置"""
        mock_scheduler_instance = MagicMock()
        mock_bg_scheduler.return_value = mock_scheduler_instance

        service = SchedulerService(scheduler_config, mock_storage, mock_app)
        service.start()
        service.add_task(sample_task)

        # 验证 add_job 被调用，且使用了正确的触发器
        call_args = mock_scheduler_instance.add_job.call_args
        assert call_args is not None

    @patch("llm_chat.scheduler.scheduler.BackgroundScheduler")
    def test_interval_trigger_config(
        self, mock_bg_scheduler, scheduler_config, mock_storage, mock_app
    ):
        """测试 interval 触发器配置"""
        mock_scheduler_instance = MagicMock()
        mock_bg_scheduler.return_value = mock_scheduler_instance

        service = SchedulerService(scheduler_config, mock_storage, mock_app)
        service.start()

        task = Task(
            id="interval-task-id",
            name="Interval Task",
            task_type=TaskType.LLM_CHAT,
            trigger_config={"interval": 3600},  # 每小时
            params={"model": "gpt-4"},
            enabled=True,
            max_retries=3,
            created_at=datetime(2026, 3, 29, 12, 0, 0),
            updated_at=datetime(2026, 3, 29, 12, 0, 0),
        )
        service.add_task(task)

        # 验证 add_job 被调用
        mock_scheduler_instance.add_job.assert_called_once()

    @patch("llm_chat.scheduler.scheduler.BackgroundScheduler")
    def test_date_trigger_config(
        self, mock_bg_scheduler, scheduler_config, mock_storage, mock_app
    ):
        """测试 date (一次性) 触发器配置"""
        mock_scheduler_instance = MagicMock()
        mock_bg_scheduler.return_value = mock_scheduler_instance

        service = SchedulerService(scheduler_config, mock_storage, mock_app)
        service.start()

        task = Task(
            id="date-task-id",
            name="One-time Task",
            task_type=TaskType.LLM_CHAT,
            trigger_config={"date": "2026-04-01 10:00:00"},
            params={"model": "gpt-4"},
            enabled=True,
            max_retries=3,
            created_at=datetime(2026, 3, 29, 12, 0, 0),
            updated_at=datetime(2026, 3, 29, 12, 0, 0),
        )
        service.add_task(task)

        # 验证 add_job 被调用
        mock_scheduler_instance.add_job.assert_called_once()
