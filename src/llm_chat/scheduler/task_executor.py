import logging
import time
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from llm_chat.scheduler.models import Task, TaskExecution, TaskStatus, TaskType

if TYPE_CHECKING:
    from llm_chat.app import App
    from llm_chat.storage import Storage

logger = logging.getLogger(__name__)


class TaskExecutor:
    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0

    def __init__(self, app: "App", task_storage: "Storage"):
        self.app = app
        self.task_storage = task_storage

    def execute(self, task: Task) -> TaskExecution:
        execution_id = str(uuid.uuid4())
        started_at = datetime.now()

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
            return execution

        retry_count = 0
        max_attempts = task.max_retries + 1
        last_error: Optional[str] = None
        result: Optional[str] = None

        while retry_count < max_attempts:
            try:
                if task.task_type == TaskType.LLM_CHAT:
                    result = self._execute_llm_chat(task)
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
                logger.info(
                    f"Task {task.id} completed successfully after {retry_count} retries"
                )
                return execution

            except Exception as e:
                last_error = str(e)
                logger.warning(
                    f"Task {task.id} attempt {retry_count + 1}/{max_attempts} failed: {e}"
                )

                retry_count += 1
                if retry_count < max_attempts:
                    delay = min(
                        self.base_delay * (2 ** (retry_count - 1)), self.max_delay
                    )
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
        logger.error(
            f"Task {task.id} failed after {retry_count} attempts: {last_error}"
        )
        return execution

    def _execute_llm_chat(self, task: Task) -> str:
        params = task.params
        # Required: user message
        message = params.get("message", "")
        # Optional: historical context for multi-turn conversations
        history = params.get("history", [])
        # Optional: specify model to use
        model = params.get("model", None)

        # Collect extra kwargs from model_params
        extra_kwargs = {}
        if model is not None:
            extra_kwargs["model"] = model
        if "model_params" in params:
            model_params = params["model_params"] or {}
            if "temperature" in model_params:
                extra_kwargs["temperature"] = model_params["temperature"]
            if "max_tokens" in model_params:
                extra_kwargs["max_tokens"] = model_params["max_tokens"]

        result = self.app.client.chat(
            message=message,
            history=history,
            **extra_kwargs,
        )
        return result

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
            if hasattr(skill_manager, "execute_skill"):
                result = skill_manager.execute_skill(skill_name, arguments)
                return result

            skill = skill_manager.get_skill(skill_name)
            if skill is None:
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
                        conversation_manager = getattr(
                            self.app, "conversation_manager", None
                        )
                        if conversation_manager:
                            memory_manager = getattr(
                                conversation_manager, "_memory_manager", None
                            )
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
                logger.warning(
                    "No conversation manager available for memory compression"
                )
                return

            memory_manager = getattr(conversation_manager, "_memory_manager", None)
            if memory_manager is None:
                logger.warning("No memory manager available for compression")
                return

            memory_manager.compress_mid_term(max_days)
            logger.info(
                f"Mid-term memory compression completed with max_days={max_days}"
            )
        except Exception as e:
            logger.error(f"Memory compression failed: {e}")
            raise

    def _evolve_understanding(self):
        try:
            conversation_manager = getattr(self.app, "conversation_manager", None)
            if conversation_manager is None:
                logger.warning(
                    "No conversation manager available for understanding evolution"
                )
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
