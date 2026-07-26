"""GhostStore — YAML file-based persistence for Ghost profiles.

Ghosts are stored as individual YAML files in the ghosts directory
(default: ~/.vermilion-bird/ghosts/). Each file name (without .yaml)
becomes the ghost's reference key.

Example directory:
    ~/.vermilion-bird/ghosts/
    ├── researcher.yaml
    ├── code-reviewer.yaml
    └── summarizer.yaml

Usage:
    store = get_ghost_store()
    store.save("researcher", ghost_config)
    ghost = store.load("researcher")
    store.list_all()  # -> ["researcher", "code-reviewer", "summarizer"]
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from llm_chat.ghost.schema import GhostConfig

logger = logging.getLogger(__name__)

# Default ghost storage directory
DEFAULT_GHOST_DIR = Path.home() / ".vermilion-bird" / "ghosts"
GHOST_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


class GhostStore:
    """File-based storage for Ghost YAML profiles.

    Reads and writes are serialized so cache state and atomic file updates remain
    consistent under concurrent sub-agent requests.
    """

    def __init__(self, ghost_dir: Optional[Path] = None):
        self._dir = Path(ghost_dir) if ghost_dir else DEFAULT_GHOST_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        self._cache: Dict[str, GhostConfig] = {}
        self._cache_mtimes: Dict[str, int] = {}
        self._lock = threading.RLock()

    @property
    def directory(self) -> Path:
        return self._dir

    # ── CRUD ──────────────────────────────────────────────────────

    @staticmethod
    def _validate_key(key: str) -> None:
        """Reject path traversal and ambiguous profile names."""
        if not GHOST_KEY_PATTERN.fullmatch(key):
            raise ValueError(f"Invalid ghost key: {key!r}")

    def save(self, key: str, ghost: GhostConfig) -> Path:
        """Save a GhostConfig to a YAML file. Overwrites if exists.

        Args:
            key: File name without extension (e.g. "researcher")
            ghost: GhostConfig to save

        Returns:
            Path to the saved file

        Raises:
            ValueError: if key is empty or contains path separators
        """
        self._validate_key(key)

        filepath = self._dir / f"{key}.yaml"
        data = ghost.to_yaml_dict()

        # Ensure name field is present
        data.setdefault("name", key)

        # Write atomically with a unique temporary file. A shared `<key>.tmp`
        # races when two callers update the same profile.
        with self._lock:
            tmp_path = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    dir=self._dir,
                    prefix=f".{key}.",
                    suffix=".tmp",
                    delete=False,
                ) as handle:
                    tmp_path = Path(handle.name)
                    yaml.dump(
                        data,
                        handle,
                        default_flow_style=False,
                        allow_unicode=True,
                        sort_keys=False,
                        width=120,
                    )
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp_path, filepath)
            finally:
                if tmp_path and tmp_path.exists():
                    tmp_path.unlink()

            self._cache[key] = ghost
            self._cache_mtimes[key] = filepath.stat().st_mtime_ns
        logger.info(f"Saved ghost '{key}' to {filepath}")
        return filepath

    def load(self, key: str) -> Optional[GhostConfig]:
        """Load a ghost by key (filename without .yaml).

        Returns None if not found or parse error.
        """
        self._validate_key(key)
        filepath = self._dir / f"{key}.yaml"
        if not filepath.exists():
            return None

        with self._lock:
            mtime = filepath.stat().st_mtime_ns
            if key in self._cache and self._cache_mtimes.get(key) == mtime:
                return self._cache[key]

            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                ghost = GhostConfig.from_yaml_dict(data)
                self._cache[key] = ghost
                self._cache_mtimes[key] = mtime
                return ghost
            except Exception as e:
                logger.warning(f"Failed to load ghost '{key}': {e}")
                return None

    def delete(self, key: str) -> bool:
        """Delete a ghost YAML file. Returns True if deleted, False if not found."""
        self._validate_key(key)
        filepath = self._dir / f"{key}.yaml"
        with self._lock:
            self._cache.pop(key, None)
            self._cache_mtimes.pop(key, None)
            if filepath.exists():
                filepath.unlink()
                logger.info(f"Deleted ghost '{key}'")
                return True
            return False

    def list_all(self) -> List[str]:
        """List all available ghost keys (sorted alphabetically)."""
        keys = []
        for f in sorted(self._dir.glob("*.yaml")):
            keys.append(f.stem)
        return keys

    def load_all(self) -> Dict[str, GhostConfig]:
        """Load all ghosts from disk into cache. Returns dict of key → GhostConfig."""
        with self._lock:
            self._cache.clear()
            self._cache_mtimes.clear()
            loaded = 0
            for key in self.list_all():
                ghost = self.load(key)
                if ghost:
                    loaded += 1
        logger.info(f"Loaded {loaded} ghosts from {self._dir}")
        return dict(self._cache)

    def get_cached(self, key: str) -> Optional[GhostConfig]:
        """Get ghost from in-memory cache without disk read."""
        with self._lock:
            return self._cache.get(key)

    def all_cached(self) -> Dict[str, GhostConfig]:
        """Get all cached ghosts."""
        with self._lock:
            return dict(self._cache)


# ── Global singleton ──────────────────────────────────────────────

_store: Optional[GhostStore] = None


def get_ghost_store(ghost_dir: Optional[Path] = None) -> GhostStore:
    """Get or create the global GhostStore singleton.

    Args:
        ghost_dir: Optional custom directory. Only used on first call.
    """
    global _store
    if _store is None:
        _store = GhostStore(ghost_dir=ghost_dir)
        _store.load_all()
    return _store
