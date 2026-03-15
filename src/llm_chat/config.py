import os
from typing import Optional, List, Dict, Any
from pydantic_settings import BaseSettings
from pydantic import Field
import yaml

from llm_chat.mcp import MCPConfig


class LLMConfig(BaseSettings):
    base_url: str = Field(default="https://api.openai.com/v1", description="模型 API 基础 URL")
    model: str = Field(default="gpt-3.5-turbo", description="模型名称")
    api_key: Optional[str] = Field(default=None, description="API 密钥")
    timeout: int = Field(default=30, description="请求超时时间（秒）")
    max_retries: int = Field(default=3, description="最大重试次数")
    protocol: str = Field(default="openai", description="API 协议类型: openai, anthropic, gemini")
    http_proxy: Optional[str] = Field(default=None, description="HTTP 代理地址，如 http://127.0.0.1:7890")
    https_proxy: Optional[str] = Field(default=None, description="HTTPS 代理地址，如 http://127.0.0.1:7890")

    class Config:
        env_prefix = "LLM_"
        case_sensitive = False


class SkillConfig(BaseSettings):
    enabled: bool = Field(default=True, description="是否启用该 Skill")
    
    class Config:
        extra = "allow"
        case_sensitive = False


class SkillsConfig(BaseSettings):
    web_search: SkillConfig = Field(default_factory=lambda: SkillConfig(enabled=True))
    calculator: SkillConfig = Field(default_factory=lambda: SkillConfig(enabled=True))
    
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
            configs[extra_field] = self.__pydantic_extra__[extra_field].model_dump() if hasattr(self.__pydantic_extra__[extra_field], 'model_dump') else self.__pydantic_extra__[extra_field]
        return configs


class Config(BaseSettings):
    llm: LLMConfig = Field(default_factory=LLMConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)
    enable_tools: bool = Field(default=True, description="是否启用工具调用")
    skills: SkillsConfig = Field(default_factory=SkillsConfig, description="Skills 配置")
    external_skill_dirs: List[str] = Field(default_factory=list, description="外部 Skill 目录列表")

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
            
            skills_data = config_data.get("skills", {})
            skills_config = cls._parse_skills(skills_data)
            
            external_skill_dirs = config_data.get("external_skill_dirs", [])
            
            return cls(
                llm=llm_config,
                mcp=mcp_config,
                enable_tools=enable_tools,
                skills=skills_config,
                external_skill_dirs=external_skill_dirs
            )
        return cls()
    
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
            "external_skill_dirs": self.external_skill_dirs
        }
        
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(config_data, f, default_flow_style=False, allow_unicode=True)


config = Config.from_yaml()
