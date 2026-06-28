"""
Vermilion Bird MemoryStorage — extends ember-core with domain-specific layers.

Provides short_term, mid_term, long_term, and soul memory files
with markdown-specific editorial methods (append_summary, add_user_fact, etc.).
"""

import re
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

from ember_core.memory.storage import MemoryStorage as _BaseMemoryStorage

logger = logging.getLogger(__name__)


class MemoryStorage(_BaseMemoryStorage):
    """Vermilion Bird memory storage with four-tier memory layers."""

    def __init__(self, memory_dir: str = "~/.vermilion-bird/memory"):
        super().__init__(memory_dir)
        # Paths kept for backward compat with existing code
        self.memory_dir = self._dir
        self.short_term_path = self._dir / "short_term.md"
        self.mid_term_path = self._dir / "mid_term.md"
        self.long_term_path = self._dir / "long_term.md"
        self.soul_path = self._dir / "soul.md"

    # ── Short-term ──────────────────────────────────────────────

    def load_short_term(self) -> str:
        return self.load("short_term")

    def save_short_term(self, content: str) -> None:
        self.save("short_term", content)
        logger.info("保存短期记忆")

    def clear_short_term(self) -> None:
        self.save("short_term", "")

    # ── Mid-term ────────────────────────────────────────────────

    def load_mid_term(self) -> str:
        return self.load("mid_term")

    def save_mid_term(self, content: str) -> None:
        self.save("mid_term", content)
        logger.info("保存中期记忆")

    def append_summary(self, date: str, summary: str) -> None:
        content = self.load_mid_term()
        match = re.search(r'## 近期摘要\n', content)
        if match:
            insert_pos = match.end()
            new_entry = f"\n### {date}\n{summary}\n"
            content = content[:insert_pos] + new_entry + content[insert_pos:]
            self.save("mid_term", content)
            logger.info(f"追加摘要: {date}")

    def append_timeline_event(self, date: str, event: str) -> None:
        content = self.load_mid_term()
        match = re.search(r'## 重要事件时间线\n', content)
        if match:
            insert_pos = match.end()
            content = content[:insert_pos] + f"\n- {date}: {event}\n" + content[insert_pos:]
            self.save("mid_term", content)
            logger.info(f"追加时间线事件: {date}")

    # ── Long-term ───────────────────────────────────────────────

    def load_long_term(self) -> str:
        return self.load("long_term")

    def save_long_term(self, content: str) -> None:
        self.save("long_term", content)
        logger.info("保存长期记忆")

    def update_section(self, section: str, content: str) -> bool:
        long_term = self.load_long_term()
        pattern = rf'(### {re.escape(section)}\n)(.*?)(?=\n###|\n##|\Z)'
        match = re.search(pattern, long_term, re.DOTALL)
        if match:
            updated = long_term[:match.start(2)] + content + long_term[match.end(2):]
            self.save("long_term", updated)
            return True
        return False

    def add_user_fact(self, fact: str) -> None:
        with self._lock:
            content = self.load_long_term()
            match = re.search(r'### 用户主动告知\n', content)
            if match:
                insert_pos = match.end()
                content = content[:insert_pos] + f"\n- {fact}\n" + content[insert_pos:]
                self.save("long_term", content)

    def add_inferred_fact(self, fact: str) -> None:
        with self._lock:
            content = self.load_long_term()
            match = re.search(r'### 系统推断\n', content)
            if match:
                insert_pos = match.end()
                content = content[:insert_pos] + f"\n- {fact}\n" + content[insert_pos:]
                self.save("long_term", content)

    def add_evolution_log(self, date: str, log: str) -> None:
        with self._lock:
            content = self.load_long_term()
            match = re.search(r'## 进化日志\n', content)
            if match:
                insert_pos = match.end()
                content = content[:insert_pos] + f"\n### {date}\n{log}\n" + content[insert_pos:]
                content = self._trim_evolution_log(content)
                self.save("long_term", content)

    def _trim_evolution_log(self, content: str, max_entries: int = 10) -> str:
        match = re.search(r'(## 进化日志\n)(.*?)(?=\n##[^#]|\Z)', content, re.DOTALL)
        if not match:
            return content
        header = match.group(1)
        body = match.group(2)
        entries = re.split(r'(?=\n### )', body.strip())
        entries = [e.strip() for e in entries if e.strip()]
        if len(entries) <= max_entries:
            return content
        trimmed_body = "\n".join(entries[-max_entries:])
        return content[:match.start()] + header + trimmed_body + "\n" + content[match.end():]

    def update_timestamp(self, memory_type: str = "all") -> None:
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        for name in ["short_term", "mid_term", "long_term"]:
            if memory_type in (name, "all"):
                content = self.load(name)
                content = re.sub(r'更新时间：.*', f'更新时间：{now}', content)
                self.save(name, content)

    # ── Soul ────────────────────────────────────────────────────

    def load_soul(self) -> Optional[str]:
        content = self.load("soul")
        return content if content else None

    def save_soul(self, content: str) -> None:
        self.save("soul", content)
        logger.info("保存人格设定")

    # ── Backward compat aliases ─────────────────────────────────

    def backup_memory(self, backup_dir: Optional[str] = None) -> str:
        return self.backup(backup_dir)

    def restore_memory(self, backup_path: str) -> None:
        self.restore(backup_path)

    def search_memories(self, query: str) -> List[Dict]:
        return self.search(query)

    def get_memory_stats(self) -> Dict:
        return self.get_stats()
