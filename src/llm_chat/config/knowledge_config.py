"""领域知识系统配置。"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class KnowledgeConfig(BaseSettings):
    """领域知识系统配置。"""

    enabled: bool = Field(default=True, description="是否启用领域知识系统")
    storage_dir: str = Field(
        default="~/.vermilion-bird/knowledge", description="知识存储目录"
    )
    max_knowledge_tokens: int = Field(
        default=300, description="注入 LLM 系统提示的知识 token 预算上限"
    )
    extraction_interval: int = Field(
        default=20, description="每 N 轮对话后触发知识提取"
    )
    consolidate_min_entries: int = Field(
        default=10, description="未整理知识点 ≥ N 时触发整合"
    )
    refine_min_total: int = Field(
        default=50, description="总知识点 ≥ N 时触发提炼"
    )

    class Config:
        env_prefix = "KNOWLEDGE_"
        case_sensitive = False
