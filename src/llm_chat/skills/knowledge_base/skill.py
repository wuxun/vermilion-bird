"""knowledge_base 技能 — 领域知识的读写。

对齐 PromptSkill 渐进式披露模式：
- 默认在 system prompt 中只注入领域名 + 描述（摘要）
- LLM 需要详细信息时调用 read_knowledge 加载全文
- LLM 识别到新知识时调用 remember_knowledge 显式写入
"""

import logging
from typing import Dict, Any, List, Optional

from llm_chat.skills.base import BaseSkill
from llm_chat.tools.base import BaseTool
from llm_chat.knowledge.storage import KnowledgeStorage, CATEGORY_LABELS  # 单一来源

logger = logging.getLogger(__name__)

# 全局存储实例 — 默认创建，可由 App 注入覆盖（确保与 pipeline 共享同一实例）
_storage_instance: Optional[KnowledgeStorage] = None


def _get_storage() -> KnowledgeStorage:
    """获取共享 KnowledgeStorage 实例（懒初始化 + 可注入）。"""
    global _storage_instance
    if _storage_instance is None:
        _storage_instance = KnowledgeStorage()
    return _storage_instance


def set_storage(storage: KnowledgeStorage) -> None:
    """注入共享 KnowledgeStorage 实例（由 App 调用以统一 pipeline 和 skill 的存储）。"""
    global _storage_instance
    _storage_instance = storage


# ---------------------------------------------------------------------------
# ReadKnowledgeTool
# ---------------------------------------------------------------------------


class ReadKnowledgeTool(BaseTool):
    """> **读取**：加载指定领域的完整知识。

    当对话涉及某个领域，需要参考已积累的专业知识时使用。
    System prompt 中只注入了领域摘要，调用此工具获取全文。
    """

    @property
    def name(self) -> str:
        return "read_knowledge"

    @property
    def description(self) -> str:
        return (
            "加载指定领域的完整知识。"
            "当对话涉及某个领域，需要参考已积累的专业知识时使用此工具。"
            "System prompt 中只列出了可用领域摘要，此工具获取全文细节。"
            "如果领域不存在，返回可用领域列表。"
        )

    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "领域标识符，如 'investment'、'machine-learning'。"
                    "从 system prompt 的领域摘要列表中获取。",
                },
            },
            "required": ["domain"],
        }

    def execute(self, domain: str) -> str:
        try:
            storage = _get_storage()
            content = storage.load_domain_body(domain)

            if content:
                meta = storage.get_domain_meta(domain)
                header = (
                    f"## 领域知识：{meta.display_name if meta else domain}\n\n"
                )
                return header + content

            # 领域不存在 → 列出可用领域
            all_domains = storage.get_all_domains()
            if not all_domains:
                return (
                    f"领域 '{domain}' 不存在，且暂无任何领域知识。"
                    f"使用 remember_knowledge 工具创建第一个领域。"
                )

            lines = [
                f"领域 '{domain}' 不存在。可用的领域：",
            ]
            for name, meta in sorted(all_domains.items()):
                kw_preview = (
                    ", ".join(meta.keywords[:3]) if meta.keywords else "无关键词"
                )
                lines.append(
                    f"  - **{meta.display_name}** (`{name}`): {meta.description}"
                    f" | 关键词: {kw_preview} | 知识点: {meta.fact_count} 条"
                )
            return "\n".join(lines)

        except Exception as e:
            logger.error(f"读取领域知识失败: {e}")
            return f"❌ 读取领域知识失败: {str(e)}"


# ---------------------------------------------------------------------------
# RememberKnowledgeTool
# ---------------------------------------------------------------------------


class RememberKnowledgeTool(BaseTool):
    """> **写入**：将一条领域知识存储到指定领域。

    当对话中出现了值得长期记住的领域专业知识时使用。
    领域不存在时自动创建。
    """

    @property
    def name(self) -> str:
        return "remember_knowledge"

    @property
    def description(self) -> str:
        return (
            "将一条领域专业知识存储到指定领域。"
            "当对话中出现了值得长期记住的领域知识时使用此工具（技术约定、业务规则、"
            "最佳实践、经验教训等）。"
            "领域不存在时会自动创建。"
            "这些知识将在后续涉及该领域的对话中自动注入到系统提示上下文。"
        )

    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": (
                        "领域标识符，英文简写，如 'investment'、'machine-learning'。"
                        "如果是新领域，此名称将用作文件名。"
                    ),
                },
                "fact": {
                    "type": "string",
                    "description": (
                        "要记住的知识点。用简洁的一句话描述，包含关键信息。"
                        "例如：'PyTorch 2.0 的 torch.compile 可提速 30-50%'"
                    ),
                },
                "category": {
                    "type": "string",
                    "description": (
                        "知识分类：concept(概念术语), strategy(策略方法), "
                        "experience(经验教训), reference(资源参考), other(其他)"
                    ),
                    "enum": list(CATEGORY_LABELS.keys()),
                    "default": "other",
                },
                "display_name": {
                    "type": "string",
                    "description": (
                        "领域显示名（仅新建领域时需要）。中文名，如 '投资'、'机器学习'。"
                        "已有领域不需要此参数。"
                    ),
                },
                "description": {
                    "type": "string",
                    "description": (
                        "领域简短描述（仅新建领域时需要）。"
                        "一句话说明该领域涵盖什么。"
                    ),
                },
                "keywords": {
                    "type": "string",
                    "description": (
                        "逗号分隔的关键词（仅新建领域时需要）。"
                        "用于自动检测对话是否涉及该领域。"
                        "例如：'股票,基金,A股,PE,ROE'"
                    ),
                },
            },
            "required": ["domain", "fact"],
        }

    def execute(
        self,
        domain: str,
        fact: str,
        category: str = "other",
        display_name: str = "",
        description: str = "",
        keywords: str = "",
    ) -> str:
        try:
            storage = _get_storage()

            # 领域不存在 → 自动创建
            if not storage.domain_exists(domain):
                if not display_name:
                    # 没有显示名 → 用 domain 本身
                    display_name = domain
                if not description:
                    description = f"{display_name}领域专业知识"
                kw_list = (
                    [k.strip() for k in keywords.split(",") if k.strip()]
                    if keywords
                    else []
                )

                try:
                    storage.create_domain(
                        domain,
                        display_name,
                        description=description,
                        keywords=kw_list,
                    )
                    logger.info(
                        f"自动创建新领域: {display_name} ({domain}), "
                        f"关键词: {kw_list}"
                    )
                except FileExistsError:
                    # 竞态：另一个线程已创建，继续
                    pass

            # 追加知识点
            ok = storage.append_fact(domain, fact, category)
            if not ok:
                return f"❌ 写入失败：无法追加到领域 '{domain}'"

            label = CATEGORY_LABELS.get(category, category)
            meta = storage.get_domain_meta(domain)
            count = meta.fact_count if meta else "?"

            return (
                f"已记住 ✓ [{label}] → {domain}\n"
                f"知识点: {fact[:120]}\n"
                f"该领域累计: {count} 条"
            )

        except Exception as e:
            logger.error(f"记住领域知识失败: {e}")
            return f"❌ 记住领域知识失败: {str(e)}"


# ---------------------------------------------------------------------------
# KnowledgeBaseSkill
# ---------------------------------------------------------------------------


class KnowledgeBaseSkill(BaseSkill):
    """领域知识管理技能 — LLM 可读写领域知识。

    渐进式披露：
    - System prompt 中只注入领域摘要（领域名 + 描述）
    - LLM 需要详细知识时调用 read_knowledge
    - LLM 识别到新知识时调用 remember_knowledge
    - 新领域自动创建（自然涌现）
    """

    @property
    def name(self) -> str:
        return "knowledge_base"

    @property
    def description(self) -> str:
        return (
            "领域知识管理：LLM 可读写领域专业知识。"
            "支持渐进式披露：默认只显示摘要，需要时加载全文。"
            "新领域自动创建（自然涌现）。"
        )

    @property
    def version(self) -> str:
        return "1.0.0"

    def get_tools(self) -> List[BaseTool]:
        return [ReadKnowledgeTool(), RememberKnowledgeTool()]
