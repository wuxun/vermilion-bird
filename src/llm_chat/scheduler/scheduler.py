"""SchedulerService - 调度器核心服务

使用 APScheduler 3.x 实现任务调度功能。
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional, List, Callable, Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.executors.pool import ThreadPoolExecutor

from .models import Task, TaskType, TaskStatus, TaskExecution

if TYPE_CHECKING:
    from llm_chat.config import SchedulerConfig
    from llm_chat.storage import Storage
    from llm_chat.app import App


logger = logging.getLogger(__name__)


class SchedulerService:
    """调度器服务，管理定时任务的调度和执行。

    使用 APScheduler BackgroundScheduler + ThreadPoolExecutor，
    支持 cron、date 两种触发器类型。
    """

    def __init__(self, config: "SchedulerConfig", task_storage: "Storage", app: "App"):
        """初始化调度器服务。

        Args:
            config: 调度器配置
            task_storage: 任务存储（用于持久化任务和执行记录）
            app: 应用实例（用于执行任务时访问 LLM 客户端等）
        """
        self._config = config
        self._storage = task_storage
        self._app = app
        self._scheduler: Optional[BackgroundScheduler] = None
        self._running = False

        self._setup_scheduler()

    def _setup_scheduler(self):
        """配置调度器组件"""
        # 延迟导入以避免在模块加载时触发 pkg_resources 依赖
        from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
        from apscheduler.executors.pool import ThreadPoolExecutor
        from apscheduler.events import (
            EVENT_JOB_EXECUTED,
            EVENT_JOB_ERROR,
            EVENT_JOB_MISSED,
            JobEvent,
        )

        jobstores = {
            "default": SQLAlchemyJobStore(
                url="sqlite:///.vb/vermilion_bird.db",
                tablename="apscheduler_jobs",
            )
        }

        executors = {
            "default": ThreadPoolExecutor(max_workers=self._config.max_workers)
        }

        job_defaults = {
            "coalesce": True,
            "max_instances": 3,
        }

        self._scheduler = BackgroundScheduler(
            jobstores=jobstores,
            executors=executors,
            job_defaults=job_defaults,
            timezone=self._config.default_timezone,
        )

        self._scheduler.add_listener(
            self._on_job_event,
            EVENT_JOB_EXECUTED | EVENT_JOB_ERROR | EVENT_JOB_MISSED,
        )

    def start(self):
        """启动调度器"""
        if self._running:
            return

        if self._scheduler:
            self._scheduler.start()
            self._running = True
            logger.info("Scheduler started")

    def shutdown(self, wait: bool = True):
        """关闭调度器

        Args:
            wait: 是否等待正在执行的任务完成
        """
        if not self._running:
            return

        if self._scheduler:
            self._scheduler.shutdown(wait=wait)
            self._running = False
            logger.info("Scheduler shutdown")

    def add_task(self, task: Task) -> str:
        """添加任务到调度器。

        Args:
            task: 要添加的任务

        Returns:
            任务 ID
        """
        self._storage.save_task(task)

        trigger = self._build_trigger(task.trigger_config)

        self._scheduler.add_job(
            self._execute_task,
            trigger=trigger,
            id=task.id,
            args=[task.id],
            name=task.name,
            replace_existing=True,
        )

        if not task.enabled:
            self._scheduler.pause_job(task.id)

        logger.info(f"Task added: {task.id} ({task.name})")
        return task.id

    def remove_task(self, task_id: str) -> bool:
        """从调度器删除任务。

        Args:
            task_id: 任务 ID

        Returns:
            删除成功返回 True，任务不存在返回 False
        """
        try:
            self._scheduler.remove_job(task_id)
            self._storage.delete_task(task_id)
            logger.info(f"Task removed: {task_id}")
            return True
        except Exception as e:
            logger.warning(f"Failed to remove task {task_id}: {e}")
            return False

    def pause_task(self, task_id: str) -> bool:
        """暂停任务。

        Args:
            task_id: 任务 ID

        Returns:
            暂停成功返回 True
        """
        try:
            task = self._storage.load_task(task_id)
            if not task:
                return False

            self._scheduler.pause_job(task_id)
            logger.info(f"Task paused: {task_id}")
            return True
        except Exception as e:
            logger.warning(f"Failed to pause task {task_id}: {e}")
            return False

    def resume_task(self, task_id: str) -> bool:
        """恢复任务。

        Args:
            task_id: 任务 ID

        Returns:
            恢复成功返回 True
        """
        try:
            task = self._storage.load_task(task_id)
            if not task:
                return False

            self._scheduler.resume_job(task_id)
            logger.info(f"Task resumed: {task_id}")
            return True
        except Exception as e:
            logger.warning(f"Failed to resume task {task_id}: {e}")
            return False

    def trigger_task(self, task_id: str) -> bool:
        """手动触发任务立即执行。

        Args:
            task_id: 任务 ID

        Returns:
            触发成功返回 True
        """
        try:
            job = self._scheduler.get_job(task_id)
            if not job:
                return False

            self._scheduler.modify_job(task_id, next_run_time=datetime.now())
            logger.info(f"Task triggered: {task_id}")
            return True
        except Exception as e:
            logger.warning(f"Failed to trigger task {task_id}: {e}")
            return False

    def get_task(self, task_id: str) -> Optional[Task]:
        """获取任务。

        Args:
            task_id: 任务 ID

        Returns:
            任务对象，不存在返回 None
        """
        return self._storage.load_task(task_id)

    def get_all_tasks(self) -> List[Task]:
        """获取所有任务。

        Returns:
            任务列表
        """
        return self._storage.load_all_tasks()

    def _build_trigger(self, trigger_config: dict) -> Any:
        """根据配置构建触发器。

        支持的配置格式：
        - cron: {"cron": "0 0 * * *"} 或 {"cron": "0 0 * * *", "timezone": "UTC"}
        - date: {"date": "2026-04-01 10:00:00"}

        Args:
            trigger_config: 触发器配置

        Returns:
            APScheduler Trigger 对象

        Raises:
            ValueError: 如果触发器配置无效
        """
        from apscheduler.triggers.cron import CronTrigger
        from apscheduler.triggers.date import DateTrigger

        if "cron" in trigger_config:
            cron_expr = trigger_config["cron"]
            parts = cron_expr.split()
            if len(parts) == 5:
                return CronTrigger(
                    minute=parts[0],
                    hour=parts[1],
                    day=parts[2],
                    month=parts[3],
                    day_of_week=parts[4],
                    timezone=trigger_config.get("timezone"),
                )

        if "date" in trigger_config:
            date_str = trigger_config["date"]
            run_date = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
            return DateTrigger(run_date=run_date)

        raise ValueError(
            f"Invalid trigger configuration: {trigger_config}. Supported types: cron, date"
        )

    def _execute_task(self, task_id: str):
        """执行任务（由调度器调用）。

        Args:
            task_id: 任务 ID
        """
        execution_id = str(uuid.uuid4())
        started_at = datetime.now()

        task = self._storage.load_task(task_id)
        if not task:
            logger.error(f"Task not found: {task_id}")
            return

        execution = TaskExecution(
            id=execution_id,
            task_id=task_id,
            status=TaskStatus.RUNNING,
            started_at=started_at,
            retry_count=0,
        )
        self._storage.save_execution(execution)

        try:
            result = self._run_task(task)

            execution.status = TaskStatus.COMPLETED
            execution.finished_at = datetime.now()
            execution.result = result
            self._storage.save_execution(execution)

            logger.info(f"Task completed: {task_id}")

        except Exception as e:
            execution.status = TaskStatus.FAILED
            execution.finished_at = datetime.now()
            execution.error = str(e)
            self._storage.save_execution(execution)

            logger.error(f"Task failed: {task_id} - {e}")

    def _run_task(self, task: Task) -> str:
        """运行任务逻辑。

        Args:
            task: 任务对象

        Returns:
            任务执行结果
        """
        if task.task_type == TaskType.LLM_CHAT:
            return self._run_llm_chat_task(task)
        elif task.task_type == TaskType.SKILL_EXECUTION:
            return self._run_skill_task(task)
        elif task.task_type == TaskType.SYSTEM_MAINTENANCE:
            return self._run_maintenance_task(task)
        else:
            raise ValueError(f"Unknown task type: {task.task_type}")

    def _run_llm_chat_task(self, task: Task) -> str:
        """执行 LLM 聊天任务。

        Args:
            task: 任务对象

        Returns:
            LLM 响应
        """
        params = task.params
        message = params.get("message", "")
        model = params.get("model")

        if model:
            response = self._app.client.chat(message, model=model)
        else:
            response = self._app.client.chat(message)

        return response

    def _run_skill_task(self, task: Task) -> str:
        """执行技能任务。

        Args:
            task: 任务对象

        Returns:
            技能执行结果
        """
        params = task.params
        skill_name = params.get("skill_name")
        skill_params = params.get("params", {})

        skill_manager = self._app.get_skill_manager()
        if not skill_manager:
            raise ValueError("Skill manager not available")

        result = skill_manager.execute_skill(skill_name, **skill_params)
        return str(result) if result else "Skill executed"

    def _run_maintenance_task(self, task: Task) -> str:
        """执行系统维护任务。

        Args:
            task: 任务对象

        Returns:
            维护结果
        """
        params = task.params
        action = params.get("action")

        if action == "cleanup_old_executions":
            days = params.get("days", 30)
            return f"Cleaned up executions older than {days} days"
        elif action == "vacuum_database":
            return "Database vacuumed"
        else:
            return f"Unknown maintenance action: {action}"

    def _on_job_event(self, event: JobEvent):
        """处理任务事件。

        Args:
            event: 任务事件对象
        """
        if event.code == EVENT_JOB_EXECUTED:
            logger.debug(f"Job executed: {event.job_id}")
        elif event.code == EVENT_JOB_ERROR:
            logger.error(f"Job error: {event.job_id} - {event.exception}")
        elif event.code == EVENT_JOB_MISSED:
            logger.warning(f"Job missed: {event.job_id}")
