"""配置入口 — 兼容性别名。

所有配置类已迁移到 llm_chat.config 子包。
此文件保留向后兼容的 re-export。
"""

# 从子包导入所有公共符号
from llm_chat.config import (
    Config,
    LLMConfig,
    ModelInfo,
    MemoryConfig,
    ShortTermMemoryConfig,
    MidTermMemoryConfig,
    LongTermMemoryConfig,
    ToolsConfig,
    ContextConfig,
    FeishuConfig,
    NotificationConfig,
    SkillsConfig,
    SkillConfig,
    SchedulerConfig,
    config,
)

__all__ = [
    "Config",
    "LLMConfig",
    "ModelInfo",
    "MemoryConfig",
    "ShortTermMemoryConfig",
    "MidTermMemoryConfig",
    "LongTermMemoryConfig",
    "ToolsConfig",
    "ContextConfig",
    "FeishuConfig",
    "NotificationConfig",
    "SkillsConfig",
    "SkillConfig",
    "SchedulerConfig",
    "config",
]
