"""MemoryStorage — atomic file-based named text storage.

Generic: stores named text files with atomic writes (tempfile + rename).
No knowledge of "short_term", "mid_term", or vermilion-bird concepts.

Usage:
    store = MemoryStorage("~/.myapp/memory")
    store.save("notes", "Important information...")
    content = store.load("notes")
    results = store.search("Important")
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class MemoryStorage:
    """Generic atomic-write file store for named text content.

    Thread-safe writes via threading.Lock + tempfile + os.replace().
    Supports save/load/search/backup/restore for arbitrary named files.
    """

    _lock = threading.Lock()

    def __init__(self, base_dir: str = "~/.ember/memory"):
        self._dir = Path(base_dir).expanduser()
        self._dir.mkdir(parents=True, exist_ok=True)

    # ── Path helpers ──────────────────────────────────────────

    def _path(self, name: str) -> Path:
        """Get the file path for a named memory, ensuring .md extension."""
        if not name.endswith(".md"):
            name = f"{name}.md"
        return self._dir / name

    # ── Atomic I/O ────────────────────────────────────────────

    def _atomic_write(self, filepath: Path, content: str) -> None:
        """Write content atomically: write to temp file, then rename over target."""
        tmp_fd, tmp_path = tempfile.mkstemp(
            suffix=".tmp",
            prefix=filepath.name + ".",
            dir=filepath.parent,
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(tmp_path, filepath)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    # ── CRUD ──────────────────────────────────────────────────

    def save(self, name: str, content: str) -> None:
        """Atomically write a named memory file."""
        self._atomic_write(self._path(name), content)
        logger.debug(f"Saved memory '{name}' ({len(content)} chars)")

    def load(self, name: str) -> str:
        """Load a named memory file. Returns empty string if not found."""
        try:
            return self._path(name).read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""

    def exists(self, name: str) -> bool:
        """Check if a named memory file exists."""
        return self._path(name).exists()

    def delete(self, name: str) -> bool:
        """Delete a named memory file. Returns True if it existed."""
        path = self._path(name)
        if path.exists():
            path.unlink()
            return True
        return False

    # ── Search ────────────────────────────────────────────────

    def search(
        self, query: str, names: Optional[List[str]] = None
    ) -> List[Dict]:
        """Search all (or specified) memory files for query string.

        Returns list of {name, path, matches: [context strings]}.
        """
        results = []
        query_lower = query.lower()

        targets = names if names else self._list_names()
        for name in targets:
            path = self._path(name)
            if not path.exists():
                continue
            content = path.read_text(encoding="utf-8")
            if query_lower in content.lower():
                results.append({
                    "name": name,
                    "path": str(path),
                    "matches": self._extract_matches(content, query),
                })
        return results

    def _extract_matches(
        self, content: str, query: str, context_lines: int = 2
    ) -> List[str]:
        """Extract matching lines with surrounding context."""
        lines = content.split("\n")
        matches = []
        query_lower = query.lower()
        for i, line in enumerate(lines):
            if query_lower in line.lower():
                start = max(0, i - context_lines)
                end = min(len(lines), i + context_lines + 1)
                matches.append("\n".join(lines[start:end]))
        return matches

    # ── Backup / Restore ──────────────────────────────────────

    def backup(self, backup_dir: Optional[str] = None) -> str:
        """Copy all memory files to a backup directory. Returns backup path."""
        if backup_dir:
            backup_path = Path(backup_dir)
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = self._dir / "backups" / timestamp

        backup_path.mkdir(parents=True, exist_ok=True)

        for md_file in self._dir.glob("*.md"):
            shutil.copy2(md_file, backup_path / md_file.name)

        logger.info(f"Backed up memory to: {backup_path}")
        return str(backup_path)

    def restore(self, backup_path: str) -> None:
        """Restore memory files from a backup directory."""
        backup_dir = Path(backup_path)
        for md_file in backup_dir.glob("*.md"):
            shutil.copy2(md_file, self._dir / md_file.name)
        logger.info(f"Restored memory from: {backup_path}")

    # ── Stats ─────────────────────────────────────────────────

    def get_stats(self) -> Dict:
        """Get statistics for all memory files."""
        stats = {"base_dir": str(self._dir), "files": {}}
        for name in self._list_names():
            path = self._path(name)
            if path.exists():
                st = path.stat()
                content = path.read_text(encoding="utf-8")
                stats["files"][name] = {
                    "size_bytes": st.st_size,
                    "modified": datetime.fromtimestamp(st.st_mtime).isoformat(),
                    "line_count": len(content.split("\n")),
                    "char_count": len(content),
                }
        return stats

    # ── Internal ──────────────────────────────────────────────

    def _list_names(self) -> List[str]:
        """List all stored memory names (without .md extension)."""
        return sorted(
            p.stem for p in self._dir.glob("*.md")
            if p.name not in (".gitkeep",)
        )

    @property
    def base_dir(self) -> Path:
        return self._dir
