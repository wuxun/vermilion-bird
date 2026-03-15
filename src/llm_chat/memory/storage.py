import re
import shutil
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

from llm_chat.memory.templates import (
    get_short_term_template,
    get_mid_term_template,
    get_long_term_template,
    get_soul_template
)

logger = logging.getLogger(__name__)


class MemoryStorage:
    """Markdown格式记忆存储管理器"""
    
    def __init__(self, memory_dir: str = "~/.vermilion-bird/memory"):
        self.memory_dir = Path(memory_dir).expanduser()
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        
        self.short_term_path = self.memory_dir / "short_term.md"
        self.mid_term_path = self.memory_dir / "mid_term.md"
        self.long_term_path = self.memory_dir / "long_term.md"
        self.soul_path = self.memory_dir / "soul.md"
        
        self._init_memory_files()
    
    def _init_memory_files(self):
        """初始化记忆文件"""
        if not self.short_term_path.exists():
            self.save_short_term(get_short_term_template())
            logger.info("初始化短期记忆文件")
        
        if not self.mid_term_path.exists():
            self.save_mid_term(get_mid_term_template())
            logger.info("初始化中期记忆文件")
        
        if not self.long_term_path.exists():
            self.save_long_term(get_long_term_template())
            logger.info("初始化长期记忆文件")
        
        if not self.soul_path.exists():
            self.save_soul(get_soul_template())
            logger.info("初始化人格设定文件")
    
    def load_short_term(self) -> str:
        """加载短期记忆"""
        try:
            return self.short_term_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return get_short_term_template()
    
    def save_short_term(self, content: str):
        """保存短期记忆"""
        self.short_term_path.write_text(content, encoding="utf-8")
        logger.info("保存短期记忆")
    
    def clear_short_term(self):
        """清空短期记忆"""
        self.save_short_term(get_short_term_template())
        logger.info("清空短期记忆")
    
    def load_mid_term(self) -> str:
        """加载中期记忆"""
        try:
            return self.mid_term_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return get_mid_term_template()
    
    def save_mid_term(self, content: str):
        """保存中期记忆"""
        self.mid_term_path.write_text(content, encoding="utf-8")
        logger.info("保存中期记忆")
    
    def append_summary(self, date: str, summary: str):
        """追加每日摘要到中期记忆"""
        content = self.load_mid_term()
        
        summary_section_match = re.search(r'## 近期摘要\n', content)
        if summary_section_match:
            insert_pos = summary_section_match.end()
            new_entry = f"\n### {date}\n{summary}\n"
            content = content[:insert_pos] + new_entry + content[insert_pos:]
            self.save_mid_term(content)
            logger.info(f"追加摘要: {date}")
    
    def append_timeline_event(self, date: str, event: str):
        """追加事件到时间线"""
        content = self.load_mid_term()
        
        timeline_match = re.search(r'## 重要事件时间线\n', content)
        if timeline_match:
            insert_pos = timeline_match.end()
            new_entry = f"\n- {date}: {event}\n"
            content = content[:insert_pos] + new_entry + content[insert_pos:]
            self.save_mid_term(content)
            logger.info(f"追加时间线事件: {date}")
    
    def load_long_term(self) -> str:
        """加载长期记忆"""
        try:
            return self.long_term_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return get_long_term_template()
    
    def save_long_term(self, content: str):
        """保存长期记忆"""
        self.long_term_path.write_text(content, encoding="utf-8")
        logger.info("保存长期记忆")
    
    def update_section(self, section: str, content: str) -> bool:
        """更新长期记忆的指定章节"""
        long_term = self.load_long_term()
        
        pattern = rf'(### {re.escape(section)}\n)(.*?)(?=\n###|\n##|\Z)'
        match = re.search(pattern, long_term, re.DOTALL)
        
        if match:
            updated = long_term[:match.start(2)] + content + long_term[match.end(2):]
            self.save_long_term(updated)
            logger.info(f"更新章节: {section}")
            return True
        return False
    
    def add_user_fact(self, fact: str):
        """添加用户主动告知的事实"""
        content = self.load_long_term()
        
        user_facts_match = re.search(r'### 用户主动告知\n', content)
        if user_facts_match:
            insert_pos = user_facts_match.end()
            new_entry = f"\n- {fact}\n"
            content = content[:insert_pos] + new_entry + content[insert_pos:]
            self.save_long_term(content)
            logger.info(f"添加用户事实: {fact[:50]}...")
    
    def add_inferred_fact(self, fact: str):
        """添加系统推断的事实"""
        content = self.load_long_term()
        
        inferred_match = re.search(r'### 系统推断\n', content)
        if inferred_match:
            insert_pos = inferred_match.end()
            new_entry = f"\n- {fact}\n"
            content = content[:insert_pos] + new_entry + content[insert_pos:]
            self.save_long_term(content)
            logger.info(f"添加推断事实: {fact[:50]}...")
    
    def add_evolution_log(self, date: str, log: str):
        """添加进化日志"""
        content = self.load_long_term()
        
        evolution_match = re.search(r'## 进化日志\n', content)
        if evolution_match:
            insert_pos = evolution_match.end()
            new_entry = f"\n### {date}\n{log}\n"
            content = content[:insert_pos] + new_entry + content[insert_pos:]
            self.save_long_term(content)
            logger.info(f"添加进化日志: {date}")
    
    def update_timestamp(self, memory_type: str = "all"):
        """更新记忆文件的时间戳"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        if memory_type in ("short_term", "all"):
            content = self.load_short_term()
            content = re.sub(
                r'更新时间：.*',
                f'更新时间：{now}',
                content
            )
            self.save_short_term(content)
        
        if memory_type in ("mid_term", "all"):
            content = self.load_mid_term()
            content = re.sub(
                r'更新时间：.*',
                f'更新时间：{now}',
                content
            )
            self.save_mid_term(content)
        
        if memory_type in ("long_term", "all"):
            content = self.load_long_term()
            content = re.sub(
                r'更新时间：.*',
                f'更新时间：{now}',
                content
            )
            self.save_long_term(content)
    
    def load_soul(self) -> Optional[str]:
        """加载人格设定"""
        try:
            return self.soul_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
    
    def save_soul(self, content: str):
        """保存人格设定"""
        self.soul_path.write_text(content, encoding="utf-8")
        logger.info("保存人格设定")
    
    def backup_memory(self, backup_dir: Optional[str] = None) -> str:
        """备份记忆文件"""
        if backup_dir:
            backup_path = Path(backup_dir)
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = self.memory_dir / "backups" / timestamp
        
        backup_path.mkdir(parents=True, exist_ok=True)
        
        for file_path in [self.short_term_path, self.mid_term_path, self.long_term_path]:
            if file_path.exists():
                shutil.copy2(file_path, backup_path / file_path.name)
        
        if self.soul_path.exists():
            shutil.copy2(self.soul_path, backup_path / self.soul_path.name)
        
        logger.info(f"备份记忆到: {backup_path}")
        return str(backup_path)
    
    def restore_memory(self, backup_path: str):
        """从备份恢复记忆"""
        backup_dir = Path(backup_path)
        
        for file_name in ["short_term.md", "mid_term.md", "long_term.md", "soul.md"]:
            src = backup_dir / file_name
            if src.exists():
                shutil.copy2(src, self.memory_dir / file_name)
        
        logger.info(f"从备份恢复记忆: {backup_path}")
    
    def search_memories(self, query: str) -> List[Dict[str, Any]]:
        """搜索记忆内容"""
        results = []
        query_lower = query.lower()
        
        for memory_type, path in [
            ("short_term", self.short_term_path),
            ("mid_term", self.mid_term_path),
            ("long_term", self.long_term_path)
        ]:
            if path.exists():
                content = path.read_text(encoding="utf-8")
                if query_lower in content.lower():
                    results.append({
                        "type": memory_type,
                        "path": str(path),
                        "matches": self._extract_matches(content, query)
                    })
        
        return results
    
    def _extract_matches(self, content: str, query: str, context_lines: int = 2) -> List[str]:
        """提取匹配内容及其上下文"""
        lines = content.split('\n')
        matches = []
        query_lower = query.lower()
        
        for i, line in enumerate(lines):
            if query_lower in line.lower():
                start = max(0, i - context_lines)
                end = min(len(lines), i + context_lines + 1)
                context = '\n'.join(lines[start:end])
                matches.append(context)
        
        return matches
    
    def get_memory_stats(self) -> Dict[str, Any]:
        """获取记忆统计信息"""
        stats = {
            "memory_dir": str(self.memory_dir),
            "files": {}
        }
        
        for name, path in [
            ("short_term", self.short_term_path),
            ("mid_term", self.mid_term_path),
            ("long_term", self.long_term_path),
            ("soul", self.soul_path)
        ]:
            if path.exists():
                stat = path.stat()
                content = path.read_text(encoding="utf-8")
                stats["files"][name] = {
                    "exists": True,
                    "size_bytes": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "line_count": len(content.split('\n')),
                    "char_count": len(content)
                }
            else:
                stats["files"][name] = {"exists": False}
        
        return stats
