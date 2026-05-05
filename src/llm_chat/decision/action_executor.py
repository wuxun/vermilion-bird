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
    client: Any,        # LLMClient
    conversation_manager: Any = None,
) -> Dict[str, Any]:
    """执行卡片选项对应的 action。

    Args:
        card: 决策卡片实例。
        option_id: 用户选择的选项 ID。
        client: LLM 客户端，用于生成修复代码等。
        conversation_manager: 可选，用于创建对话（GUI 场景）。

    Returns:
        {
            "success": bool,
            "text": str,           # 执行结果文本
            "action_type": str,    # execute_skill | approve | reject | None
            "card_title": str,
            "option_label": str,
        }
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

    action = getattr(selected, "action", None)

    if not action or not isinstance(action, dict) or not action.get("type"):
        # 无 action：默认行为，返回确认文本
        return {
            "success": True,
            "text": _build_option_confirmation(card, selected),
            "action_type": None,
            "card_title": card.title,
            "option_label": selected.label,
        }

    action_type = action["type"]

    if action_type == "execute_skill":
        return _execute_skill_action(card, selected, action, client)

    elif action_type == "approve":
        return {
            "success": True,
            "text": f"✅ 已批准: {selected.label}",
            "action_type": "approve",
            "card_title": card.title,
            "option_label": selected.label,
        }

    elif action_type == "reject":
        return {
            "success": True,
            "text": f"❌ 已驳回: {selected.label}",
            "action_type": "reject",
            "card_title": card.title,
            "option_label": selected.label,
        }

    else:
        return {
            "success": True,
            "text": _build_option_confirmation(card, selected),
            "action_type": action_type,
            "card_title": card.title,
            "option_label": selected.label,
        }


def _execute_skill_action(
    card, selected, action: dict, client
) -> Dict[str, Any]:
    """执行 execute_skill 类型的 action。

    当前支持 skill="file_editor" 场景：
    基于审查结果调用 LLM 生成修复代码。
    """
    skill = action.get("skill", "")
    description = action.get("description", "执行操作")

    if skill == "file_editor" and "review_results" in action:
        review_text = "\n\n".join(
            f"### {name}\n{result}"
            for name, result in action["review_results"].items()
        )
        fix_prompt = (
            "你是一位资深代码审查工程师。以下是代码审查结果，"
            "请根据每个问题生成具体的修复代码。\n\n"
            f"## 审查结果\n{review_text}\n\n"
            "## 要求\n"
            "1. 对每个问题输出修复后的代码片段\n"
            "2. 在修改处标注修复说明\n"
            "3. 不要改变原有功能逻辑"
        )
        try:
            fix_response = client.chat(
                message=fix_prompt,
                temperature=0.2,
                max_tokens=3000,
            )
            result_text = (
                f"## ✅ {description}\n\n"
                f"{fix_response}\n\n"
                f"---\n*你可以继续要求调整。*"
            )
            return {
                "success": True,
                "text": result_text,
                "action_type": "execute_skill",
                "card_title": card.title,
                "option_label": selected.label,
            }
        except Exception as e:
            logger.error(f"action 执行失败: {e}")
            return {
                "success": False,
                "text": f"❌ 执行失败: {e}",
                "action_type": "execute_skill",
                "card_title": card.title,
                "option_label": selected.label,
            }

    # 其他 skill 类型：返回确认
    return {
        "success": True,
        "text": _build_option_confirmation(card, selected),
        "action_type": "execute_skill",
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
