import os
from typing import Optional, Literal, List
from pydantic_settings import BaseSettings
from pydantic import Field
import yaml

from llm_chat.mcp import MCPConfig, MCPServerConfig


class LLMConfig(BaseSettings):
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
    llm: LLMConfig = Field(default_factory=LLMConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)
    enable_tools: bool = Field(default=True, description="是否启用工具调用")

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
            
            mcp_data = config_data.get("mcp", {})
            mcp_config = MCPConfig.from_dict(mcp_data)
            
            enable_tools = config_data.get("enable_tools", True)
            
            return cls(
                llm=llm_config,
                mcp=mcp_config,
                enable_tools=enable_tools
            )
        return cls()
    
    def to_yaml(self, config_path: str = "config.yaml"):
        config_data = {
            "llm": self.llm.model_dump(),
            "mcp": self.mcp.to_dict(),
            "enable_tools": self.enable_tools
        }
        
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(config_data, f, default_flow_style=False, allow_unicode=True)


config = Config.from_yaml()
