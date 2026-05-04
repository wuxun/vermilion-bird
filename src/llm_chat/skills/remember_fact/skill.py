"""remember_fact 技能 — 长期记忆读写删改。

提供读写删改全套工具，让 LLM 能主动管理长期记忆：
- read_facts: 查询已有事实
- remember_fact: 写入新事实
- update_fact: 修改已有事实
- delete_facts: 删除事实
- consolidate_facts: 合并多条事实（删除 + 新增合并版）
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
    """读取长期记忆中已存储的用户事实。"""

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
                    "description": "按分类筛选。留空返回全部。",
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

            ua_match = re.search(
                r'### 用户主动告知\n(.*?)(?=\n###|\n##|\Z)', content, re.DOTALL
            )
            if not ua_match:
                return "暂无用户主动告知的事实。"

            facts_text = ua_match.group(1).strip()
            if not facts_text:
                return "暂无用户主动告知的事实。"

            lines = [l.strip() for l in facts_text.split("\n") if l.strip().startswith("- ")]

            if category:
                label = CATEGORY_LABELS.get(category, category)
                lines = [l for l in lines if f"[{label}]" in l]

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

            result_parts = [f"共 {len(lines)} 条事实："]
            for i, line in enumerate(lines, 1):
                result_parts.append(f"{i}. {line[2:]}")

            return "\n".join(result_parts)

        except Exception as e:
            logger.error(f"读取事实失败: {e}")
            return f"❌ 读取事实失败: {str(e)}"


class UpdateFactTool(BaseTool):
    """修改一条已存储的用户事实。"""

    @property
    def name(self) -> str:
        return "update_fact"

    @property
    def description(self) -> str:
        return (
            "修改一条已存在的用户事实。先用 read_facts 查看已有事实，"
            "通过原内容中的关键词定位要修改的条目，然后用新内容替换。"
        )

    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "old_substring": {
                    "type": "string",
                    "description": (
                        "要修改的事实中的关键词或子串（不区分大小写），"
                        "用于定位要修改的条目。"
                    ),
                },
                "new_fact": {
                    "type": "string",
                    "description": "替换后的新事实内容（不含分类前缀，系统会自动添加）。",
                },
                "category": {
                    "type": "string",
                    "description": "事实分类。不传则保持原分类。",
                    "enum": ["identity", "preference", "project",
                             "plan", "skill", "other"],
                    "default": "",
                },
            },
            "required": ["old_substring", "new_fact"],
        }

    def execute(self, old_substring: str, new_fact: str, category: str = "") -> str:
        try:
            storage = _get_storage()
            if category:
                label = CATEGORY_LABELS.get(category, category)
                new_fact = f"[{label}] {new_fact}"

            success = storage.update_user_fact(old_substring, new_fact)
            if success:
                return f"已更新 ✓ {new_fact[:80]}"
            else:
                return f"未找到包含「{old_substring}」的事实，请先用 read_facts 确认。"

        except Exception as e:
            logger.error(f"更新事实失败: {e}")
            return f"❌ 更新事实失败: {str(e)}"


class DeleteFactsTool(BaseTool):
    """删除一条或多条用户事实。"""

    @property
    def name(self) -> str:
        return "delete_facts"

    @property
    def description(self) -> str:
        return (
            "删除一条或多条用户事实。先用 read_facts 查看已有事实，"
            "然后通过关键词定位要删除的条目。"
            "注意：关键词匹配不区分大小写，匹配到的所有条目都会被删除！"
        )

    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "关键词列表，包含任意关键词的事实都会被删除（不区分大小写）。"
                        "每个关键词应足够精确，避免误删。"
                    ),
                },
            },
            "required": ["keywords"],
        }

    def execute(self, keywords: List[str]) -> str:
        try:
            storage = _get_storage()
            if not keywords:
                return "请提供至少一个关键词。"

            count = storage.delete_user_facts(keywords)
            if count > 0:
                return f"已删除 {count} 条事实 ✓"
            else:
                return "未找到匹配的事实，请先用 read_facts 确认。"

        except Exception as e:
            logger.error(f"删除事实失败: {e}")
            return f"❌ 删除事实失败: {str(e)}"


class ConsolidateFactsTool(BaseTool):
    """合并多条事实为一条，同时删除原条目。"""

    @property
    def name(self) -> str:
        return "consolidate_facts"

    @property
    def description(self) -> str:
        return (
            "合并多条相似或相关的事实。先用 read_facts 查看，"
            "然后用关键词定位要合并的条目，系统会删除这些条目，"
            "并写入一条合并后的事实。用于减少重复、精简记忆。"
        )

    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "delete_keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "要删除的旧事实的关键词列表，匹配的所有条目都会被删除。"
                    ),
                },
                "consolidated_fact": {
                    "type": "string",
                    "description": "合并后的事实，应包含原始所有条目的关键信息。",
                },
                "category": {
                    "type": "string",
                    "description": "合并后事实的分类。",
                    "enum": ["identity", "preference", "project",
                             "plan", "skill", "other"],
                    "default": "preference",
                },
            },
            "required": ["delete_keywords", "consolidated_fact"],
        }

    def execute(self, delete_keywords: List[str], consolidated_fact: str,
                category: str = "preference") -> str:
        try:
            storage = _get_storage()
            if not delete_keywords or not consolidated_fact:
                return "请提供关键词列表和合并后的事实。"

            # 删除旧条目
            deleted = storage.delete_user_facts(delete_keywords)

            # 写入合并后的事实
            label = CATEGORY_LABELS.get(category, category)
            tagged_fact = f"[{label}] {consolidated_fact}"
            storage.add_user_fact(tagged_fact)

            return f"已合并 ✓ 删除了 {deleted} 条旧事实，新增合并版本 [{label}]: {consolidated_fact[:80]}"

        except Exception as e:
            logger.error(f"合并事实失败: {e}")
            return f"❌ 合并事实失败: {str(e)}"


class RememberFactSkill(BaseSkill):
    """长期记忆技能 — 提供读写删改全套工具。"""

    @property
    def name(self) -> str:
        return "remember_fact"

    @property
    def description(self) -> str:
        return (
            "长期记忆管理：LLM 可读写删改用户事实，"
            "进行去重、合并、整理等操作以维持记忆精简。"
        )

    @property
    def version(self) -> str:
        return "1.2.0"

    def get_tools(self) -> List[BaseTool]:
        return [
            RememberFactTool(),
            ReadFactsTool(),
            UpdateFactTool(),
            DeleteFactsTool(),
            ConsolidateFactsTool(),
        ]
