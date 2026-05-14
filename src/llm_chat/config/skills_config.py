"""技能系统配置。"""

from __future__ import annotations

from typing import Dict, Any
from pydantic import Field
from pydantic_settings import BaseSettings


class SkillConfig(BaseSettings):
    """单个技能配置。"""

    enabled: bool = Field(default=True, description="是否启用该 Skill")

    class Config:
        extra = "allow"
        case_sensitive = False


class SkillsConfig(BaseSettings):
    """所有技能的总配置。"""

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
    remember_fact: SkillConfig = Field(default_factory=lambda: SkillConfig(enabled=True))

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
