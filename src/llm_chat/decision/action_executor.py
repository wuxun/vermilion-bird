"""CardActionExecutor — 卡片选项确认文本生成。

GUI 端不使用此模块——点击卡片直接走 _continue_chat_from_card
启动新一轮 LLM 对话。此模块仅用于 Feishu 纯文本端的确认消息生成。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def execute_card_action(
    card: Any,          # DecisionCard
    option_id: str,
    client: Any = None, # Deprecated: 不再需要，保留兼容
    conversation_manager: Any = None,
) -> Dict[str, Any]:
    """返回卡片选项的确认文本（供 Feishu 等纯文本端使用）。

    GUI 端不调用此函数——卡片选择直接走 _continue_chat_from_card
    启动新一轮 LLM 对话，由 LLM 自主决定调用哪些工具。
    """
    selected = next(
        (o for o in card.options if o.id == option_id), None
    )
    if not selected:
        return {
            "success": False,
            "text": f"选项 {option_id} 不在卡片选项中",
            "action_type": None,
            "card_title": card.title,
            "option_label": "",
        }

    return {
        "success": True,
        "text": _build_option_confirmation(card, selected),
        "action_type": None,
        "card_title": card.title,
        "option_label": selected.label,
    }


def _build_option_confirmation(card, selected) -> str:
    """构建选项确认文本。"""
    parts = [f"你选择了: {selected.label}"]
    if selected.description:
        parts.append(f"\n{selected.description}")
    if selected.expected_effect:
        parts.append(f"\n预期: {selected.expected_effect}")
    return "".join(parts)
