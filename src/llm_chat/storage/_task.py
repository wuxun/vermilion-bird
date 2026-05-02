"""Task/Execution persistence operations (tasks / task_executions 表)"""

import json
import logging
from datetime import datetime
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from llm_chat.scheduler.models import Task, TaskExecution, TaskType, TaskStatus

logger = logging.getLogger(__name__)


class StorageTaskMixin:
    """任务和执行的 CRUD 操作"""

    # ------------------------------------------------------------------
    # Tasks
    # ------------------------------------------------------------------

    def save_task(self, task: "Task") -> str:
        from llm_chat.scheduler.models import TaskType

        with self._get_connection() as conn:
            trigger_config = (
                json.dumps(task.trigger_config)
                if task.trigger_config is not None
                else json.dumps({})
            )
            params = (
                json.dumps(task.params)
                if task.params is not None
                else json.dumps({})
            )
            created_at = (
                task.created_at.isoformat()
                if hasattr(task, "created_at")
                else None
            )
            updated_at = (
                task.updated_at.isoformat()
                if hasattr(task, "updated_at")
                else None
            )
            notify_targets = getattr(task, "notify_targets", None)
            notify_targets_json = (
                json.dumps(notify_targets) if notify_targets else None
            )
            conn.execute(
                "INSERT OR REPLACE INTO tasks "
                "(id, name, task_type, trigger_config, params, enabled, "
                "max_retries, notify_enabled, notify_targets, "
                "notify_on_success, notify_on_failure, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    task.id,
                    task.name,
                    task.task_type.value
                    if isinstance(task.task_type, TaskType)
                    else str(task.task_type),
                    trigger_config,
                    params,
                    int(getattr(task, "enabled", True)),
                    int(getattr(task, "max_retries", 3)),
                    int(getattr(task, "notify_enabled", True)),
                    notify_targets_json,
                    int(getattr(task, "notify_on_success", True)),
                    int(getattr(task, "notify_on_failure", True)),
                    created_at,
                    updated_at,
                ),
            )
            return task.id

    def load_task(self, task_id: str) -> Optional["Task"]:
        from llm_chat.scheduler.models import Task, TaskType

        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
            if not row:
                return None
            trigger_config = (
                json.loads(row["trigger_config"])
                if row["trigger_config"]
                else {}
            )
            params = json.loads(row["params"]) if row["params"] else {}
            created_at = (
                datetime.fromisoformat(row["created_at"])
                if row["created_at"]
                else None
            )
            updated_at = (
                datetime.fromisoformat(row["updated_at"])
                if row["updated_at"]
                else None
            )
            notify_targets = None
            if "notify_targets" in row.keys() and row["notify_targets"]:
                try:
                    notify_targets = json.loads(row["notify_targets"])
                except (json.JSONDecodeError, TypeError):
                    pass
            row_dict = dict(row)
            return Task(
                id=row_dict["id"],
                name=row_dict["name"],
                task_type=TaskType(row_dict["task_type"])
                if isinstance(row_dict["task_type"], str)
                else row_dict["task_type"],
                trigger_config=trigger_config,
                params=params,
                enabled=bool(row_dict["enabled"]),
                max_retries=row_dict["max_retries"]
                if row_dict["max_retries"] is not None
                else 3,
                created_at=created_at,
                updated_at=updated_at,
                notify_enabled=bool(row_dict.get("notify_enabled", True)),
                notify_targets=notify_targets,
                notify_on_success=bool(row_dict.get("notify_on_success", True)),
                notify_on_failure=bool(row_dict.get("notify_on_failure", True)),
            )

    def load_all_tasks(self) -> List["Task"]:
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM tasks ORDER BY updated_at DESC"
            ).fetchall()
            tasks: list = []
            for row in rows:
                t = self.load_task(row["id"])
                if t:
                    tasks.append(t)
            return tasks

    def delete_task(self, task_id: str) -> bool:
        with self._get_connection() as conn:
            conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            return True

    # ------------------------------------------------------------------
    # Executions
    # ------------------------------------------------------------------

    def save_execution(self, execution: "TaskExecution") -> str:
        from llm_chat.scheduler.models import TaskStatus

        with self._get_connection() as conn:
            started_at = (
                execution.started_at.isoformat()
                if isinstance(execution.started_at, datetime)
                else None
            )
            finished_at = (
                execution.finished_at.isoformat()
                if isinstance(execution.finished_at, datetime)
                else None
            )
            status = (
                execution.status.value
                if isinstance(execution.status, TaskStatus)
                else str(execution.status)
            )
            conn.execute(
                "INSERT OR REPLACE INTO task_executions "
                "(id, task_id, status, started_at, finished_at, "
                "result, error, retry_count) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    execution.id,
                    execution.task_id,
                    status,
                    started_at,
                    finished_at,
                    execution.result,
                    execution.error,
                    getattr(execution, "retry_count", 0),
                ),
            )
            return execution.id

    def load_executions(
        self, task_id: str, limit: int = 100
    ) -> List["TaskExecution"]:
        from llm_chat.scheduler.models import TaskExecution, TaskStatus

        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM task_executions "
                "WHERE task_id = ? ORDER BY started_at DESC LIMIT ?",
                (task_id, limit),
            ).fetchall()
            executions: list = []
            for row in rows:
                started_at = (
                    datetime.fromisoformat(row["started_at"])
                    if row["started_at"]
                    else None
                )
                finished_at = (
                    datetime.fromisoformat(row["finished_at"])
                    if row["finished_at"]
                    else None
                )
                exec_obj = TaskExecution(
                    id=row["id"],
                    task_id=row["task_id"],
                    status=TaskStatus(row["status"])
                    if isinstance(row["status"], str)
                    else row["status"],
                    started_at=started_at,
                    finished_at=finished_at,
                    result=row["result"],
                    error=row["error"],
                    retry_count=row["retry_count"]
                    if row["retry_count"] is not None
                    else 0,
                )
                executions.append(exec_obj)
            return executions
