from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional, Dict

from pydantic import BaseModel


class TaskType(str, Enum):
    LLM_CHAT = "LLM_CHAT"
    SKILL_EXECUTION = "SKILL_EXECUTION"
    SYSTEM_MAINTENANCE = "SYSTEM_MAINTENANCE"


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class Task(BaseModel):
    id: str
    name: str
    task_type: TaskType
    trigger_config: Dict
    params: Dict
    enabled: bool
    max_retries: int = 3
    created_at: datetime
    updated_at: datetime
    # 通知配置
    notify_enabled: bool = True
    notify_targets: Optional[list] = (
        None  # 通知目标列表，如 [{"type": "feishu", "chat_id": "oc_xxx"}]
    )
    notify_on_success: bool = True
    notify_on_failure: bool = True


class TaskExecution(BaseModel):
    id: str
    task_id: str
    status: TaskStatus
    started_at: datetime
    finished_at: Optional[datetime] = None
    result: Optional[str] = None
    error: Optional[str] = None
    retry_count: int
