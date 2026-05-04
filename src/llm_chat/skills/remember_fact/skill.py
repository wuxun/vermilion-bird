"""remember_fact 技能 — 长期记忆读写。

提供 remember_fact（写入）和 read_facts（读取）两个工具，
让 LLM 既能存储新事实，也能查询已有事实，进行记忆整理/去重。
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


class RememberFactTool(BaseTool):
    """将一条重要事实/偏好/信息存入长期记忆「用户主动告知」章节。"""

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
    """读取长期记忆中已存储的用户事实，用于查询/去重/整理。"""

    @property
    def name(self) -> str:
        return "read_facts"

    @property
    def description(self) -> str:
        return (
            "读取长期记忆中已存储的所有用户事实。"
            "在调用 remember_fact 之前应先调用此工具检查是否已存在相同事实，避免重复。"
            "也可用于检查记忆状态或回答用户'你记得我吗'这类问题。"
        )

    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": (
                        "按分类筛选事实。留空则返回全部。"
                    ),
                    "enum": ["identity", "preference", "project",
                             "plan", "skill", "other"],
                    "default": "",
                },
                "keyword": {
                    "type": "string",
                    "description": (
                        "按关键词搜索（不区分大小写）。例如：'python'、'项目'。留空则不过滤。"
                    ),
                    "default": "",
                },
            },
        }

    def execute(self, category: str = "", keyword: str = "") -> str:
        try:
            storage = _get_storage()
            content = storage.load_long_term()

            # 提取「用户主动告知」章节
            ua_match = re.search(
                r'### 用户主动告知\n(.*?)(?=\n###|\n##|\Z)', content, re.DOTALL
            )
            if not ua_match:
                return "暂无用户主动告知的事实。"

            facts_text = ua_match.group(1).strip()
            if not facts_text:
                return "暂无用户主动告知的事实。"

            # 解析为行列表
            lines = [l.strip() for l in facts_text.split("\n") if l.strip().startswith("- ")]

            # 按分类过滤
            if category:
                label = CATEGORY_LABELS.get(category, category)
                lines = [l for l in lines if f"[{label}]" in l]

            # 按关键词过滤
            if keyword:
                kw = keyword.lower()
                lines = [l for l in lines if kw in l.lower()]

            if not lines:
                filter_desc = []
                if category:
                    filter_desc.append(f"分类={category}")
                if keyword:
                    filter_desc.append(f"关键词={keyword}")
                desc = " (" + ", ".join(filter_desc) + ")" if filter_desc else ""
                return f"未匹配到事实{desc}。"

            # 格式化输出
            result_parts = [f"共 {len(lines)} 条事实："]
            for i, line in enumerate(lines, 1):
                result_parts.append(f"{i}. {line[2:]}")  # 去掉 "- "

            return "\n".join(result_parts)

        except Exception as e:
            logger.error(f"读取事实失败: {e}")
            return f"❌ 读取事实失败: {str(e)}"


class RememberFactSkill(BaseSkill):
    """长期记忆技能 — 提供 remember_fact（写入）和 read_facts（读取）工具。"""

    @property
    def name(self) -> str:
        return "remember_fact"

    @property
    def description(self) -> str:
        return (
            "长期记忆管理：LLM 可主动写入用户事实（remember_fact），"
            "也可查询已有事实（read_facts）进行去重和整理。"
        )

    @property
    def version(self) -> str:
        return "1.1.0"

    def get_tools(self) -> List[BaseTool]:
        return [RememberFactTool(), ReadFactsTool()]
