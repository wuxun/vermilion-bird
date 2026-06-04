"""LLM 连接 & 模型配置。"""

from __future__ import annotations

from typing import Optional, List, Dict, Any
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


class ModelInfo(BaseSettings):
    """可用模型条目。"""

    id: str = Field(description="模型ID")
    name: str = Field(description="模型显示名称")
    description: Optional[str] = Field(default=None, description="模型描述")
    base_url: Optional[str] = Field(default=None, description="模型 API 基础 URL")
    api_key: Optional[str] = Field(default=None, description="API 密钥")
    protocol: Optional[str] = Field(default=None, description="API 协议类型")
    supports_tools: bool = Field(
        default=True,
        description="是否支持 function calling / tools，本地小模型建议设为 false",
    )

    class Config:
        extra = "allow"

    @field_validator("protocol")
    @classmethod
    def validate_protocol(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ["openai", "anthropic", "gemini"]:
            raise ValueError(f"协议类型必须是 openai, anthropic, 或 gemini，得到: {v}")
        return v


class LLMConfig(BaseSettings):
    """LLM 连接配置。"""

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
    max_context_tokens: Optional[int] = Field(
        default=None, description="模型最大上下文窗口大小(token)，不设则自动检测"
    )
    top_p: Optional[float] = Field(default=None, description="Top-p 采样参数")
    reasoning_effort: Optional[str] = Field(
        default=None,
        description="推理深度: low/medium/high，用于DeepSeek R1/OpenAI o1等模型",
    )
    available_models: List[ModelInfo] = Field(
        default_factory=list, description="可用模型列表"
    )
    fallback_models: List[str] = Field(
        default_factory=list,
        description="内容审核拒绝时的备选模型 ID 列表 (引用 available_models 中的 id)",
    )
    moderation_log_dir: Optional[str] = Field(
        default=None,
        description="内容审核拒绝请求日志目录，默认 ~/.vermilion-bird/moderation_logs",
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
        """获取非空的模型参数。"""
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
