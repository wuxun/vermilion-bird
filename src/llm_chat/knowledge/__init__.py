"""领域知识系统 — domain knowledge accumulation.

与 Memory 系统平行的独立层：
- Memory: 用户画像、偏好、行为模式
- Knowledge: 领域专业知识、技术约定、业务规则

架构:
    storage.py   — KnowledgeStorage (文件 I/O + 原子写入) + DomainDetector (关键词匹配)
    extractor.py — KnowledgeExtractor (LLM 提取/整合/提炼)
    manager.py   — KnowledgeManager (编排: 记录/注入/维护)
    templates.py — knowledge.md 初始模板
"""

from llm_chat.knowledge.storage import KnowledgeStorage, DomainDetector, DomainMeta, CATEGORY_LABELS
from llm_chat.knowledge.extractor import KnowledgeExtractor
from llm_chat.knowledge.manager import KnowledgeManager
from llm_chat.knowledge.templates import get_knowledge_template

__all__ = [
    "KnowledgeStorage",
    "DomainDetector",
    "DomainMeta",
    "KnowledgeExtractor",
    "KnowledgeManager",
    "get_knowledge_template",
]
