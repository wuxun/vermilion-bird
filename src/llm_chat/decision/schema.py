"""决策卡片数据模型。

核心类型层次:
    DecisionCard — 完整决策卡片 (含选项列表 + 推荐)
    DecisionOption — 单个选项 (含置信度)
    CardType — 卡片类型枚举
    CardStatus — 卡片生命周期状态
    DecisionRecord — 已做出的决策记录 (用于持久化)
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class CardType(str, Enum):
    """决策卡片类型。"""

    DECISION = "decision"
    """方案决策: 多个选项，用户选择其一执行。"""

    APPROVAL = "approval"
    """审批请求: 确认发布/执行某个产出。"""

    STATUS = "status"
    """状态通报: 无需操作，仅需知情。"""

    ALERT = "alert"
    """异常告警: 需要用户定夺处理方式。"""

    SUGGESTION = "suggestion"
    """建议推送: AI 预判用户可能要做的某件事。"""


class CardStatus(str, Enum):
    """决策卡片生命周期状态。"""

    PENDING = "pending"
    """待决策: 已推送给用户，等待响应。"""

    DECIDED = "decided"
    """已决策: 用户已做出选择。"""

    DISMISSED = "dismissed"
    """已忽略: 用户关闭/暂缓此卡片。"""

    ARCHIVED = "archived"
    """已归档: 超出有效期或已处理完毕。"""


class DecisionOption(BaseModel):
    """决策卡片中的单个选项。"""

    id: str = Field(description="选项唯一标识 (如 'A', 'B', 'C')")
    label: str = Field(description="选项名称，如 '连接池扩容（推荐）'")
    description: Optional[str] = Field(
        default=None, description="选项的详细说明"
    )
    expected_effect: Optional[str] = Field(
        default=None, description="预期效果摘要"
    )
    risk: Optional[str] = Field(default=None, description="风险描述")
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="置信度 (0.0 ~ 1.0)",
    )
    action: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "用户选择后的执行动作。格式: "
            "{'type': 'execute_skill'|'approve'|'reject'|'delegate', "
            "'skill': 'file_editor', 'params': {...}}。"
            "为 None 时使用默认行为（创建对话）"
        ),
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default=None, description="扩展元数据"
    )


class DecisionCard(BaseModel):
    """结构化决策卡片。

    这是 Decision-First 范式的核心数据单元。
    每一张卡片代表一个需要用户做决策的问题。
    """

    id: str = Field(default_factory=lambda: f"card_{uuid.uuid4().hex[:12]}")
    """卡片唯一标识。"""

    card_type: CardType = CardType.DECISION
    """卡片类型。"""

    status: CardStatus = CardStatus.PENDING
    """当前状态。"""

    title: str = Field(description="卡片标题，一句话说明问题")
    context: Optional[str] = Field(
        default=None, description="背景摘要 (1-3 行)"
    )
    options: List[DecisionOption] = Field(
        default_factory=list,
        description="选项列表 (至少 1 个，通常 2-3 个)",
    )
    recommendation: Optional[str] = Field(
        default=None,
        description="推荐选项的 id",
    )
    sources: List[str] = Field(
        default_factory=list,
        description="信息来源引用",
    )
    conversation_id: Optional[str] = Field(
        default=None,
        description="关联的对话 ID",
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default=None, description="扩展元数据"
    )

    # ── 时间戳 ──
    created_at: datetime = Field(default_factory=datetime.now)
    decided_at: Optional[datetime] = Field(default=None)
    dismissed_at: Optional[datetime] = Field(default=None)

    def decide(self, option_id: str) -> DecisionOption:
        """用户做出决策。

        Args:
            option_id: 被选择的选项 ID。

        Returns:
            被选中的 DecisionOption。

        Raises:
            ValueError: option_id 不在 options 列表中或卡片已决策。
        """
        if self.status != CardStatus.PENDING:
            raise ValueError(f"卡片 {self.id} 状态为 {self.status.value}，不可决策")

        selected = next(
            (o for o in self.options if o.id == option_id), None
        )
        if not selected:
            raise ValueError(
                f"选项 {option_id} 不在卡片 {self.id} 的选项中: "
                f"{[o.id for o in self.options]}"
            )

        self.status = CardStatus.DECIDED
        self.decided_at = datetime.now()
        return selected

    def dismiss(self):
        """用户忽略/暂缓此卡片。"""
        if self.status != CardStatus.PENDING:
            raise ValueError(f"卡片 {self.id} 状态为 {self.status.value}，不可忽略")
        self.status = CardStatus.DISMISSED
        self.dismissed_at = datetime.now()

    def archive(self):
        """归档卡片（超时或已处理完毕）。"""
        self.status = CardStatus.ARCHIVED
        if not self.decided_at:
            self.dismissed_at = datetime.now()

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典 (用于 JSON 传输/存储)。"""
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DecisionCard:
        """从字典反序列化。"""
        return cls.model_validate(data)


class DecisionRecord(BaseModel):
    """已归档的决策记录 (存入 SQLite decision_log 表)。"""

    id: str = Field(default_factory=lambda: f"rec_{uuid.uuid4().hex[:12]}")
    """记录唯一标识。"""

    card_id: str = Field(description="原始决策卡片的 ID")
    card_type: CardType = Field(description="卡片类型")
    title: str = Field(description="卡片标题")

    selected_option_id: Optional[str] = Field(default=None)
    selected_option_label: Optional[str] = Field(default=None)
    recommendation: Optional[str] = Field(default=None)

    context_snapshot: Optional[str] = Field(
        default=None, description="决策时的上下文快照"
    )
    conversation_id: Optional[str] = Field(default=None)

    created_at: datetime = Field(default_factory=datetime.now)
    decided_at: Optional[datetime] = Field(default=None)
