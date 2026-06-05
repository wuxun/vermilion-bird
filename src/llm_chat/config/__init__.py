"""配置子系统 — 聚合所有子域配置，提供 YAML/环境变量加载。

子模块:
    llm_config        LLMConfig, ModelInfo
    memory_config     MemoryConfig, ShortTermMemoryConfig, MidTermMemoryConfig, LongTermMemoryConfig
    tools_config      ToolsConfig
    context_config    ContextConfig
    feishu_config     FeishuConfig
    notification_config  NotificationConfig
    skills_config     SkillsConfig, SkillConfig
    scheduler_config  SchedulerConfig
"""

from __future__ import annotations

import os
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings

from llm_chat.config.mcp_config import MCPConfig

# ── 子域配置类 ──
from llm_chat.config.llm_config import LLMConfig, ModelInfo
from llm_chat.config.memory_config import (
    MemoryConfig,
    ShortTermMemoryConfig,
    MidTermMemoryConfig,
    LongTermMemoryConfig,
)
from llm_chat.config.tools_config import ToolsConfig
from llm_chat.config.context_config import ContextConfig
from llm_chat.config.feishu_config import FeishuConfig
from llm_chat.config.notification_config import NotificationConfig
from llm_chat.config.skills_config import SkillsConfig, SkillConfig
from llm_chat.config.scheduler_config import SchedulerConfig
from llm_chat.config.knowledge_config import KnowledgeConfig

logger = logging.getLogger(__name__)

# ── 导出列表（供旧代码 from llm_chat.config import * 使用） ──
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
    "KnowledgeConfig",
    "config",
]


class Config(BaseSettings):
    """全局应用配置 — 聚合所有子域。"""

    llm: LLMConfig = Field(default_factory=LLMConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    context: ContextConfig = Field(default_factory=ContextConfig)
    feishu: FeishuConfig = Field(default_factory=lambda: FeishuConfig())
    notification: NotificationConfig = Field(
        default_factory=lambda: NotificationConfig()
    )
    enable_tools: bool = Field(default=True, description="是否启用工具调用")
    skills: SkillsConfig = Field(
        default_factory=SkillsConfig, description="Skills 配置"
    )
    external_skill_dirs: List[str] = Field(
        default_factory=lambda: [
            str(Path.home() / ".vermilion-bird" / "skills" / "code"),
        ],
        description="外部 Skill (Code Skill) 目录列表。默认包含 ~/.vermilion-bird/skills/code/"
    )
    prompt_skill_dirs: List[str] = Field(
        default_factory=list,
        description=(
            "外部 Prompt Skill 目录列表（Agent Skills 标准 SKILL.md）。"
            "默认已包含 ~/.vermilion-bird/skills/ 和 .agents/skills/"
        ),
    )
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    knowledge: KnowledgeConfig = Field(default_factory=KnowledgeConfig)
    log_file: str = Field(
        default="~/.vermilion-bird/logs/app.log",
        description="日志文件路径，可被 CLI --log-file 覆盖",
    )
    log_level: str = Field(
        default="INFO",
        description="日志级别: DEBUG, INFO, WARNING, ERROR",
    )

    class Config:
        env_prefix = ""
        case_sensitive = False

    # ------------------------------------------------------------------
    # YAML 序列化
    # ------------------------------------------------------------------

    @staticmethod
    def get_default_config_path() -> str:
        config_dir = os.path.expanduser("~/.vermilion-bird")
        os.makedirs(config_dir, exist_ok=True)
        return os.path.join(config_dir, "config.yaml")

    @classmethod
    def from_yaml(cls, config_path: Optional[str] = None) -> "Config":
        if config_path is None:
            config_path = cls.get_default_config_path()

        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                config_data = yaml.safe_load(f)

            if config_data is None:
                return cls()

            llm_data = config_data.get("llm", {})
            llm_config = LLMConfig(**llm_data)

            # Resolve API key from keyring if prefixed with 'keyring:'
            from llm_chat.utils.secure_storage import resolve_api_key
            resolved_key = resolve_api_key(llm_config.api_key)
            if resolved_key and resolved_key != llm_config.api_key:
                llm_config.api_key = resolved_key
                logger.info("LLM API key resolved from keyring/environment")

            # Parse available_models
            has_available_models_key = "available_models" in llm_data
            available_models_data = llm_data.get("available_models", [])
            available_models = []
            for model_data in available_models_data:
                if isinstance(model_data, dict):
                    available_models.append(ModelInfo(**model_data))

            if not has_available_models_key and not available_models:
                available_models = _default_models()

            llm_config.available_models = available_models

            # Feishu
            feishu_data = config_data.get("feishu", {})
            feishu_config = (
                FeishuConfig(**feishu_data)
                if feishu_data is not None
                else FeishuConfig()
            )

            # MCP
            mcp_data = config_data.get("mcp", {})
            mcp_config = MCPConfig.from_dict(mcp_data)

            enable_tools = config_data.get("enable_tools", True)

            # Tools
            tools_data = config_data.get("tools", {})
            tools_config = (
                ToolsConfig(**tools_data)
                if tools_data
                else ToolsConfig()
            )

            # Skills
            skills_data = config_data.get("skills", {})
            skills_config = cls._parse_skills(skills_data)

            external_skill_dirs = config_data.get("external_skill_dirs", [])
            prompt_skill_dirs = config_data.get("prompt_skill_dirs", [])

            # Memory
            memory_data = config_data.get("memory", {})
            memory_config = cls._parse_memory(memory_data)

            # Context
            context_data = config_data.get("context", {})
            context_config = (
                ContextConfig(**context_data)
                if context_data is not None
                else ContextConfig()
            )

            # Scheduler
            scheduler_data = config_data.get("scheduler", {})
            scheduler_config = (
                SchedulerConfig(**scheduler_data)
                if scheduler_data is not None
                else SchedulerConfig()
            )

            # Knowledge
            knowledge_data = config_data.get("knowledge", {})
            knowledge_config = (
                KnowledgeConfig(**knowledge_data)
                if knowledge_data
                else KnowledgeConfig()
            )

            # Log
            log_file = config_data.get("log_file", "~/.vermilion-bird/logs/app.log")
            log_level = config_data.get("log_level", "INFO")

            config_instance = cls(
                llm=llm_config,
                mcp=mcp_config,
                enable_tools=enable_tools,
                tools=tools_config,
                skills=skills_config,
                feishu=feishu_config,
                external_skill_dirs=external_skill_dirs,
                memory=memory_config,
                context=context_config,
                scheduler=scheduler_config,
                knowledge=knowledge_config,
                log_file=log_file,
                log_level=log_level,
            )
            config_instance.validate_feishu_config()
            return config_instance
        return cls()

    def validate_feishu_config(self) -> None:
        """向后兼容：触发 FeishuConfig 的 model_validator。"""
        if getattr(self, "feishu", None) is None:
            return

    @classmethod
    def from_env(cls) -> "Config":
        """从环境变量加载配置。"""
        cfg = cls()
        feishu_enabled = os.getenv("FEISHU_ENABLED")
        app_id = os.getenv("FEISHU_APP_ID")
        app_secret = os.getenv("FEISHU_APP_SECRET")
        tenant_key = os.getenv("FEISHU_TENANT_KEY")

        if any(v is not None for v in [feishu_enabled, app_id, app_secret, tenant_key]):
            enabled = False
            if feishu_enabled is not None:
                enabled = str(feishu_enabled).lower() in ("1", "true", "yes")
            cfg.feishu = FeishuConfig(
                enabled=enabled,
                app_id=app_id,
                app_secret=app_secret,
                tenant_key=tenant_key,
            )
            cfg.validate_feishu_config()
        return cfg

    @classmethod
    def _parse_memory(cls, data: Dict[str, Any]) -> MemoryConfig:
        if not data:
            return MemoryConfig()
        short_term_data = data.get("short_term", {})
        mid_term_data = data.get("mid_term", {})
        long_term_data = data.get("long_term", {})
        return MemoryConfig(
            enabled=data.get("enabled", True),
            storage_dir=data.get("storage_dir", "~/.vermilion-bird/memory"),
            short_term=ShortTermMemoryConfig(**short_term_data),
            mid_term=MidTermMemoryConfig(**mid_term_data),
            long_term=LongTermMemoryConfig(**long_term_data),
            exclude_patterns=data.get(
                "exclude_patterns", ["密码", "password", "token", "api_key", "secret"]
            ),
            extraction_interval=data.get("extraction_interval", 10),
            extraction_time_interval=data.get("extraction_time_interval", 3600),
            short_term_max_entries=data.get("short_term_max_entries", 50),
            max_memory_tokens=data.get("max_memory_tokens", 2000),
        )

    @classmethod
    def _parse_skills(cls, data: Dict[str, Any]) -> SkillsConfig:
        skill_configs = {}
        for skill_name, skill_data in data.items():
            if isinstance(skill_data, dict):
                skill_configs[skill_name] = SkillConfig(**skill_data)
            elif isinstance(skill_data, SkillConfig):
                skill_configs[skill_name] = skill_data

        for skill_name in SkillsConfig.model_fields.keys():
            if skill_name not in skill_configs:
                default = SkillsConfig.model_fields[skill_name].default
                if default is not None:
                    skill_configs[skill_name] = default

        return SkillsConfig(**skill_configs)

    def to_yaml(self, config_path: Optional[str] = None):
        if config_path is None:
            config_path = self.get_default_config_path()

        config_dir = os.path.dirname(config_path)
        if config_dir:
            os.makedirs(config_dir, exist_ok=True)

        skills_dict = {}
        for skill_name in self.skills.model_fields.keys():
            skill_config = getattr(self.skills, skill_name, None)
            if skill_config:
                skills_dict[skill_name] = skill_config.model_dump()

        config_data = {
            "llm": self.llm.model_dump(),
            "mcp": self.mcp.to_dict(),
            "enable_tools": self.enable_tools,
            "feishu": self.feishu.model_dump(),
            "notification": self.notification.model_dump(),
            "skills": skills_dict,
            "tools": self.tools.model_dump(),
            "external_skill_dirs": self.external_skill_dirs,
            "prompt_skill_dirs": self.prompt_skill_dirs,
            "memory": self.memory.model_dump(),
            "context": self.context.model_dump(),
            "scheduler": self.scheduler.model_dump(),
            "knowledge": self.knowledge.model_dump(),
            "log_file": self.log_file,
            "log_level": self.log_level,
        }

        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(config_data, f, default_flow_style=False, allow_unicode=True)


# ── 默认模型列表 ──

def _default_models() -> list:
    return [
        ModelInfo(
            id="gpt-3.5-turbo",
            name="GPT-3.5 Turbo",
            description="OpenAI GPT-3.5 Turbo - 快速高效",
        ),
        ModelInfo(
            id="gpt-4",
            name="GPT-4",
            description="OpenAI GPT-4 - 更强大的模型",
        ),
        ModelInfo(
            id="claude-3-opus",
            name="Claude 3 Opus",
            description="Anthropic Claude 3 Opus - 最强大的模型",
        ),
        ModelInfo(
            id="claude-3-sonnet",
            name="Claude 3.5 Sonnet",
            description="Anthropic Claude 3.5 Sonnet - 快速且强大",
        ),
        ModelInfo(
            id="gemini-pro",
            name="Gemini Pro",
            description="Google Gemini Pro - 高效且强大",
        ),
    ]


# ── 模块级快捷实例 ──

config = Config.from_yaml()
