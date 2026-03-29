"""Scheduler module - 任务调度系统

提供定时任务调度和执行功能。
"""

from .models import TaskType, TaskStatus, Task, TaskExecution
from .task_executor import TaskExecutor

# Lazy import SchedulerService to avoid loading apscheduler during module import
# This is necessary for Python 3.14 compatibility (pkg_resources deprecated)
_SchedulerService = None


def __getattr__(name: str):
    """Lazy import for SchedulerService to avoid apscheduler dependency at module import time.

    This is critical for Python 3.14 compatibility because:
    1. APScheduler's BackgroundScheduler imports SQLAlchemyJobStore at module level
    2. SQLAlchemyJobStore depends on pkg_resources (deprecated in Python 3.14)
    3. We use delayed import in scheduler.py, but that doesn't help if __init__.py imports it directly

    By using lazy import here, we ensure apscheduler is only loaded when SchedulerService is actually used.
    """
    if name == "SchedulerService":
        global _SchedulerService
        if _SchedulerService is None:
            from .scheduler import SchedulerService

            _SchedulerService = SchedulerService
        return _SchedulerService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "TaskType",
    "TaskStatus",
    "Task",
    "TaskExecution",
    "SchedulerService",
    "TaskExecutor",
]
