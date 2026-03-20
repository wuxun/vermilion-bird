import os
from typing import Optional, List, Dict, Any
from pydantic_settings import BaseSettings
from pydantic import Field
import yaml

from llm_chat.mcp import MCPConfig


class ModelInfo(BaseSettings):
    id: str = Field(description="模型ID")
    name: str = Field(description="模型显示名称")
    description: Optional[str] = Field(default=None, description="模型描述")

    class Config:
        extra = "allow"


class LLMConfig(BaseSettings):
    base_url: str = Field(
        default="https://api.openai.com/v1", description="模型 API 基础 URL"
    )
    model: str = Field(default="gpt-3.5-turbo", description="模型名称")
    api_key: Optional[str] = Field(default=None, description="API 密钥")
    timeout: int = Field(default=30, description="请求超时时间(秒)")
    max_retries: int = Field(default=3, description="最大重试次数")
    protocol: str = Field(
        default="openai", description="API 协议类型: openai, anthropic, gemini"
    )
    http_proxy: Optional[str] = Field(
        default=None, description="HTTP 代理地址， 如 http://127.0.0.1:7890"
    )
    https_proxy: Optional[str] = Field(
        default=None, description="HTTPS 代理地址, 如 http://127.0.0.1:7890"
    )

    temperature: Optional[float] = Field(
        default=None, description="温度参数 (0-2)，控制输出随机性"
    )
    max_tokens: Optional[int] = Field(default=None, description="最大输出token数")
    top_p: Optional[float] = Field(default=None, description="Top-p 采样参数")
    reasoning_effort: Optional[str] = Field(
        default=None,
        description="推理深度: low/medium/high，用于DeepSeek R1/OpenAI o1等模型",
    )
    available_models: List[ModelInfo] = Field(
        default_factory=list, description="可用模型列表"
    )

    class Config:
        env_prefix = "LLM_"
        case_sensitive = False

    def get_model_params(self) -> Dict[str, Any]:
        """获取非空的模型参数"""
        params = {}
        if self.temperature is not None:
            params["temperature"] = self.temperature
        if self.max_tokens is not None:
            params["max_tokens"] = self.max_tokens
        if self.top_p is not None:
            params["top_p"] = self.top_p
        if self.reasoning_effort is not None:
            params["reasoning_effort"] = self.reasoning_effort
        return params


class ToolsConfig(BaseSettings):
    max_workers: int = Field(default=5, description="工具并行执行的最大工作线程数")
    max_retries: int = Field(default=3, description="工具执行失败时的最大重试次数")
    retry_delay: float = Field(default=1.0, description="重试间隔时间（秒）")
    timeout: int = Field(default=30, description="单个工具执行超时时间（秒）")

    class Config:
        env_prefix = "TOOLS_"
        case_sensitive = False


class ShortTermMemoryConfig(BaseSettings):
    max_items: int = Field(default=10, description="短期记忆最大条目数")

    class Config:
        env_prefix = "MEMORY_SHORT_TERM_"
        case_sensitive = False


class MidTermMemoryConfig(BaseSettings):
    max_days: int = Field(default=30, description="中期记忆保留天数")
    compress_after_days: int = Field(default=7, description="多少天后压缩记忆")

    class Config:
        env_prefix = "MEMORY_MID_TERM_"
        case_sensitive = False


class LongTermMemoryConfig(BaseSettings):
    auto_evolve: bool = Field(default=True, description="是否自动进化记忆")
    evolve_interval_days: int = Field(default=7, description="记忆进化间隔天数")

    class Config:
        env_prefix = "MEMORY_LONG_TERM_"
        case_sensitive = False


class MemoryConfig(BaseSettings):
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

    class Config:
        env_prefix = "MEMORY_"
        case_sensitive = False


class SkillConfig(BaseSettings):
    enabled: bool = Field(default=True, description="是否启用该 Skill")

    class Config:
        extra = "allow"
        case_sensitive = False


class SkillsConfig(BaseSettings):
    web_search: SkillConfig = Field(default_factory=lambda: SkillConfig(enabled=True))
    calculator: SkillConfig = Field(default_factory=lambda: SkillConfig(enabled=True))
    web_fetch: SkillConfig = Field(default_factory=lambda: SkillConfig(enabled=True))
    file_reader: SkillConfig = Field(default_factory=lambda: SkillConfig(enabled=True))
    file_writer: SkillConfig = Field(default_factory=lambda: SkillConfig(enabled=True))
    file_editor: SkillConfig = Field(default_factory=lambda: SkillConfig(enabled=True))
    todo_manager: SkillConfig = Field(default_factory=lambda: SkillConfig(enabled=True))

    class Config:
        extra = "allow"
        case_sensitive = False

    def get_skill_config(self, skill_name: str) -> Dict[str, Any]:
        skill_config = getattr(self, skill_name, None)
        if skill_config is None:
            return {"enabled": False}
        return skill_config.model_dump()

    def get_all_skill_configs(self) -> Dict[str, Dict[str, Any]]:
        configs = {}
        for skill_name in self.model_fields.keys():
            configs[skill_name] = self.get_skill_config(skill_name)
        for extra_field in self.__pydantic_extra__ or {}:
            configs[extra_field] = (
                self.__pydantic_extra__[extra_field].model_dump()
                if hasattr(self.__pydantic_extra__[extra_field], "model_dump")
                else self.__pydantic_extra__[extra_field]
            )
        return configs


class Config(BaseSettings):
    llm: LLMConfig = Field(default_factory=LLMConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    enable_tools: bool = Field(default=True, description="是否启用工具调用")
    skills: SkillsConfig = Field(
        default_factory=SkillsConfig, description="Skills 配置"
    )
    external_skill_dirs: List[str] = Field(
        default_factory=list, description="外部 Skill 目录列表"
    )

    class Config:
        env_prefix = ""
        case_sensitive = False

    @classmethod
    def from_yaml(cls, config_path: str = "config.yaml") -> "Config":
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                config_data = yaml.safe_load(f)

            if config_data is None:
                return cls()

            llm_data = config_data.get("llm", {})
            llm_config = LLMConfig(**llm_data)

            # Parse available_models
            available_models_data = llm_data.get("available_models", [])
            available_models = []
            for model_data in available_models_data:
                if isinstance(model_data, dict):
                    available_models.append(ModelInfo(**model_data))
            llm_config.available_models = available_models

            mcp_data = config_data.get("mcp", {})
            mcp_config = MCPConfig.from_dict(mcp_data)

            enable_tools = config_data.get("enable_tools", True)

            skills_data = config_data.get("skills", {})
            skills_config = cls._parse_skills(skills_data)

            external_skill_dirs = config_data.get("external_skill_dirs", [])

            memory_data = config_data.get("memory", {})
            memory_config = cls._parse_memory(memory_data)

            return cls(
                llm=llm_config,
                mcp=mcp_config,
                enable_tools=enable_tools,
                skills=skills_config,
                external_skill_dirs=external_skill_dirs,
                memory=memory_config,
            )
        return cls()

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
        )

    @classmethod
    def _parse_skills(cls, data: Dict[str, Any]) -> SkillsConfig:
        skill_configs = {}
        for skill_name, skill_data in data.items():
            if isinstance(skill_data, dict):
                skill_configs[skill_name] = SkillConfig(**skill_data)
            elif isinstance(skill_data, SkillConfig):
                skill_configs[skill_name] = skill_data

        if "web_search" not in skill_configs:
            skill_configs["web_search"] = SkillConfig(enabled=True)
        if "calculator" not in skill_configs:
            skill_configs["calculator"] = SkillConfig(enabled=True)
        if "web_fetch" not in skill_configs:
            skill_configs["web_fetch"] = SkillConfig(enabled=True)
        if "file_reader" not in skill_configs:
            skill_configs["file_reader"] = SkillConfig(enabled=True)

        return SkillsConfig(**skill_configs)

    def to_yaml(self, config_path: str = "config.yaml"):
        skills_dict = {}
        for skill_name in self.skills.model_fields.keys():
            skill_config = getattr(self.skills, skill_name, None)
            if skill_config:
                skills_dict[skill_name] = skill_config.model_dump()

        config_data = {
            "llm": self.llm.model_dump(),
            "mcp": self.mcp.to_dict(),
            "enable_tools": self.enable_tools,
            "skills": skills_dict,
            "external_skill_dirs": self.external_skill_dirs,
            "memory": {
                "enabled": self.memory.enabled,
                "storage_dir": self.memory.storage_dir,
                "short_term": self.memory.short_term.model_dump(),
                "mid_term": self.memory.mid_term.model_dump(),
                "long_term": self.memory.long_term.model_dump(),
                "exclude_patterns": self.memory.exclude_patterns,
            },
        }

        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(config_data, f, default_flow_style=False, allow_unicode=True)


config = Config.from_yaml()
