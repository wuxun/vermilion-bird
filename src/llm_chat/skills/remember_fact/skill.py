"""remember_fact 技能 — 长期记忆读写。

提供 remember_fact（写入）和 read_facts（读取）两个工具。
删改/去重/合并由 MemoryManager 后台自动进化完成。
"""

import logging
import re
from typing import Dict, Any, List

from llm_chat.skills.base import BaseSkill
from llm_chat.tools.base import BaseTool

logger = logging.getLogger(__name__)

CATEGORY_LABELS = {
    "identity": "身份",
    "preference": "偏好",
    "project": "项目",
    "plan": "计划",
    "skill": "技能",
    "other": "其他",
}


def _get_storage():
    from llm_chat.memory import MemoryStorage
    return MemoryStorage()


def _parse_user_facts(content: str) -> List[str]:
    """从 long_term.md 内容中提取所有用户事实行。"""
    match = re.search(
        r'### 用户主动告知\n(.*?)(?=\n###|\n##|\Z)', content, re.DOTALL
    )
    if not match:
        return []
    text = match.group(1).strip()
    return [l.strip() for l in text.split("\n") if l.strip().startswith("- ")]


class RememberFactTool(BaseTool):
    """> **写入**：将一条重要事实存储到长期记忆。

    当用户明确说出值得长期记住的信息时使用。
    后台系统会自动去重、合并、整理，无需手动管理。
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
            "后台系统会定期自动去重和整理，无需手动管理。"
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
                        "事实分类：identity(身份背景), preference(偏好), project(项目), "
                        "plan(计划), skill(技能), other(其他)"
                    ),
                    "enum": list(CATEGORY_LABELS.keys()),
                    "default": "preference",
                },
            },
            "required": ["fact"],
        }

    def execute(self, fact: str, category: str = "preference") -> str:
        try:
            storage = _get_storage()
            label = CATEGORY_LABELS.get(category, category)
            tagged_fact = f"[{label}] {fact}"

            storage.add_user_fact(tagged_fact)
            logger.info(f"记住事实 [{label}]: {fact[:100]}...")
            return f"已记住 ✓ [{label}]: {fact}"

        except Exception as e:
            logger.error(f"记住事实失败: {e}")
            return f"❌ 记住事实失败: {str(e)}"


class ReadFactsTool(BaseTool):
    """> **读取**：查询长期记忆中已存储的用户事实。

    用于回答"你记得我吗"这类问题，或在写入前检查是否已存在。
    """

    @property
    def name(self) -> str:
        return "read_facts"

    @property
    def description(self) -> str:
        return (
            "读取长期记忆中已存储的所有用户事实。"
            "可用于回答用户'你记得我吗'这类问题，"
            "或在调用 remember_fact 之前检查是否已存在相同事实。"
        )

    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": (
                        "按关键词搜索（不区分大小写）。留空返回全部。"
                    ),
                    "default": "",
                },
            },
        }

    def execute(self, keyword: str = "") -> str:
        try:
            storage = _get_storage()
            lines = _parse_user_facts(storage.load_long_term())
            if not lines:
                return "暂无用户主动告知的事实。"

            if keyword:
                kw = keyword.lower()
                lines = [l for l in lines if kw in l.lower()]

            if not lines:
                return f"未匹配到包含「{keyword}」的事实。"

            result = [f"共 {len(lines)} 条事实："]
            for i, line in enumerate(lines, 1):
                result.append(f"{i}. {line[2:]}")

            return "\n".join(result)

        except Exception as e:
            logger.error(f"读取事实失败: {e}")
            return f"❌ 读取事实失败: {str(e)}"


class RememberFactSkill(BaseSkill):
    """长期记忆技能 — 读写用户事实。后台自动进化管理。"""

    @property
    def name(self) -> str:
        return "remember_fact"

    @property
    def description(self) -> str:
        return "长期记忆管理：LLM 可写入和查询用户事实。"

    @property
    def version(self) -> str:
        return "1.0.0"

    def get_tools(self) -> List[BaseTool]:
        return [RememberFactTool(), ReadFactsTool()]
