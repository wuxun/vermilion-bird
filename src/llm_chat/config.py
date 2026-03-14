import os
from typing import Optional, Literal
from pydantic_settings import BaseSettings
from pydantic import Field
import yaml


class LLMConfig(BaseSettings):
    """LLM 配置类"""
    base_url: str = Field(default="https://api.openai.com/v1", description="模型 API 基础 URL")
    model: str = Field(default="gpt-3.5-turbo", description="模型名称")
    api_key: Optional[str] = Field(default=None, description="API 密钥")
    timeout: int = Field(default=30, description="请求超时时间（秒）")
    max_retries: int = Field(default=3, description="最大重试次数")
    protocol: str = Field(default="openai", description="API 协议类型: openai, anthropic, gemini")

    class Config:
        env_prefix = "LLM_"
        case_sensitive = False


class Config(BaseSettings):
    """全局配置类"""
    llm: LLMConfig = Field(default_factory=LLMConfig)

    class Config:
        env_prefix = ""
        case_sensitive = False

    @classmethod
    def from_yaml(cls, config_path: str = "config.yaml") -> "Config":
        """从 YAML 文件加载配置"""
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                config_data = yaml.safe_load(f)
            return cls(**config_data)
        return cls()


config = Config.from_yaml()
