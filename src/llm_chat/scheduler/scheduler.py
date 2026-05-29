"""SchedulerService - 调度器核心服务

使用 APScheduler 3.x 实现任务调度功能。
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional, List, Callable, Any, Dict

# APScheduler imports are delayed to avoid pkg_resources dependency at module load time
# This is critical for Python 3.14 compatibility (pkg_resources deprecated)

from .models import Task, TaskType, TaskStatus, TaskExecution

if TYPE_CHECKING:
    from apscheduler.schedulers.background import BackgroundScheduler
    from llm_chat.config import SchedulerConfig
    from llm_chat.storage import Storage
    from llm_chat.app import App


logger = logging.getLogger(__name__)


class SchedulerService:
    """调度器服务，管理定时任务的调度和执行。

    使用 APScheduler BackgroundScheduler + ThreadPoolExecutor，
    支持 cron、date 两种触发器类型。

    使用类级注册表 _instances 替代模块级全局变量，
    避免 job wrapper 的跨模块状态污染。
    """

    _instances: Dict[str, "SchedulerService"] = {}

    @classmethod
    def _get_instance(cls, scheduler_id: str) -> Optional["SchedulerService"]:
        return cls._instances.get(scheduler_id)

    @classmethod
    def _job_wrapper(cls, task_id: str, scheduler_id: str):
        """类方法 job 包装 — 避免绑定方法的 pickle 问题。"""
        scheduler = cls._instances.get(scheduler_id)
        if scheduler:
            scheduler._execute_task(task_id)
        else:
            logger.error(f"Scheduler instance not found: {scheduler_id}")
            if cls._instances:
                scheduler = next(iter(cls._instances.values()))
                scheduler._execute_task(task_id)

    @property
    def name(self) -> str:
        """服务名称"""
        return "scheduler"

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
        # Use string annotation to avoid importing BackgroundScheduler at module load time
        self._scheduler: Optional["BackgroundScheduler"] = None
        self._running = False
        # 生成唯一的 scheduler ID 用于注册表
        self._scheduler_id = str(uuid.uuid4())
        # 立即注册到全局注册表
        SchedulerService._instances[self._scheduler_id] = self

        self._setup_scheduler()

        # Webhook 事件驱动触发器
        self._webhook_server: Optional[WebhookServer] = None
        webhook_enabled = getattr(config, 'webhook_enabled', False)
        webhook_port = getattr(config, 'webhook_port', 9100)
        if webhook_enabled:
            from .webhook import WebhookServer
            self._webhook_server = WebhookServer(port=webhook_port)
            logger.info(
                f"Webhook server configured on port {webhook_port}"
            )

    def _get_notification_service(self):
        """动态创建通知服务"""
        from .notification import NotificationService

        return NotificationService(self._app, self._app.config)

    def _setup_scheduler(self):
        """配置调度器组件"""
        # 延迟导入以避免在模块加载时触发 pkg_resources 依赖
        # Critical: Import pkg_resources shim BEFORE importing apscheduler to ensure it's in sys.modules
        # This is necessary for Python 3.14 compatibility (pkg_resources deprecated)
        import llm_chat.pkg_resources  # noqa: F401

        from apscheduler.schedulers.background import BackgroundScheduler
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
                url="sqlite:///" + os.path.expanduser("~/.vermilion-bird/vermilion_bird.db"),
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

        # 启动 webhook 服务器
        if self._webhook_server:
            self._webhook_server.start()
            # 注册已存在的 webhook 任务
            self._register_webhook_tasks()

    def shutdown(self, wait: bool = True):
        """关闭调度器

        Args:
            wait: 是否等待正在执行的任务完成
        """
        if not self._running and not self._webhook_server:
            return

        # 停止 webhook 服务器
        if self._webhook_server:
            self._webhook_server.stop()

        if self._scheduler:
            self._scheduler.shutdown(wait=wait)
            # 从全局注册表移除
            if self._scheduler_id in SchedulerService._instances:
                del SchedulerService._instances[self._scheduler_id]
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

        # Webhook 任务：注册到 webhook 服务器
        if task.task_type == TaskType.WEBHOOK:
            if self._webhook_server and self._webhook_server.is_running:
                secret = task.trigger_config.get("secret")
                self._webhook_server.register_task(
                    task.id,
                    callback=lambda tid, payload: self._execute_webhook_task(tid, payload),
                    secret=secret,
                )
            logger.info(f"Webhook task registered: {task.id} ({task.name})")
            return task.id

        # 常规任务：注册到 APScheduler
        trigger = self._build_trigger(task.trigger_config)

        self._scheduler.add_job(
            SchedulerService._job_wrapper,
            trigger=trigger,
            id=task.id,
            args=[task.id, self._scheduler_id],
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
        # 首先检查任务是否存在于存储中
        task = self._storage.load_task(task_id)
        if not task:
            logger.debug(f"Task not found in storage: {task_id}")
            return False

        # Webhook 任务：从 webhook 服务器注销
        if task.task_type == TaskType.WEBHOOK and self._webhook_server:
            self._webhook_server.unregister_task(task_id)

        # 尝试从调度器删除（任务可能已不存在，如一次性触发任务）
        try:
            self._scheduler.remove_job(task_id)
            logger.debug(f"Job removed from scheduler: {task_id}")
        except Exception as e:
            logger.debug(f"Job not found in scheduler (continuing): {task_id} - {e}")

        # 从存储删除
        try:
            self._storage.delete_task(task_id)
            logger.info(f"Task removed: {task_id}")
            return True
        except Exception as e:
            logger.warning(f"Failed to delete task from storage {task_id}: {e}")
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
        # 首先检查任务是否存在于存储中
        task = self._storage.load_task(task_id)
        if not task:
            logger.debug(f"Task not found in storage: {task_id}")
            return False

        try:
            # 尝试获取 job
            job = self._scheduler.get_job(task_id)
            if job:
                # Job 存在，使用 modify_job 立即执行
                self._scheduler.modify_job(task_id, next_run_time=datetime.now())
                logger.info(f"Task triggered (existing job): {task_id}")
                return True
            else:
                # Job 不存在（可能是已执行的一次性任务），直接调用执行方法
                logger.debug(
                    f"Job not found in scheduler, executing directly: {task_id}"
                )
                # 在新线程中执行任务以避免阻塞 UI
                import threading

                thread = threading.Thread(
                    target=self._execute_task, args=(task_id,), daemon=True
                )
                thread.start()
                logger.info(f"Task triggered (direct execution): {task_id}")
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
            run_date = self._parse_datetime(date_str)
            return DateTrigger(run_date=run_date)

        raise ValueError(
            f"Invalid trigger configuration: {trigger_config}. Supported types: cron, date"
        )

    def _parse_datetime(self, date_str: str) -> datetime:
        formats = [
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%Y-%m-%d",
        ]
        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue
        raise ValueError(
            f"无法解析时间格式: {date_str}，支持的格式: YYYY-MM-DD HH:MM:SS 或 ISO 格式"
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
            self._notify_task_completion(task, result, success=True)

        except Exception as e:
            execution.status = TaskStatus.FAILED
            execution.finished_at = datetime.now()
            execution.error = str(e)
            self._storage.save_execution(execution)

            logger.error(f"Task failed: {task_id} - {e}")
            self._notify_task_completion(task, str(e), success=False)

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
        elif task.task_type == TaskType.PROACTIVE_CHAT:
            return self._run_proactive_chat_task(task)
        else:
            raise ValueError(f"Unknown task type: {task.task_type}")

    def _run_llm_chat_task(self, task: Task) -> str:
        """执行 LLM 聊天任务，通过 ChatCore 完整管道。"""
        params = task.params
        message = params.get("message", "")
        if not message:
            return "No message provided"

        model = params.get("model")
        temperature = params.get("temperature")
        conversation_id = f"scheduled:{task.id}"

        chat_core = self._app.chat_core
        if chat_core is None:
            logger.warning("ChatCore unavailable, falling back to direct client.chat")
            result = self._app.client.chat(message, **({"model": model} if model else {}))
            return result

        # 捕获决策卡片
        captured_cards = []
        def on_card(card):
            captured_cards.append(card)

        extra_kwargs = {}
        if model:
            extra_kwargs["model"] = model
        if temperature is not None:
            extra_kwargs["temperature"] = temperature

        result = chat_core.send_message(
            conversation_id,
            message,
            on_card=on_card,
            **extra_kwargs,
        )

        # 暂存卡片，由 _notify_task_completion 统一推送（受 notify_enabled 控制）
        self._pending_cards = captured_cards

        # 写入 daily_digest
        self._save_task_digest(task, message, result)

        return result

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

    def _notify_task_completion(self, task: Task, result: str, success: bool = True):
        """统一通知入口：检查 notify_enabled，推动态卡或发完成文本。"""
        if not getattr(task, "notify_enabled", True):
            logger.debug(f"[{task.name}] 通知已禁用，跳过")
            return

        pending_cards = getattr(self, "_pending_cards", None) or []
        self._pending_cards = []

        if pending_cards:
            # 有决策卡片 → 只推卡片，不发完成文本
            for card in pending_cards:
                self._push_task_card(task, card)
            return

        # 无卡片 → 发通用完成/失败通知
        self._send_completion_text(task, result, success)

    def _send_completion_text(self, task, result: str, success: bool):
        """发送通用完成/失败文本通知到前端和飞书。"""
        try:
            from llm_chat.frontends.base import Message, MessageType

            frontend = self._app.current_frontend
            if frontend:
                status = "✅" if success else "❌"
                content = (
                    f"{status} **定时任务完成**: {task.name}\n\n{result}"
                    if success
                    else f"{status} **定时任务失败**: {task.name}\n\n错误: {result}"
                )
                message = Message(
                    content=content,
                    role="assistant",
                    msg_type=MessageType.TEXT,
                    metadata={"task_id": task.id, "is_notification": True},
                )
                frontend.display_message(message)

            notification_service = self._get_notification_service()
            notification_service.send_notification(task, result, success)
        except Exception as e:
            logger.error(f"Failed to send completion text: {e}")

    def _on_job_event(self, event):
        """处理任务事件。

        Args:
            event: 任务事件对象
        """
        from apscheduler.events import (
            EVENT_JOB_EXECUTED,
            EVENT_JOB_ERROR,
            EVENT_JOB_MISSED,
        )

        if event.code == EVENT_JOB_EXECUTED:
            logger.debug(f"Job executed: {event.job_id}")
        elif event.code == EVENT_JOB_ERROR:
            logger.error(f"Job error: {event.job_id} - {event.exception}")
        elif event.code == EVENT_JOB_MISSED:
            logger.warning(f"Job missed: {event.job_id}")

    # ------------------------------------------------------------------
    # Webhook 事件驱动触发器
    # ------------------------------------------------------------------

    def _register_webhook_tasks(self):
        """将数据库中已存在的 webhook 任务注册到 webhook 服务器。"""
        if not self._webhook_server:
            return

        tasks = self._storage.get_all_tasks()
        for task in tasks:
            if task.task_type == TaskType.WEBHOOK and task.enabled:
                secret = task.trigger_config.get("secret")
                self._webhook_server.register_task(
                    task.id,
                    callback=lambda tid, payload, t=task: self._execute_webhook_task(tid, payload),
                    secret=secret,
                )
        logger.info(f"Registered {sum(1 for t in tasks if t.task_type == TaskType.WEBHOOK and t.enabled)} webhook tasks")

    def _execute_webhook_task(self, task_id: str, payload: dict):
        """执行 webhook 触发的任务。

        Args:
            task_id: 任务 ID
            payload: webhook 请求的 JSON body
        """
        task = self._storage.load_task(task_id)
        if not task:
            logger.warning(f"Webhook task not found: {task_id}")
            return

        # 注入 webhook payload 到 task params
        task.params["webhook_payload"] = payload

        # 直接执行 (webhook 不需要 APScheduler job)
        self._execute_task(task_id)

    def get_webhook_info(self) -> Optional[dict]:
        """获取 webhook 服务器状态信息。"""
        if self._webhook_server:
            return self._webhook_server.get_status()
        return None

    def _push_task_card(self, task, card):
        """推送决策卡片到 GUI 和飞书。"""
        card_title = getattr(card, "title", "") or ""
        logger.info(f"[{task.name}] 推送卡片: {card_title}")

        # GUI
        try:
            frontend = getattr(self._app, "current_frontend", None)
            if frontend and frontend.name == "gui":
                signals = getattr(frontend, "_card_signals", None)
                if signals:
                    signals.card_created.emit(card)
        except Exception as e:
            logger.warning(f"[{task.name}] GUI 推送失败: {e}")

        # 飞书
        try:
            feishu_cfg = getattr(self._app.config, "feishu", None)
            if not feishu_cfg or not getattr(feishu_cfg, "enabled", False):
                return
            adapter = getattr(self._app, "_feishu_adapter", None)
            if adapter is None:
                return
            recent = adapter.get_recent_chat()
            if not recent or recent.get("type") != "feishu":
                try:
                    recent = self._app.storage.get_recent_feishu_chat()
                except Exception:
                    pass
            if not recent:
                return
            receive_id = (
                recent.get("chat_id") or recent.get("open_id")
                or recent.get("user_id")
            )
            receive_id_type = (
                "chat_id" if "chat_id" in recent
                else "open_id" if "open_id" in recent else "user_id"
            )
            if not receive_id:
                return
            lines = [f"💡 {card_title}"]
            context = getattr(card, "context", "") or ""
            if context:
                lines.append(f"  {context}")
            for opt in getattr(card, "options", []) or []:
                rec = (
                    "✅" if getattr(opt, "id", "") == getattr(card, "recommendation", "")
                    else "  "
                )
                lines.append(f"{rec} 选{opt.id}: {opt.label}")
            adapter.send_message(
                receive_id=receive_id,
                msg_type="text",
                content={"text": "\n".join(lines)},
                receive_id_type=receive_id_type,
            )
        except Exception as e:
            logger.warning(f"[{task.name}] 飞书推送失败: {e}")

    def _save_task_digest(self, task, prompt: str, result: str):
        """任务执行后写入 daily_digest。"""
        if not result or not result.strip():
            return
        try:
            from datetime import date
            today = date.today().isoformat()
            summary = result[:300].replace("\n", " ")
            self._app.storage.save_digest(
                digest_date=today,
                items=[{
                    "title": task.name,
                    "summary": summary,
                    "source": "scheduled_task",
                    "source_url": "",
                    "relevance": task.id,
                }],
                raw_context=prompt,
                source=task.name,
            )
        except Exception as e:
            logger.warning(f"Failed to save task digest: {e}")
