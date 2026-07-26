"""KnowledgeEmbedder — lightweight text embedding with optional sentence-transformers.

Strategy:
    - Try sentence-transformers (all-MiniLM-L6-v2) if installed
    - Fall back to TF-IDF-like character n-gram similarity (zero-dependency)
    - Cache embeddings per domain, invalidate on file modification

Usage:
    embedder = KnowledgeEmbedder()
    embedding = embedder.embed("some text")  # -> np.ndarray
    score = embedder.similarity(emb1, emb2)  # -> float (cosine)
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

# Multilingual is the safe default for this Chinese-first application.
DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
# Smaller English-oriented fallback for resource-constrained environments.
FALLBACK_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


class KnowledgeEmbedder:
    """Lightweight text embedding with smart fallback.

    Cache key: md5(domain_name + file_mtime) — auto-invalidates on file change.
    """

    def __init__(self, model_name: Optional[str] = None):
        self._model = None
        self._model_name = model_name or DEFAULT_MODEL
        self._use_transformers = False

        # Embedding cache: key → np.ndarray
        self._cache: Dict[str, np.ndarray] = {}
        self._cache_domains: Dict[str, str] = {}

        # Try to load sentence-transformers
        self._try_load_model()

    def _try_load_model(self) -> None:
        """Attempt to load sentence-transformers. Falls back silently."""
        try:
            from sentence_transformers import SentenceTransformer  # noqa: F811

            try:
                self._model = SentenceTransformer(self._model_name)
                self._use_transformers = True
                dim = self._model.get_sentence_embedding_dimension()
                logger.info(f"Loaded embedding model: {self._model_name} (dim={dim})")
            except Exception as e:
                logger.warning(
                    f"Failed to load {self._model_name}: {e}. "
                    f"Trying fallback {FALLBACK_MODEL}..."
                )
                try:
                    self._model = SentenceTransformer(FALLBACK_MODEL)
                    self._use_transformers = True
                    self._model_name = FALLBACK_MODEL
                    dim = self._model.get_sentence_embedding_dimension()
                    logger.info(f"Loaded fallback model: {FALLBACK_MODEL} (dim={dim})")
                except Exception as e2:
                    logger.warning(f"Fallback also failed: {e2}. Using n-gram fallback.")
        except ImportError:
            logger.info(
                "sentence-transformers not installed. "
                "Using character n-gram embedding fallback. "
                "Install with: pip install sentence-transformers"
            )

    @property
    def is_semantic(self) -> bool:
        """Whether we're using true semantic embeddings (vs n-gram fallback)."""
        return self._use_transformers

    @property
    def dimension(self) -> int:
        """Embedding dimension."""
        if self._use_transformers and self._model:
            return self._model.get_sentence_embedding_dimension()
        return 256  # n-gram fallback dimension

    # ── Public API ────────────────────────────────────────────────

    def embed(self, text: str) -> np.ndarray:
        """Embed a single text into a vector.

        Args:
            text: Text to embed (truncated to ~512 tokens for efficiency)

        Returns:
            numpy array of shape (dimension,)
        """
        if not text or not text.strip():
            return np.zeros(self.dimension, dtype=np.float32)

        # Truncate for efficiency (MiniLM max is 512 tokens, ~2000 chars CJK)
        truncated = text[:2000]

        if self._use_transformers and self._model:
            return self._model.encode(truncated, normalize_embeddings=True)
        else:
            return self._ngram_embed(truncated)

    def embed_batch(self, texts: List[str]) -> np.ndarray:
        """Embed multiple texts. Returns (n, dim) array."""
        if not texts:
            return np.zeros((0, self.dimension), dtype=np.float32)

        truncated = [t[:2000] for t in texts]

        if self._use_transformers and self._model:
            return self._model.encode(truncated, normalize_embeddings=True)
        else:
            return np.array([self._ngram_embed(t) for t in truncated])

    @staticmethod
    def similarity(a: np.ndarray, b: np.ndarray) -> float:
        """Cosine similarity between two vectors.

        Returns:
            float in [-1, 1], higher = more similar
        """
        a_norm = np.linalg.norm(a)
        b_norm = np.linalg.norm(b)
        if a_norm == 0 or b_norm == 0:
            return 0.0
        return float(np.dot(a, b) / (a_norm * b_norm))

    # ── Cache management ──────────────────────────────────────────

    def _cache_key(self, domain_name: str, file_path: Optional[Path] = None) -> str:
        """Generate cache key from domain name + file modification time."""
        mtime = ""
        if file_path and file_path.exists():
            mtime = str(file_path.stat().st_mtime)
        raw = f"{domain_name}:{mtime}"
        return hashlib.md5(raw.encode()).hexdigest()[:16]

    def get_cached(
        self, domain_name: str, file_path: Optional[Path] = None
    ) -> Optional[np.ndarray]:
        """Get cached embedding for a domain, or None if stale/missing."""
        key = self._cache_key(domain_name, file_path)
        return self._cache.get(key)

    def set_cached(
        self,
        domain_name: str,
        embedding: np.ndarray,
        file_path: Optional[Path] = None,
    ) -> None:
        """Cache an embedding for a domain."""
        key = self._cache_key(domain_name, file_path)
        self._cache[key] = embedding
        self._cache_domains[key] = domain_name

    def invalidate(self, domain_name: str) -> None:
        """Remove all cached embeddings for a domain."""
        stale = [
            key
            for key, cached_domain in self._cache_domains.items()
            if cached_domain == domain_name
        ]
        for k in stale:
            del self._cache[k]
            self._cache_domains.pop(k, None)

    # ── N-gram fallback embedding ─────────────────────────────────

    @staticmethod
    def _ngram_embed(text: str, dim: int = 256) -> np.ndarray:
        """Character n-gram hashing for zero-dependency embedding.

        Uses 2-gram, 3-gram, and 4-gram character features hashed
        into a fixed-dimension vector. Works for any language including CJK.
        """
        vec = np.zeros(dim, dtype=np.float32)

        if not text:
            return vec

        text_lower = text.lower()

        # 2-grams, 3-grams, 4-grams
        for n in (2, 3, 4):
            for i in range(len(text_lower) - n + 1):
                gram = text_lower[i : i + n]
                h = hash(gram) % dim
                vec[h] += 1.0

        # Normalize to unit length
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec /= norm

        return vec


# ── Global singleton ──────────────────────────────────────────────

_embedder: Optional[KnowledgeEmbedder] = None


def get_embedder(model_name: Optional[str] = None) -> KnowledgeEmbedder:
    """Get or create the global KnowledgeEmbedder singleton."""
    global _embedder
    if _embedder is None:
        _embedder = KnowledgeEmbedder(model_name=model_name)
    return _embedder
