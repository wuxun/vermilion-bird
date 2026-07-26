"""SemanticDomainDetector — embedding-based domain matching.

Upgrades from keyword-based DomainDetector to semantic search:
    - Embeds user query and domain descriptions
    - Computes cosine similarity
    - Additionally embeds domain keywords for hybrid matching
    - Falls back to keyword matching when embedder unavailable

Usage:
    detector = SemanticDomainDetector(storage)
    matches = detector.match("如何评估一家公司的投资价值")
    # -> [("investment", 0.78), ("finance", 0.65), ...]
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from llm_chat.knowledge.storage import KnowledgeStorage, DomainDetector, DomainMeta
from llm_chat.knowledge.embedder import KnowledgeEmbedder, get_embedder

logger = logging.getLogger(__name__)

# Default: domains with similarity below this are excluded
DEFAULT_SIMILARITY_THRESHOLD = 0.35


class SemanticDomainDetector:
    """Semantic domain detector using text embeddings.

    Compared to DomainDetector (keyword-only):
    - "投资策略" matches "investment strategy" domain even without exact keyword match
    - "怎么判断公司好坏" matches "企业评估" domain
    - CJK and English queries both work
    """

    def __init__(
        self,
        storage: KnowledgeStorage,
        embedder: Optional[KnowledgeEmbedder] = None,
        similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    ):
        self._storage = storage
        self._embedder = embedder or get_embedder()
        self._threshold = similarity_threshold

        # Fallback to keyword matching when embedder is n-gram only
        self._keyword_detector = DomainDetector(storage)

        # Pre-computed domain embeddings cache
        self._domain_embeddings: Dict[str, np.ndarray] = {}
        self._domain_texts: Dict[str, str] = {}
        self._loaded = False

    # ── Public API ────────────────────────────────────────────────

    def match(self, text: str) -> List[Tuple[str, float]]:
        """Match text against all domains using semantic + keyword hybrid.

        When sentence-transformers is available: true semantic matching.
        When not available: falls back to keyword-only matching via DomainDetector.

        Args:
            text: User query or message text

        Returns:
            [(domain_name, confidence_score), ...] sorted by score descending.
            Score range: 0.0–1.0, higher = more relevant.
        """
        if not text or not text.strip():
            return []

        # In semantic mode: use embeddings
        if self._embedder.is_semantic:
            return self._semantic_match(text)

        # Fallback: keyword matching (same behavior as old DomainDetector)
        return self._keyword_match(text)

    def match_domains(self, text: str, min_score: Optional[float] = None) -> List[str]:
        """Return matching domain names above threshold.

        Args:
            text: User query
            min_score: Override default threshold

        Returns:
            Domain name list, sorted by relevance
        """
        threshold = min_score if min_score is not None else self._threshold
        matched = self.match(text)
        return [name for name, score in matched if score >= threshold]

    # ── Internal ──────────────────────────────────────────────────

    def _keyword_match(self, text: str) -> List[Tuple[str, float]]:
        """Keyword-only matching via DomainDetector (fallback mode).

        Returns scores normalized to 0-1 range.
        """
        raw = self._keyword_detector.match(text)  # [(name, hit_count), ...]
        if not raw:
            return []
        max_hits = max(h for _, h in raw)
        return [(name, round(hits / max(1, max_hits), 4)) for name, hits in raw]

    def _semantic_match(self, text: str) -> List[Tuple[str, float]]:
        """True semantic matching using sentence-transformers embeddings."""
        self._ensure_loaded()

        if not self._domain_embeddings:
            return []

        query_emb = self._embedder.embed(text)

        scores: List[Tuple[str, float]] = []

        for domain_name, domain_emb in self._domain_embeddings.items():
            # Raw cosine similarity [-1, 1]
            sem_score = KnowledgeEmbedder.similarity(query_emb, domain_emb)

            # Negative cosine values are irrelevant. Do not shift cosine 0 to
            # 0.5, otherwise unrelated domains meet the default 0.35 hybrid
            # threshold with no keyword evidence.
            sem_score_norm = max(0.0, min(1.0, sem_score))

            # Keyword bonus (0-1)
            kw_score = self._keyword_bonus(text, domain_name)

            # Hybrid: 70% semantic + 30% keyword
            combined = 0.7 * sem_score_norm + 0.3 * kw_score

            if combined >= self._threshold:
                scores.append((domain_name, round(combined, 4)))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores

    # ── Cache & Embedding Management ──────────────────────────────

    def _ensure_loaded(self) -> None:
        """Lazy-load domain embeddings if needed."""
        domains = self._storage.get_all_domains()
        current_keys = set(domains.keys())

        # Check if we need reload (new/removed domains, or file changes)
        if self._loaded and current_keys == set(self._domain_embeddings.keys()):
            # Still check for file modification
            needs_reload = False
            for name in current_keys:
                meta = domains[name]
                cached_emb = self._embedder.get_cached(name, meta.file_path)
                if cached_emb is None:
                    needs_reload = True
                    break
            if not needs_reload:
                return

        self._reload(domains)
        self._loaded = True

    def _reload(self, domains: Dict[str, DomainMeta]) -> None:
        """Rebuild domain embeddings from storage.

        For each domain, embed: display_name + description + keywords.
        """
        self._domain_embeddings.clear()
        self._domain_texts.clear()

        for name, meta in domains.items():
            # Check cache first (keyed by file mtime)
            cached = self._embedder.get_cached(name, meta.file_path)
            if cached is not None:
                self._domain_embeddings[name] = cached
                continue

            # Build representative text for the domain
            parts = [meta.display_name or name]
            if meta.description:
                parts.append(meta.description)
            if meta.keywords:
                parts.append("关键词: " + ", ".join(meta.keywords))

            # Also include a snippet of the body for richer context
            body = self._storage.load_domain_body(name)
            if body:
                # Take first 500 chars as domain summary
                body_snippet = body[:500]
                parts.append(body_snippet)

            domain_text = " ".join(parts)
            self._domain_texts[name] = domain_text

            # Embed and cache
            emb = self._embedder.embed(domain_text)
            self._domain_embeddings[name] = emb
            self._embedder.set_cached(name, emb, meta.file_path)

        logger.debug(
            f"Loaded {len(self._domain_embeddings)} domain embeddings "
            f"({'semantic' if self._embedder.is_semantic else 'ngram'})"
        )

    def _keyword_bonus(self, text: str, domain_name: str) -> float:
        """Compute keyword match bonus (0-1 scale).

        Exact keyword matches give a boost on top of semantic similarity.
        """
        domains = self._storage.get_all_domains()
        meta = domains.get(domain_name)
        if not meta or not meta.keywords:
            return 0.0

        text_lower = text.lower()
        hits = sum(1 for kw in meta.keywords if kw.lower() in text_lower)
        if hits == 0:
            return 0.0

        # Normalize: 1 hit → 0.3, 2 hits → 0.6, 3+ → 1.0
        return min(1.0, hits / 3.0)

    def invalidate(self, domain_name: Optional[str] = None) -> None:
        """Invalidate cached embeddings.

        Args:
            domain_name: Specific domain to invalidate, or None for all.
        """
        if domain_name:
            self._embedder.invalidate(domain_name)
            self._domain_embeddings.pop(domain_name, None)
            self._domain_texts.pop(domain_name, None)
        else:
            self._domain_embeddings.clear()
            self._domain_texts.clear()
            self._loaded = False


# ── Factory ───────────────────────────────────────────────────────


def create_detector(
    storage: KnowledgeStorage,
    prefer_semantic: bool = True,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> "SemanticDomainDetector":
    """Create the best available detector.

    If sentence-transformers is installed, returns SemanticDomainDetector.
    Otherwise, SemanticDomainDetector still works with n-gram fallback
    (better than pure keyword matching).
    """
    embedder = get_embedder()
    return SemanticDomainDetector(
        storage=storage,
        embedder=embedder,
        similarity_threshold=similarity_threshold,
    )
