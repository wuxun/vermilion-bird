"""意图识别类型定义。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List


class Intent(str, Enum):
    """用户意图分类。"""

    # ── Layer 0: 快捷指令 ──
    SHORTCUT = "shortcut"       # / 前缀指令（无需 LLM）

    # ── Layer 1: 确定性路由 ──
    GREETING = "greeting"       # 问候 → 直接回复
    SEARCH = "search"           # 搜索请求 → web_search 工具
    FILE_OP = "file_op"         # 文件读/写/编辑
    CODE = "code"               # 代码生成/调试/解释
    SUMMARIZE = "summarize"     # 摘要/总结请求
    SCHEDULE = "schedule"       # 定时任务管理
    MEMORY = "memory"           # 记忆查询/修改
    SIMPLE_QA = "simple_qa"     # 简单事实问答 → 小模型

    # ── 默认 ──
    CHAT = "chat"               # 一般对话/复杂推理


@dataclass
class RoutingDecision:
    """路由决策 — 决定如何处理用户消息。

    Attributes:
        intent: 识别到的意图
        confidence: 置信度 (0.0-1.0)
        skip_llm: 是否跳过 LLM 调用
        direct_response: 预设回复（skip_llm=True 时使用）
        override_message: 覆盖原始消息（如 /search xxx → xxx）
        suggested_model: 建议的模型名称 ("small" / "medium" / "large")
        suggested_tools: 建议预加载的工具列表
        force_reasoning: 是否强制使用推理模型
    """

    intent: Intent
    confidence: float = 1.0
    skip_llm: bool = False
    direct_response: Optional[str] = None
    override_message: Optional[str] = None
    suggested_model: Optional[str] = None
    suggested_tools: List[str] = field(default_factory=list)
    force_reasoning: bool = False

    @classmethod
    def passthrough(cls) -> RoutingDecision:
        """默认决策：走完整 LLM 管道。"""
        return cls(intent=Intent.CHAT, confidence=1.0)

    @classmethod
    def bypass(cls, intent: Intent, response: str) -> RoutingDecision:
        """跳过 LLM，直接返回预设回复。"""
        return cls(
            intent=intent,
            confidence=1.0,
            skip_llm=True,
            direct_response=response,
        )
