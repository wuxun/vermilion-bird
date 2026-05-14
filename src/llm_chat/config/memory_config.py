"""记忆系统配置。"""

from __future__ import annotations

from typing import List
from pydantic import Field
from pydantic_settings import BaseSettings


class ShortTermMemoryConfig(BaseSettings):
    """短期记忆配置。"""

    max_items: int = Field(default=10, description="短期记忆最大条目数")

    class Config:
        env_prefix = "MEMORY_SHORT_TERM_"
        case_sensitive = False


class MidTermMemoryConfig(BaseSettings):
    """中期记忆配置。"""

    max_days: int = Field(default=30, description="中期记忆保留天数")
    compress_after_days: int = Field(default=7, description="多少天后压缩记忆")

    class Config:
        env_prefix = "MEMORY_MID_TERM_"
        case_sensitive = False


class LongTermMemoryConfig(BaseSettings):
    """长期记忆配置。"""

    auto_evolve: bool = Field(default=True, description="是否自动进化记忆")
    evolve_interval_days: int = Field(default=7, description="记忆进化间隔天数")
    consolidate_min_facts: int = Field(
        default=8, description="累积多少条事实后触发长期记忆去重整理"
    )
    consolidate_interval_secs: int = Field(
        default=600, description="长期记忆整理最小间隔秒数 (防频繁调用 LLM)"
    )

    class Config:
        env_prefix = "MEMORY_LONG_TERM_"
        case_sensitive = False


class MemoryConfig(BaseSettings):
    """记忆系统总配置。"""

    enabled: bool = Field(default=True, description="是否启用记忆系统")
    storage_dir: str = Field(
        default="~/.vermilion-bird/memory", description="记忆存储目录"
    )
    short_term: ShortTermMemoryConfig = Field(default_factory=ShortTermMemoryConfig)
    mid_term: MidTermMemoryConfig = Field(default_factory=MidTermMemoryConfig)
    long_term: LongTermMemoryConfig = Field(default_factory=LongTermMemoryConfig)
    exclude_patterns: List[str] = Field(
        default_factory=lambda: ["密码", "password", "token", "api_key", "secret"],
        description="敏感词过滤模式",
    )
    extraction_interval: int = Field(default=10, description="多少次对话后提取中期记忆")
    extraction_time_interval: int = Field(
        default=3600, description="多少秒后提取中期记忆（默认1小时）"
    )
    short_term_max_entries: int = Field(default=50, description="短期记忆最大条目数")
    max_memory_tokens: int = Field(
        default=2000, description="注入 LLM 系统提示的记忆 token 预算上限"
    )

    class Config:
        env_prefix = "MEMORY_"
        case_sensitive = False
