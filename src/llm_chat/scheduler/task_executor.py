import logging
import time
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Callable, Optional

from llm_chat.runtime import RecoveryPolicy, RunManager, RunStatus, RunType
from llm_chat.scheduler.models import Task, TaskExecution, TaskStatus, TaskType
from llm_chat.work import (
    ArtifactKind,
    ArtifactReviewPolicy,
    WorkItemKind,
    WorkItemService,
)

if TYPE_CHECKING:
    from llm_chat.app import App
    from llm_chat.storage import Storage

logger = logging.getLogger(__name__)


class TaskExecutor:
    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0

    def __init__(
        self,
        app: "App",
        task_storage: "Storage",
        *,
        task_runner: Optional[Callable[[Task, Optional[str]], str]] = None,
        on_complete: Optional[Callable[[Task, str, bool], None]] = None,
    ):
        self.app = app
        self.task_storage = task_storage
        self._task_runner = task_runner
        self._on_complete = on_complete
        candidate = getattr(app, "run_manager", None)
        self.run_manager = candidate if isinstance(candidate, RunManager) else None
        candidate_work_items = getattr(app, "work_items", None)
        self.work_items = (
            candidate_work_items
            if isinstance(candidate_work_items, WorkItemService)
            else None
        )

    def execute(self, task: Task) -> TaskExecution:
        execution_id = str(uuid.uuid4())
        started_at = datetime.now()
        run = None
        work_item = None
        if self.work_items:
            review_policy = self._artifact_review_policy(task)
            work_item = self.work_items.create(
                title=task.name,
                objective=self._work_objective(task),
                kind=WorkItemKind.AUTOMATION,
                conversation_id=(
                    f"scheduled:{task.id}"
                    if task.task_type
                    in {
                        TaskType.LLM_CHAT,
                        TaskType.PROACTIVE_CHAT,
                        TaskType.WEBHOOK,
                    }
                    else None
                ),
                series_key=f"scheduler:{task.id}",
                artifact_review_policy=review_policy,
                metadata={
                    "source": "scheduler",
                    "scheduled_task_id": task.id,
                    "scheduled_task_type": task.task_type.value,
                },
            )
        if self.run_manager:
            run_type = {
                TaskType.WEBHOOK: RunType.WEBHOOK,
                TaskType.PROACTIVE_CHAT: RunType.PROACTIVE,
            }.get(task.task_type, RunType.SCHEDULED)
            run = self.run_manager.start(
                run_type,
                work_item_id=work_item.id if work_item else None,
                input={"task_id": task.id, "params": task.params},
                metadata={
                    "task_name": task.name,
                    "task_type": task.task_type.value,
                    "task_id": task.id,
                    "execution_id": execution_id,
                    "run_handler": "scheduled",
                },
                recovery_policy=RecoveryPolicy.RETRY,
                max_attempts=max(2, task.max_retries + 1),
            )
        return self._execute_existing(
            task,
            execution_id=execution_id,
            started_at=started_at,
            run_id=run.id if run else None,
        )

    def _execute_existing(
        self,
        task: Task,
        *,
        execution_id: str,
        started_at: datetime,
        run_id: Optional[str],
    ) -> TaskExecution:
        if not task.enabled:
            execution = TaskExecution(
                id=execution_id,
                task_id=task.id,
                status=TaskStatus.FAILED,
                started_at=started_at,
                finished_at=datetime.now(),
                result=None,
                error="Task is disabled",
                retry_count=0,
            )
            self.task_storage.save_execution(execution)
            if run_id:
                self.run_manager.fail(run_id, execution.error)
            self._notify(task, execution.error or "Task is disabled", False)
            return execution

        retry_count = 0
        max_attempts = task.max_retries + 1
        last_error: Optional[str] = None
        result: Optional[str] = None

        while retry_count < max_attempts:
            try:
                if self._task_runner is not None:
                    result = self._task_runner(task, run_id)
                elif task.task_type in {
                    TaskType.LLM_CHAT,
                    TaskType.PROACTIVE_CHAT,
                }:
                    result = self._execute_llm_chat(
                        task,
                        parent_run_id=run_id,
                    )
                elif task.task_type == TaskType.WEBHOOK:
                    result = self._execute_webhook(
                        task,
                        parent_run_id=run_id,
                    )
                elif task.task_type == TaskType.SKILL_EXECUTION:
                    result = self._execute_skill(task)
                elif task.task_type == TaskType.SYSTEM_MAINTENANCE:
                    result = self._execute_maintenance(task)
                else:
                    raise ValueError(f"Unknown task type: {task.task_type}")

                execution = TaskExecution(
                    id=execution_id,
                    task_id=task.id,
                    status=TaskStatus.COMPLETED,
                    started_at=started_at,
                    finished_at=datetime.now(),
                    result=result,
                    error=None,
                    retry_count=retry_count,
                )
                self.task_storage.save_execution(execution)
                logger.info(f"Task {task.id} completed successfully after {retry_count} retries")
                if run_id:
                    self.run_manager.complete(run_id, result)
                    self._materialize_result(run_id, result)
                self._notify(task, result or "", True)
                return execution

            except Exception as e:
                last_error = str(e)
                logger.warning(
                    f"Task {task.id} attempt {retry_count + 1}/{max_attempts} failed: {e}"
                )

                retry_count += 1
                if retry_count < max_attempts:
                    delay = min(self.base_delay * (2 ** (retry_count - 1)), self.max_delay)
                    logger.info(f"Retrying task {task.id} in {delay} seconds...")
                    time.sleep(delay)

        execution = TaskExecution(
            id=execution_id,
            task_id=task.id,
            status=TaskStatus.FAILED,
            started_at=started_at,
            finished_at=datetime.now(),
            result=None,
            error=last_error,
            retry_count=retry_count,
        )
        self.task_storage.save_execution(execution)
        logger.error(f"Task {task.id} failed after {retry_count} attempts: {last_error}")
        if run_id:
            self.run_manager.fail(run_id, last_error or "Task execution failed")
        self._notify(task, last_error or "Task execution failed", False)
        return execution

    def retry(self, run_id: str):
        if self.run_manager is None:
            raise ValueError("Scheduled run manager is unavailable")
        run = self.run_manager.get(run_id)
        if run is None:
            raise KeyError(f"Unknown run: {run_id}")
        task = self.task_storage.load_task(str(run.metadata.get("task_id", "")))
        if task is None:
            raise ValueError(f"Scheduled task for run {run_id} no longer exists")
        self.run_manager.retry(run_id)
        self._execute_existing(
            task,
            execution_id=str(uuid.uuid4()),
            started_at=datetime.now(),
            run_id=run_id,
        )
        restored = self.run_manager.get(run_id)
        assert restored is not None
        return restored

    def replay(self, run_id: str):
        if self.run_manager is None:
            raise ValueError("Scheduled run manager is unavailable")
        source = self.run_manager.get(run_id)
        if source is None:
            raise KeyError(f"Unknown run: {run_id}")
        task = self.task_storage.load_task(str(source.metadata.get("task_id", "")))
        if task is None:
            raise ValueError(f"Scheduled task for run {run_id} no longer exists")
        replay = self.run_manager.replay(run_id)
        if self.work_items and replay.work_item_id:
            self.work_items.attach_run(
                replay.work_item_id,
                replay.id,
                make_primary=True,
            )
        self._execute_existing(
            task,
            execution_id=str(uuid.uuid4()),
            started_at=datetime.now(),
            run_id=replay.id,
        )
        restored = self.run_manager.get(replay.id)
        assert restored is not None
        return restored

    def resume(self, run_id: str, value=None):
        raise ValueError(f"Scheduled run {run_id} cannot be resumed; retry it instead")

    @staticmethod
    def can_resume(_run) -> bool:
        return False

    @staticmethod
    def can_retry(run) -> bool:
        return run.status == RunStatus.FAILED

    @staticmethod
    def can_replay(run) -> bool:
        return run.status.terminal

    def _notify(self, task: Task, value: str, success: bool) -> None:
        if self._on_complete is not None:
            self._on_complete(task, value, success)

    @staticmethod
    def _work_objective(task: Task) -> str:
        params = task.params or {}
        return str(
            params.get("message")
            or params.get("action")
            or params.get("tool_name")
            or params.get("skill_name")
            or task.name
        )

    @staticmethod
    def _artifact_review_policy(task: Task) -> ArtifactReviewPolicy:
        value = str(
            (task.params or {}).get(
                "artifact_review_policy",
                ArtifactReviewPolicy.OPTIONAL.value,
            )
        ).strip()
        try:
            return ArtifactReviewPolicy(value)
        except ValueError:
            logger.warning(
                "Unknown artifact review policy %r for scheduled task %s; using optional",
                value,
                task.id,
            )
            return ArtifactReviewPolicy.OPTIONAL

    def _materialize_result(self, run_id: str, result: Optional[str]) -> None:
        if not self.work_items or not result:
            return
        run = self.run_manager.get(run_id) if self.run_manager else None
        if run is None or not run.work_item_id:
            return
        self.work_items.add_artifact(
            run.work_item_id,
            run_id=run.id,
            kind=ArtifactKind.TEXT,
            name="自动任务结果",
            content=str(result),
            content_preview=str(result)[:500],
            idempotency_key=f"{run.id}:scheduled-result",
            metadata={"role": "scheduled_result"},
        )

    def _execute_llm_chat(self, task: Task, parent_run_id: Optional[str] = None) -> str:
        """通过 ChatCore 完整管道执行 LLM 对话 — 包含记忆注入、工具调用、决策卡片。

        使用固定 conversation_id '__scheduled__' 作为所有定时任务的共享会话，
        避免每次触发创建新会话导致上下文碎片化。
        """
        params = task.params
        message = params.get("message", "")
        if not message:
            raise ValueError("LLM_CHAT task requires 'message' in params")

        extra_kwargs = dict(params.get("model_params", {}))
        model = params.get("model")
        temperature = params.get("temperature")
        if model:
            extra_kwargs["model"] = model
        if temperature is not None:
            extra_kwargs["temperature"] = temperature

        # 捕获 LLM 生成的决策卡片
        captured_cards = []

        def on_card(card):
            captured_cards.append(card)

        chat_core = getattr(self.app, "chat_core", None)
        if chat_core is not None:
            chat_kwargs = dict(
                conversation_id=f"scheduled:{task.id}",
                message=message,
                on_card=on_card,
            )
            if parent_run_id:
                chat_kwargs["parent_run_id"] = parent_run_id
            result = chat_core.send_message(**chat_kwargs, **extra_kwargs)
        else:
            result = self.app.client.chat(
                message=message,
                history=params.get("history", []),
                **extra_kwargs,
            )
        result = str(result)

        # 推送决策卡片 (如果有)
        for card in captured_cards:
            self._push_card(task, card)

        # 写入 daily_digest 供历史查询和其他任务复用
        self._save_task_digest(task, message, result)

        return result

    def _execute_webhook(self, task: Task, parent_run_id: Optional[str] = None) -> str:
        """Turn a webhook payload into a regular governed chat request."""
        import json

        params = dict(task.params)
        payload = params.get("webhook_payload", {})
        message = params.get("message", "处理以下 webhook 事件")
        params["message"] = (
            f"{message}\n\nWebhook payload:\n"
            f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
        )
        delegated = task.model_copy(update={"task_type": TaskType.LLM_CHAT, "params": params})
        return self._execute_llm_chat(
            delegated,
            parent_run_id=parent_run_id,
        )

    def _execute_skill(self, task: Task) -> str:
        params = task.params
        skill_name = params.get("skill_name")
        tool_name = params.get("tool_name")
        arguments = params.get("arguments", {})

        # If a specific tool is requested, execute it directly
        if tool_name:
            result = self.app.client.execute_builtin_tool(tool_name, arguments)
            return result

        # If a skill name is provided, try to use SkillManager when available
        if skill_name:
            skill_manager = self.app.client.get_skill_manager()

            # Prefer a dedicated execute_skill API if available on the manager
            execute_skill = getattr(type(skill_manager), "execute_skill", None)
            if callable(execute_skill):
                result = skill_manager.execute_skill(skill_name, arguments)
                return result

            skill = skill_manager.get_skill(skill_name)
            from llm_chat.skills.base import BaseSkill

            if not isinstance(skill, BaseSkill):
                raise ValueError(f"Skill not found: {skill_name}")
            tools = skill.get_tools()
            if not tools:
                raise ValueError(f"Skill {skill_name} has no tools")
            first_tool = tools[0]
            result = self.app.client.execute_builtin_tool(first_tool.name, arguments)
            return result

        raise ValueError("Skill task must specify either tool_name or skill_name")

    def _execute_maintenance(self, task: Task) -> str:
        params = task.params
        action = params.get("action", "")

        if action == "cleanup_memory":
            max_days = params.get("max_days", 30)
            self._cleanup_memory(max_days)
            return f"Memory cleanup completed (max_days={max_days})"

        if action == "archive_sessions":
            days_old = params.get("days_old", 7)
            self._archive_old_sessions(days_old)
            return f"Session archival completed (days_old={days_old})"

        if action == "compress_mid_term":
            max_days = params.get("max_days", 30)
            self._compress_mid_term_memory(max_days)
            return f"Mid-term memory compression completed (max_days={max_days})"

        if action == "evolve_understanding":
            self._evolve_understanding()
            return "Understanding evolution completed"

        return f"Unsupported maintenance action: {action}"

    def _cleanup_memory(self, max_days: int):
        try:
            conversation_manager = getattr(self.app, "conversation_manager", None)
            if conversation_manager is None:
                logger.warning("No conversation manager available for memory cleanup")
                return

            memory_manager = getattr(conversation_manager, "_memory_manager", None)
            if memory_manager is None:
                logger.warning("No memory manager available for cleanup")
                return

            memory_manager.compress_mid_term(max_days)
            logger.info(f"Memory cleanup completed with max_days={max_days}")
        except Exception as e:
            logger.error(f"Memory cleanup failed: {e}")
            raise

    def _archive_old_sessions(self, days_old: int):
        try:
            conversations = self.app.storage.list_conversations(limit=1000)
            cutoff_date = datetime.now()
            archived_count = 0

            for conv in conversations:
                updated_at_str = conv.get("updated_at")
                if not updated_at_str:
                    continue

                try:
                    updated_at = datetime.fromisoformat(updated_at_str)
                    age_days = (cutoff_date - updated_at).days

                    if age_days > days_old:
                        conversation_manager = getattr(self.app, "conversation_manager", None)
                        if conversation_manager:
                            memory_manager = getattr(conversation_manager, "_memory_manager", None)
                            if memory_manager:
                                memory_manager.archive_session(conv["id"])
                                archived_count += 1
                except (ValueError, TypeError):
                    continue

            logger.info(f"Archived {archived_count} old sessions")
        except Exception as e:
            logger.error(f"Session archival failed: {e}")
            raise

    def _compress_mid_term_memory(self, max_days: int):
        try:
            conversation_manager = getattr(self.app, "conversation_manager", None)
            if conversation_manager is None:
                logger.warning("No conversation manager available for memory compression")
                return

            memory_manager = getattr(conversation_manager, "_memory_manager", None)
            if memory_manager is None:
                logger.warning("No memory manager available for compression")
                return

            memory_manager.compress_mid_term(max_days)
            logger.info(f"Mid-term memory compression completed with max_days={max_days}")
        except Exception as e:
            logger.error(f"Memory compression failed: {e}")
            raise

    def _evolve_understanding(self):
        try:
            conversation_manager = getattr(self.app, "conversation_manager", None)
            if conversation_manager is None:
                logger.warning("No conversation manager available for understanding evolution")
                return

            memory_manager = getattr(conversation_manager, "_memory_manager", None)
            if memory_manager is None:
                logger.warning("No memory manager available for evolution")
                return

            memory_manager.evolve_understanding()
            logger.info("Understanding evolution completed")
        except Exception as e:
            logger.error(f"Understanding evolution failed: {e}")
            raise

    def _save_task_digest(self, task: Task, prompt: str, result: str):
        """任务执行后写入 daily_digest，供历史查询和其他任务复用。

        每天每个任务只保留最新一条（INSERT OR REPLACE 按 date 覆盖）。
        """
        if not result or not result.strip():
            return

        try:
            from datetime import date

            today = date.today().isoformat()
            summary = result[:300].replace("\n", " ")
            self.app.storage.save_digest(
                digest_date=today,
                items=[
                    {
                        "title": task.name,
                        "summary": summary,
                        "source": "scheduled_task",
                        "source_url": "",
                        "relevance": task.id,
                    }
                ],
                raw_context=prompt,
                source=task.name,
            )
            logger.debug(f"Digest saved for task '{task.name}'")
        except Exception as e:
            logger.warning(f"Failed to save task digest: {e}")

    def _push_card(self, task, card):
        """推送决策卡片到 GUI 和飞书。

        分别尝试两个通道，失败不影响另一个。
        """
        card_title = getattr(card, "title", "") or ""
        logger.info(f"[{task.name}] 推送卡片: {card_title}")

        # 1. GUI 推送
        try:
            frontend = getattr(self.app, "current_frontend", None)
            if frontend and frontend.name == "gui":
                signals = getattr(frontend, "_card_signals", None)
                if signals:
                    card.conversation_id = None  # 定时任务推送 → 新建会话
                    signals.card_created.emit(card)
                    logger.info(f"[{task.name}] 卡片已推送到 GUI")
        except Exception as e:
            logger.warning(f"[{task.name}] GUI 推送失败: {e}")

        # 2. 飞书推送
        try:
            feishu_cfg = getattr(self.app.config, "feishu", None)
            if not feishu_cfg or not getattr(feishu_cfg, "enabled", False):
                return
            adapter = getattr(self.app, "_feishu_adapter", None)
            if adapter is None:
                return

            recent = adapter.get_recent_chat()
            if not recent or recent.get("type") != "feishu":
                try:
                    recent = self.app.storage.get_recent_feishu_chat()
                except Exception:
                    pass
            if not recent:
                return

            receive_id = recent.get("chat_id") or recent.get("open_id") or recent.get("user_id")
            receive_id_type = (
                "chat_id"
                if "chat_id" in recent
                else "open_id"
                if "open_id" in recent
                else "user_id"
            )
            if not receive_id:
                return

            # 构建文本摘要
            lines = [f"💡 {card_title}"]
            context = getattr(card, "context", "") or ""
            if context:
                lines.append(f"  {context}")
            for opt in getattr(card, "options", []) or []:
                rec = "✅" if getattr(opt, "id", "") == getattr(card, "recommendation", "") else "  "
                lines.append(f"{rec} 选{opt.id}: {opt.label}")

            adapter.send_message(
                receive_id=receive_id,
                msg_type="text",
                content={"text": "\n".join(lines)},
                receive_id_type=receive_id_type,
            )
            logger.info(f"[{task.name}] 卡片已推送到飞书")
        except Exception as e:
            logger.warning(f"[{task.name}] 飞书推送失败: {e}")
