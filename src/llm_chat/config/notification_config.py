"""任务通知配置。"""

from __future__ import annotations

from typing import Optional, List, Dict, Any
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


class NotificationConfig(BaseSettings):
    """任务通知配置。"""

    enabled: bool = Field(default=True, description="是否启用通知")
    # 默认通知目标（可以在任务级别覆盖）
    default_targets: Optional[List[Dict[str, Any]]] = Field(
        default=None, description="默认通知目标列表"
    )
    # 飞书通知相关配置
    feishu: Optional[Dict[str, Any]] = Field(default=None, description="飞书通知配置")

    @field_validator("default_targets")
    @classmethod
    def validate_default_targets(
        cls, v: Optional[List[Dict[str, Any]]]
    ) -> Optional[List[Dict[str, Any]]]:
        if v is not None:
            for target in v:
                if "type" not in target:
                    raise ValueError("每个通知目标必须包含 'type' 字段")
        return v
