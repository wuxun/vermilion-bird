from __future__ import annotations
import os
from typing import Optional, List, Dict, Any
from pydantic_settings import BaseSettings
from pydantic import Field, field_validator, model_validator
import yaml

from llm_chat.mcp import MCPConfig


# FeishuConfig duplicate removed to unify with the later definition


class ModelInfo(BaseSettings):
    id: str = Field(description="模型ID")
    name: str = Field(description="模型显示名称")
    description: Optional[str] = Field(default=None, description="模型描述")
    base_url: Optional[str] = Field(default=None, description="模型 API 基础 URL")
    api_key: Optional[str] = Field(default=None, description="API 密钥")
    protocol: Optional[str] = Field(default=None, description="API 协议类型")

    class Config:
        extra = "allow"

    @field_validator("protocol")
    @classmethod
    def validate_protocol(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ["openai", "anthropic", "gemini"]:
            raise ValueError(f"协议类型必须是 openai, anthropic, 或 gemini，得到: {v}")
        return v


class FeishuConfig(BaseSettings):
    enabled: bool = Field(default=False, description="是否启用飞书集成")
    app_id: Optional[str] = Field(default=None, description="飞书应用 ID")
    app_secret: Optional[str] = Field(default=None, description="飞书应用密钥")
    tenant_key: Optional[str] = Field(default=None, description="飞书租户密钥")
    encrypt_key: Optional[str] = Field(default=None, description="飞书事件加密密钥")
    verification_token: Optional[str] = Field(
        default=None, description="飞书事件验证令牌"
    )

    @model_validator(mode="after")
    def validate_credentials_when_enabled(self) -> "FeishuConfig":
        """当 enabled=True 时，验证 app_id 和 app_secret 必须不为空"""
        if self.enabled:
            if not self.app_id or not self.app_secret:
                raise ValueError("飞书集成已启用但 app_id 或 app_secret 为空")
        return self


class NotificationConfig(BaseSettings):
    """任务通知配置"""

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
    max_context_tokens: int = Field(
        default=4096, description="模型最大上下文窗口大小(token)"
    )
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

    @field_validator("protocol")
    @classmethod
    def validate_protocol(cls, v: str) -> str:
        if v not in ["openai", "anthropic", "gemini"]:
            raise ValueError(f"协议类型必须是 openai, anthropic, 或 gemini，得到: {v}")
        return v

    @field_validator("timeout")
    @classmethod
    def validate_timeout(cls, v: int) -> int:
        if v <= 0:
            raise ValueError(f"超时时间必须大于0，得到: {v}")
        return v

    @field_validator("max_retries")
    @classmethod
    def validate_max_retries(cls, v: int) -> int:
        if v < 0:
            raise ValueError(f"最大重试次数不能为负数，得到: {v}")
        return v

    @field_validator("temperature")
    @classmethod
    def validate_temperature(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and (v < 0 or v > 2):
            raise ValueError(f"温度参数必须在 0-2 之间，得到: {v}")
        return v

    @field_validator("max_tokens")
    @classmethod
    def validate_max_tokens(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v <= 0:
            raise ValueError(f"最大输出token数必须大于0，得到: {v}")
        return v

    @field_validator("top_p")
    @classmethod
    def validate_top_p(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and (v < 0 or v > 1):
            raise ValueError(f"Top-p 参数必须在 0-1 之间，得到: {v}")
        return v

    @field_validator("reasoning_effort")
    @classmethod
    def validate_reasoning_effort(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ["low", "medium", "high"]:
            raise ValueError(f"推理深度必须是 low, medium, 或 high，得到: {v}")
        return v

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


class ContextConfig(BaseSettings):
    """上下文管理配置"""

    enabled: bool = Field(default=True, description="是否启用上下文管理")
    reserve_tokens: int = Field(
        default=1024, description="为系统提示和回复预留的token数量"
    )
    enable_cache: bool = Field(default=True, description="是否启用上下文缓存")
    auto_prune_cache: bool = Field(default=True, description="是否自动清理过期缓存")
    transcript_dir: str = Field(
        default="~/.vermilion-bird/transcripts", description="完整转录本保存目录"
    )
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

    @field_validator("auto_compact_threshold")
    @classmethod
    def validate_threshold(cls, v: float) -> float:
        if v < 0 or v > 1:
            raise ValueError(f"自动压缩阈值必须在0-1之间，得到: {v}")
        return v


class ToolsConfig(BaseSettings):
    max_workers: int = Field(default=5, description="工具并行执行的最大工作线程数")
    max_retries: int = Field(default=3, description="工具执行失败时的最大重试次数")
    retry_delay: float = Field(default=1.0, description="重试间隔时间（秒）")
    timeout: int = Field(default=300, description="工具执行超时时间（秒）")
    work_dir: str = Field(default="./work", description="任务临时文件工作目录")
    workflow_poll_timeout: int = Field(
        default=240,
        description="execute_workflow 内部轮询超时时间（秒），超时后返回 submitted 状态让 LLM 自行轮询",
    )
    workflow_timeout_padding: int = Field(
        default=30,
        description="workflow 节点超时额外 padding（秒），实际超时 = node.timeout + padding",
    )
    subagent_max_retries: int = Field(
        default=2,
        description="子 agent LLM 调用失败时的最大重试次数（0=不重试）",
    )
    subagent_retry_delay: float = Field(
        default=2.0,
        description="子 agent 重试初始延迟（秒），指数退避",
    )
    subagent_max_concurrent: int = Field(
        default=10,
        description="子 agent 最大并发数（0=不限制），超过此数量 spawn_subagent 会拒绝",
    )
    subagent_models: Dict[str, str] = Field(
        default_factory=dict,
        description=(
            "子 agent 按复杂度选择模型: {'simple': 'model-a', 'complex': 'model-b'}。"
            "LLM 调用 spawn_subagent 时指定 complexity 级别即可，无需知道具体模型名。"
        ),
    )

    class Config:
        env_prefix = "TOOLS_"
        case_sensitive = False

    @field_validator("max_workers")
    @classmethod
    def validate_max_workers(cls, v: int) -> int:
        if v <= 0:
            raise ValueError(f"最大工作线程数必须大于0，得到: {v}")
        return v

    @field_validator("max_retries")
    @classmethod
    def validate_max_retries(cls, v: int) -> int:
        if v < 0:
            raise ValueError(f"最大重试次数不能为负数，得到: {v}")
        return v

    @field_validator("retry_delay")
    @classmethod
    def validate_retry_delay(cls, v: float) -> float:
        if v < 0:
            raise ValueError(f"重试间隔时间不能为负数，得到: {v}")
        return v

    @field_validator("timeout")
    @classmethod
    def validate_timeout(cls, v: int) -> int:
        if v <= 0:
            raise ValueError(f"超时时间必须大于0，得到: {v}")
        return v


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
    max_memory_tokens: int = Field(
        default=2000, description="注入 LLM 系统提示的记忆 token 预算上限"
    )

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
    task_delegator: SkillConfig = Field(
        default_factory=lambda: SkillConfig(enabled=True)
    )
    scheduler: SkillConfig = Field(default_factory=lambda: SkillConfig(enabled=True))
    shell_exec: SkillConfig = Field(default_factory=lambda: SkillConfig(enabled=True))

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
        extra = getattr(self, "__pydantic_extra__", {}) or {}
        for extra_field, extra_value in extra.items():
            if hasattr(extra_value, "model_dump"):
                configs[extra_field] = extra_value.model_dump()
            else:
                configs[extra_field] = extra_value
        return configs


class SchedulerConfig(BaseSettings):
    """Scheduler 配置，用于调度并发执行任务的参数。

    注意：不包含 db_path 字段，复用现有数据库。
    """

    enabled: bool = Field(default=True, description="是否启用调度器")
    max_workers: int = Field(default=4, description="调度器并发最大工作线程数")
    default_timezone: str = Field(default="UTC", description="默认时区")

    class Config:
        env_prefix = "SCHEDULER_"
        case_sensitive = False

    @field_validator("max_workers")
    @classmethod
    def validate_max_workers(cls, v: int) -> int:
        if v <= 0:
            raise ValueError(f"最大工作线程数必须大于0，得到: {v}")
        return v

    @field_validator("default_timezone")
    @classmethod
    def validate_timezone(cls, v: str) -> str:
        try:
            import pytz

            pytz.timezone(v)
        except ImportError:
            pass
        except Exception:
            raise ValueError(f"无效的时区: {v}")
        return v


class Config(BaseSettings):
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
        default_factory=list, description="外部 Skill 目录列表"
    )
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)

    class Config:
        env_prefix = ""
        case_sensitive = False

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

            # Parse available_models
            # Check if "available_models" key exists in config file
            has_available_models_key = "available_models" in llm_data
            available_models_data = llm_data.get("available_models", [])
            available_models = []
            for model_data in available_models_data:
                if isinstance(model_data, dict):
                    available_models.append(ModelInfo(**model_data))

            # Only add defaults if the key doesn't exist in config file
            # If user explicitly sets empty list, respect that
            if not has_available_models_key and not available_models:
                available_models = [
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

            llm_config.available_models = available_models

            # Feishu (Feishu/Lark) config
            feishu_data = config_data.get("feishu", {})
            feishu_config = (
                FeishuConfig(**feishu_data)
                if feishu_data is not None
                else FeishuConfig()
            )

            mcp_data = config_data.get("mcp", {})
            mcp_config = MCPConfig.from_dict(mcp_data)

            enable_tools = config_data.get("enable_tools", True)

            skills_data = config_data.get("skills", {})
            skills_config = cls._parse_skills(skills_data)

            external_skill_dirs = config_data.get("external_skill_dirs", [])

            memory_data = config_data.get("memory", {})
            memory_config = cls._parse_memory(memory_data)

            # Context 配置
            context_data = config_data.get("context", {})
            context_config = (
                ContextConfig(**context_data)
                if context_data is not None
                else ContextConfig()
            )

            # Scheduler 配置
            scheduler_data = config_data.get("scheduler", {})
            scheduler_config = (
                SchedulerConfig(**scheduler_data)
                if scheduler_data is not None
                else SchedulerConfig()
            )

            config_instance = cls(
                llm=llm_config,
                mcp=mcp_config,
                enable_tools=enable_tools,
                skills=skills_config,
                feishu=feishu_config,
                external_skill_dirs=external_skill_dirs,
                memory=memory_config,
                context=context_config,
                scheduler=scheduler_config,
            )
            config_instance.validate_feishu_config()
            return config_instance
        return cls()

    def validate_feishu_config(self) -> None:
        # FeishuConfig 现在有自己的 model_validator，这里保留向后兼容性
        if getattr(self, "feishu", None) is None:
            return
        # 触发 FeishuConfig 的验证（如果还没有验证过）
        if hasattr(self.feishu, "model_validate"):
            pass

    @classmethod
    def from_env(cls) -> "Config":
        # 从环境变量加载配置，覆盖 Feishu 配置的相关字段
        cfg = cls()
        # 读取 Feishu 环境变量
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

        # 默认启用的 skills
        default_skills = [
            "web_search",
            "calculator",
            "web_fetch",
            "file_reader",
            "task_delegator",
        ]
        for skill_name in default_skills:
            if skill_name not in skill_configs:
                skill_configs[skill_name] = SkillConfig(enabled=True)

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
            "external_skill_dirs": self.external_skill_dirs,
            "memory": self.memory.model_dump(),
            "context": self.context.model_dump(),
            "scheduler": self.scheduler.model_dump(),
        }

        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(config_data, f, default_flow_style=False, allow_unicode=True)


config = Config.from_yaml()
