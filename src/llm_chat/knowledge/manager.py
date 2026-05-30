"""KnowledgeManager — 领域知识编排器。

职责：
- 记录对话 → 计数 → 触发提取
- 构建 system prompt 注入块（渐进式披露）
- 周期维护：整合 / 提炼
- 新领域检测与创建

与 MemoryManager 并行，单例由 ConversationManager 持有。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, List, Optional, TYPE_CHECKING

from llm_chat.knowledge.storage import KnowledgeStorage, DomainDetector, DomainMeta
from llm_chat.knowledge.extractor import KnowledgeExtractor
import re as _re_module

if TYPE_CHECKING:
    from llm_chat.memory.summarizer import Summarizer

logger = logging.getLogger(__name__)


class KnowledgeManager:
    """领域知识核心编排器。

    三个入口：
    - record_conversation() — 管道每轮调用，累计计数 + 触发提取/整合/提炼
    - build_knowledge_context() — SystemContextStage 调用，注入 system prompt
    - 内部自动周期维护
    """

    def __init__(
        self,
        storage: Optional[KnowledgeStorage] = None,
        summarizer: Optional["Summarizer"] = None,
        config: Optional[Dict] = None,
    ):
        self.storage = storage or KnowledgeStorage()
        self._summarizer = summarizer
        self.extractor = KnowledgeExtractor(summarizer=summarizer)
        self.config = config or {}

        # 轮次计数（用于触发提取）
        self._conversation_count = 0
        self._extraction_interval = self.config.get("extraction_interval", 20)
        self._consolidate_min_entries = self.config.get("consolidate_min_entries", 10)
        self._refine_min_total = self.config.get("refine_min_total", 50)
        self._max_knowledge_tokens = self.config.get("max_knowledge_tokens", 300)

        # 防止频繁 LLM 调用
        self._last_extraction_time = datetime.now()
        self._min_extraction_interval_secs = 300  # 5 分钟

    # ------------------------------------------------------------------
    # 公共 API — 管道调用
    # ------------------------------------------------------------------

    def record_conversation(
        self, user_message: str, assistant_response: str
    ) -> None:
        """记录一轮对话，触发周期维护。

        Args:
            user_message: 用户消息
            assistant_response: LLM 响应
        """
        self._conversation_count += 1

        # 触发提取
        if self._conversation_count >= self._extraction_interval:
            elapsed = (datetime.now() - self._last_extraction_time).total_seconds()
            if elapsed >= self._min_extraction_interval_secs:
                try:
                    self._extract_from_recent(
                        [{"role": "user", "content": user_message},
                         {"role": "assistant", "content": assistant_response}]
                    )
                except Exception as e:
                    logger.warning(f"领域知识提取失败: {e}")
                self._conversation_count = 0
                self._last_extraction_time = datetime.now()

    def build_knowledge_context(self, user_message: str) -> str:
        """构建领域知识的 system prompt 注入块。

        渐进式披露：
        - type=always 的领域：注入全文（受 token 预算限制）
        - type=requested/manual 的领域：注入一行摘要

        Args:
            user_message: 当前用户消息

        Returns:
            注入文本，无匹配时返回 ""
        """
        if not user_message:
            return ""

        all_domains = self.storage.get_all_domains()
        if not all_domains:
            return ""

        detector = DomainDetector(self.storage)
        keyword_matched = detector.match(user_message)
        matched_names = set(name for name, _hits in keyword_matched)

        token_budget = self._max_knowledge_tokens
        always_parts = []
        summary_lines = []

        # type=always 领域：无条件注入（跳过关键词过滤，始终注入全文）
        # 预算公平分配：每个 always 领域至少得到 budget // count
        all_always = [n for n, m in all_domains.items() if m.type == "always"]
        per_domain_budget = max(100, token_budget // max(1, len(all_always))) if all_always else 0
        for name in all_always:
            meta = all_domains[name]
            body = self.storage.load_domain_body(name)
            if body and token_budget > 50:
                cap = min(token_budget, per_domain_budget)
                truncated = self._truncate_by_token_estimate(body, cap)
                always_parts.append(
                    f"## 领域知识：{meta.display_name}\n{truncated}"
                )
                token_budget -= self._estimate_tokens(truncated)

        # type=requested/manual 领域：仅关键词匹配时注入一行摘要
        for name, _hits in keyword_matched:
            meta = all_domains.get(name)
            if meta is None or meta.type == "always":
                continue  # always 已处理
            summary_lines.append(
                f"- **{meta.display_name}** (`{name}`): {meta.description}"
                f" | 知识点: {meta.fact_count} 条"
            )

        parts = []
        if always_parts:
            parts.append("\n\n".join(always_parts))
        if summary_lines:
            header = "## 领域知识库 (用 read_knowledge 工具加载全文)\n"
            parts.append(header + "\n".join(summary_lines))

        if not parts:
            return ""

        result = "\n\n".join(parts)
        logger.debug(
            f"注入领域知识: {len(keyword_matched)} 个领域, "
            f"{self._estimate_tokens(result)} tokens"
        )
        return result

    # ------------------------------------------------------------------
    # 内部 — 提取
    # ------------------------------------------------------------------

    def _extract_from_recent(self, messages: List[Dict]) -> None:
        """从近期消息中提取领域知识。

        流程：
        1. DomainDetector 匹配涉及的领域
        2. 对每个领域：LLM 提取知识点 → 追加
        3. 尝试检测新领域
        4. 检查整合 / 提炼触发条件
        """
        if not self._summarizer:
            return

        # 拼接消息文本用于匹配
        text = " ".join(
            m.get("content", "")[:200] for m in messages[-5:]
        )
        if not text.strip():
            return

        detector = DomainDetector(self.storage)
        matched = detector.match_domains(text, min_hits=2)
        all_domains = self.storage.get_all_domains()

        # 1. 对已匹配领域提取知识（使用 display_name）
        for domain_name in matched:
            try:
                meta = all_domains.get(domain_name)
                display_name = meta.display_name if meta else domain_name
                facts = self.extractor.extract_facts(
                    messages, display_name
                )
                for item in facts:
                    self.storage.append_fact(
                        domain_name, item["fact"], item["category"]
                    )
            except Exception as e:
                logger.warning(f"提取 {domain_name} 知识失败: {e}")

        # 2. 尝试检测新领域（未匹配到任何已有领域时）
        if not matched:
            try:
                suggestion = self.extractor.suggest_new_domain(messages)
                if suggestion:
                    if not self.storage.domain_exists(suggestion["name"]):
                        self.storage.create_domain(
                            suggestion["name"],
                            suggestion["display_name"],
                            description=suggestion.get("description", ""),
                            keywords=suggestion.get("keywords", []),
                        )
                        logger.info(
                            f"自然涌现新领域: {suggestion['display_name']} "
                            f"({suggestion['name']})"
                        )
            except Exception as e:
                logger.warning(f"检测新领域失败: {e}")

        # 3. 检查维护触发
        self._maintain_domains(matched)

    # ------------------------------------------------------------------
    # 内部 — 维护 (整合 + 提炼)
    # ------------------------------------------------------------------

    def _maintain_domains(self, domain_names: List[str]) -> None:
        """检查并触发整合/提炼。"""
        for name in domain_names:
            self._maybe_consolidate(name)
            self._maybe_refine(name)

    def _maybe_consolidate(self, domain_name: str) -> bool:
        """检查是否需要整合（未整理条目 ≥ 阈值）。"""
        unconsolidated = self.storage.get_unconsolidated_count(domain_name)
        if unconsolidated < self._consolidate_min_entries:
            return False

        if not self._summarizer:
            return False

        logger.info(
            f"触发整合: {domain_name} (未整理 {unconsolidated} 条 ≥ "
            f"{self._consolidate_min_entries})"
        )

        try:
            content = self.storage.load_domain(domain_name)
            if not content:
                return False

            new_content = self.extractor.consolidate_domain(content, domain_name)
            if new_content:
                self.storage.save_domain(domain_name, new_content)
                logger.info(f"整合完成: {domain_name}")
                return True
        except Exception as e:
            logger.warning(f"整合 {domain_name} 失败: {e}")

        return False

    def _maybe_refine(self, domain_name: str) -> bool:
        """检查是否需要提炼（总知识点 ≥ 阈值）。"""
        meta = self.storage.get_domain_meta(domain_name)
        if meta is None:
            return False

        if meta.fact_count < self._refine_min_total:
            return False

        if not self._summarizer:
            return False

        logger.info(
            f"触发提炼: {domain_name} (总知识点 {meta.fact_count} ≥ "
            f"{self._refine_min_total})"
        )

        try:
            content = self.storage.load_domain(domain_name)
            if not content:
                return False

            new_content = self.extractor.refine_domain(content, domain_name)
            if new_content:
                self.storage.save_domain(domain_name, new_content)
                logger.info(f"提炼完成: {domain_name}")
                return True
        except Exception as e:
            logger.warning(f"提炼 {domain_name} 失败: {e}")

        return False

    # ------------------------------------------------------------------
    # Token 估算（对齐 MemoryManager 的实现）
    # ------------------------------------------------------------------

    _CJK_RE = _re_module.compile(
        r"[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af]"
    )

    @classmethod
    def _estimate_tokens(cls, text: str) -> int:
        """粗略估算 token 数（中文 ≈ 1 字=1 token，英文 ≈ 4 字符=1 token）。"""
        if not text:
            return 0
        cjk = len(cls._CJK_RE.findall(text))
        other = len(text) - cjk
        return cjk + (other // 4)

    @classmethod
    def _truncate_by_token_estimate(cls, text: str, max_tokens: int) -> str:
        """按 token 预算截断文本，保留完整行。"""
        if not text or max_tokens <= 0:
            return ""
        lines = text.split("\n")
        result = []
        current = 0
        for line in lines:
            lt = cls._estimate_tokens(line)
            if current + lt > max_tokens:
                break
            result.append(line)
            current += lt
        return "\n".join(result)

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------

    def get_stats(self) -> Dict:
        """获取知识系统统计信息。"""
        domains = self.storage.get_all_domains()
        total_facts = sum(m.fact_count for m in domains.values())
        return {
            "domain_count": len(domains),
            "total_facts": total_facts,
            "domains": {
                name: {
                    "display_name": m.display_name,
                    "fact_count": m.fact_count,
                    "type": m.type,
                    "unconsolidated": self.storage.get_unconsolidated_count(name),
                }
                for name, m in domains.items()
            },
        }
