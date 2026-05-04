"""remember_fact 技能 — 将重要事实直接存储到长期记忆。

提供 remember_fact 工具，LLM 可在检测到用户重要偏好、背景、计划等信息时主动调用。
用户也可通过 /记住 快捷指令或 CLI 直接写入，不走 LLM。
"""

import logging
from typing import Dict, Any, List

from llm_chat.skills.base import BaseSkill
from llm_chat.tools.base import BaseTool

logger = logging.getLogger(__name__)


class RememberFactTool(BaseTool):
    """将一条重要事实/偏好/信息存入长期记忆「用户主动告知」章节。

    用途：当用户明确说出值得长期记住的信息时使用。
    示例：
    - 用户说"我的项目部署在 AWS us-east-1" → 记录
    - 用户说"我喜欢用 black 格式化代码，行宽 100" → 记录
    - 用户说"我通常工作到晚上 10 点" → 记录
    """

    @property
    def name(self) -> str:
        return "remember_fact"

    @property
    def description(self) -> str:
        return (
            "将一条重要事实/偏好/计划存储到长期记忆。"
            "当用户明确说出值得长期记住的信息时使用此工具。"
            "这些信息将持久保存并在后续对话中自动注入到系统提示上下文。"
        )

    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "fact": {
                    "type": "string",
                    "description": (
                        "要记住的事实。用简洁的一句话描述，包含关键信息。"
                        "例如：'用户最喜欢的代码格式化工具是 black，行宽 100'"
                    ),
                },
                "category": {
                    "type": "string",
                    "description": (
                        "事实分类，帮助记忆系统组织信息。可选值："
                        "identity(身份背景), preference(偏好), project(项目信息), "
                        "plan(计划), skill(技能), other(其他)"
                    ),
                    "enum": [
                        "identity", "preference", "project",
                        "plan", "skill", "other"
                    ],
                    "default": "preference",
                },
            },
            "required": ["fact"],
        }

    def execute(self, fact: str, category: str = "preference") -> str:
        try:
            from llm_chat.memory import MemoryStorage

            storage = MemoryStorage()

            # 构建带分类前缀的事实条目
            category_labels = {
                "identity": "身份",
                "preference": "偏好",
                "project": "项目",
                "plan": "计划",
                "skill": "技能",
                "other": "其他",
            }
            label = category_labels.get(category, category)
            tagged_fact = f"[{label}] {fact}"

            storage.add_user_fact(tagged_fact)
            logger.info(f"记住事实 [{label}]: {fact[:100]}...")
            return f"已记住 ✓ [{label}]: {fact}"

        except Exception as e:
            logger.error(f"记住事实失败: {e}")
            return f"❌ 记住事实失败: {str(e)}"


class RememberFactSkill(BaseSkill):
    """记住重要事实技能 — 提供 remember_fact 工具。"""

    @property
    def name(self) -> str:
        return "remember_fact"

    @property
    def description(self) -> str:
        return (
            "长期记忆增强：当用户说出重要信息时，"
            "LLM 可主动调用 remember_fact 工具存储到长期记忆。"
            "用户也可用 /记住 快捷指令或 CLI 直接写入。"
        )

    @property
    def version(self) -> str:
        return "1.0.0"

    def get_tools(self) -> List[BaseTool]:
        return [RememberFactTool()]
