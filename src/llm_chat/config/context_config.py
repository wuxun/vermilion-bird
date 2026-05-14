"""上下文管理配置。"""

from __future__ import annotations

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


class ContextConfig(BaseSettings):
    """上下文管理配置。"""

    enabled: bool = Field(default=True, description="是否启用上下文管理")
    reserve_tokens: int = Field(
        default=1024, description="为系统提示和回复预留的token数量"
    )
    enable_cache: bool = Field(default=True, description="是否启用上下文缓存")
    auto_prune_cache: bool = Field(default=True, description="是否自动清理过期缓存")
    keep_recent_tool_results: int = Field(
        default=2, description="微压缩时保留最近的工具结果数量"
    )
    keep_recent_dialog_rounds: int = Field(
        default=3, description="自动压缩时保留最近的对话轮次"
    )
    auto_compact_threshold: float = Field(
        default=0.8,
        description="自动压缩触发阈值，0-1之间，超过max_context_tokens*阈值时触发自动压缩",
    )

    class Config:
        env_prefix = "CONTEXT_"
        case_sensitive = False
        extra = "allow"

    @field_validator("auto_compact_threshold")
    @classmethod
    def validate_threshold(cls, v: float) -> float:
        if v < 0 or v > 1:
            raise ValueError(f"自动压缩阈值必须在0-1之间，得到: {v}")
        return v
