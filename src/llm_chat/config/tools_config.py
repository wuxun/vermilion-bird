"""工具 & 意图识别配置。"""

from __future__ import annotations

from typing import Dict
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


class ToolsConfig(BaseSettings):
    """工具执行 & 子 Agent & 意图识别配置。"""

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

    # ── 意图识别 ──
    enable_intent: bool = Field(
        default=True,
        description="启用意图识别 (问候/快捷指令等直接回复，跳过 LLM)",
    )
    intent_model_map: Dict[str, str] = Field(
        default_factory=dict,
        description=(
            "意图 → 模型映射，按 size hint 分配具体模型名。"
            "例: {'small': 'gpt-4o-mini', 'medium': 'gpt-4o', 'large': 'claude-3-5-sonnet'}"
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
