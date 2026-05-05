"""CardActionExecutor — 共享的卡片 action 执行逻辑。

GUI 和 Feishu 共用此模块执行卡片选项对应的 action，
避免两处维护相同的执行逻辑。

用法:
    from llm_chat.decision.action_executor import execute_card_action

    result = execute_card_action(
        card=card,
        option_id="A",
        client=app.client,
        conversation_manager=app.conversation_manager,
    )
    # result = {"success": True, "text": "修复方案...", "action_type": "execute_skill"}
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
