import logging
import threading
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from llm_chat.memory.storage import MemoryStorage
from llm_chat.memory.extractor import MemoryExtractor

logger = logging.getLogger(__name__)


class MemoryManager:
    """记忆系统核心管理器"""
    
    def __init__(
        self,
        storage: Optional[MemoryStorage] = None,
        db_storage=None,
        llm_client=None,
        config: Optional[Dict] = None
    ):
        self.storage = storage or MemoryStorage()
        self.db_storage = db_storage
        self.extractor = MemoryExtractor(llm_client)
        self.llm_client = llm_client
        self.config = config or {}
        
        self._extraction_lock = threading.Lock()
        self._pending_extractions: List[Dict] = []
    
    def load_recent_conversations(self, days: int = 7) -> List[Dict]:
        """从SQLite读取最近的对话"""
        if not self.db_storage:
            logger.warning("数据库存储未配置，无法加载历史对话")
            return []
        
        try:
            conversations = self.db_storage.list_conversations(limit=100)
            recent_messages = []
            cutoff_date = datetime.now() - timedelta(days=days)
            
            for conv in conversations:
                updated_at = datetime.fromisoformat(conv.get("updated_at", ""))
                if updated_at >= cutoff_date:
                    messages = self.db_storage.get_messages(conv["id"])
                    recent_messages.extend(messages)
            
            logger.info(f"加载了 {len(recent_messages)} 条最近对话")
            return recent_messages
        except Exception as e:
            logger.error(f"加载历史对话失败: {e}")
            return []
    
    def extract_memories_from_messages(self, messages: List[Dict]) -> Dict:
        """从消息中提取记忆"""
        if not messages:
            return {}
        
        return self.extractor.extract(messages)
    
    def consolidate_to_short_term(self, info: Dict):
        """整合信息到短期记忆"""
        content = self.storage.load_short_term()
        
        if info.get("current_task"):
            content = self._update_section(
                content, 
                "## 当前任务",
                f"- 正在进行的工作：{info['current_task']}"
            )
        
        if info.get("pending_items"):
            pending_text = "\n".join([f"- [ ] {item}" for item in info["pending_items"]])
            content = self._update_section(content, "## 待处理事项", pending_text)
        
        self.storage.save_short_term(content)
        logger.info("更新短期记忆")
    
    def consolidate_to_mid_term(self, summary: str, date: Optional[str] = None):
        """整合摘要到中期记忆"""
        if not date:
            date = datetime.now().strftime("%Y-%m-%d")
        
        self.storage.append_summary(date, summary)
        logger.info(f"添加中期记忆摘要: {date}")
    
    def consolidate_to_long_term(self, facts: List[str], is_user_told: bool = True):
        """整合事实到长期记忆"""
        for fact in facts:
            if is_user_told:
                self.storage.add_user_fact(fact)
            else:
                self.storage.add_inferred_fact(fact)
        
        logger.info(f"添加 {len(facts)} 条长期记忆")
    
    def _update_section(self, content: str, section_header: str, new_content: str) -> str:
        """更新Markdown文件的特定章节"""
        import re
        
        pattern = rf'({re.escape(section_header)}\n)(.*?)(?=\n##|\Z)'
        match = re.search(pattern, content, re.DOTALL)
        
        if match:
            return content[:match.start(2)] + new_content + "\n" + content[match.end(2):]
        else:
            return content + f"\n\n{section_header}\n{new_content}\n"
    
    def search_memories(self, query: str) -> List[Dict]:
        """搜索记忆"""
        return self.storage.search_memories(query)
    
    def compress_mid_term(self, max_days: int = 30):
        """压缩中期记忆"""
        content = self.storage.load_mid_term()
        
        import re
        summary_section = re.search(r'## 近期摘要\n(.*?)(?=\n##|\Z)', content, re.DOTALL)
        
        if summary_section:
            summaries_text = summary_section.group(1)
            date_pattern = r'### (\d{4}-\d{2}-\d{2})'
            dates = re.findall(date_pattern, summaries_text)
            
            cutoff_date = datetime.now() - timedelta(days=max_days)
            
            for date_str in dates:
                try:
                    date = datetime.strptime(date_str, "%Y-%m-%d")
                    if date < cutoff_date:
                        old_entry_pattern = rf'\n### {date_str}\n.*?(?=\n###|\Z)'
                        content = re.sub(old_entry_pattern, '', content, flags=re.DOTALL)
                        logger.info(f"压缩旧记忆: {date_str}")
                except ValueError:
                    continue
            
            self.storage.save_mid_term(content)
    
    def evolve_understanding(self):
        """进化对用户的理解"""
        logger.info("开始记忆进化...")
        
        preferences = self.extractor.detect_user_preferences(
            self.load_recent_conversations(7)
        )
        
        if preferences.get("language"):
            self.storage.update_section("基本信息", f"- 偏好语言：{preferences['language']}")
        
        if preferences.get("style"):
            self.storage.update_section("沟通偏好", f"- 回复风格：{preferences['style']}")
        
        if preferences.get("code_style"):
            self.storage.update_section("沟通偏好", f"- 代码风格：{preferences['code_style']}")
        
        today = datetime.now().strftime("%Y-%m-%d")
        evolution_log = "- 更新了用户偏好理解\n- 优化了记忆系统"
        self.storage.add_evolution_log(today, evolution_log)
        
        self.storage.update_timestamp("long_term")
        logger.info("记忆进化完成")
    
    def build_system_prompt(self) -> str:
        """构建注入到LLM的系统提示"""
        parts = []
        
        soul = self.storage.load_soul()
        if soul and len(soul) > 50:
            parts.append("## 你的人格设定\n")
            parts.append(self._extract_soul_content(soul))
        
        long_term = self.storage.load_long_term()
        if long_term and len(long_term) > 100:
            parts.append("\n## 关于用户\n")
            parts.append(self._extract_relevant_sections(long_term))
        
        mid_term = self.storage.load_mid_term()
        if mid_term and len(mid_term) > 100:
            recent_summary = self._extract_recent_summary(mid_term)
            if recent_summary:
                parts.append("\n## 近期上下文\n")
                parts.append(recent_summary)
        
        short_term = self.storage.load_short_term()
        if short_term and len(short_term) > 100:
            current_task = self._extract_current_task(short_term)
            if current_task:
                parts.append("\n## 当前任务\n")
                parts.append(current_task)
        
        if parts:
            return "\n".join(parts)
        return ""
    
    def _extract_soul_content(self, content: str) -> str:
        """提取人格设定内容"""
        import re
        
        sections = []
        
        core_traits = re.search(r'## 核心特质\n(.*?)(?=\n##|\Z)', content, re.DOTALL)
        if core_traits:
            sections.append(core_traits.group(1).strip())
        
        behavior = re.search(r'## 行为准则\n(.*?)(?=\n##|\Z)', content, re.DOTALL)
        if behavior:
            sections.append(behavior.group(1).strip())
        
        style = re.search(r'## 沟通风格\n(.*?)(?=\n##|\Z)', content, re.DOTALL)
        if style:
            sections.append(style.group(1).strip())
        
        return "\n\n".join(sections)
    
    def get_soul(self) -> str:
        """获取人格设定"""
        return self.storage.load_soul() or ""
    
    def update_soul(self, content: str):
        """更新人格设定"""
        self.storage.save_soul(content)
        logger.info("更新人格设定")
    
    def update_soul_section(self, section: str, content: str):
        """更新人格设定的特定章节"""
        soul = self.storage.load_soul() or ""
        
        import re
        pattern = rf'(## {re.escape(section)}\n)(.*?)(?=\n##|\Z)'
        match = re.search(pattern, soul, re.DOTALL)
        
        if match:
            updated = soul[:match.start(2)] + content + "\n" + soul[match.end(2):]
            self.storage.save_soul(updated)
            logger.info(f"更新人格设定章节: {section}")
    
    def _extract_relevant_sections(self, content: str) -> str:
        """提取长期记忆中的相关章节"""
        import re
        
        sections = []
        
        user_profile = re.search(r'## 用户画像\n(.*?)(?=\n##|\Z)', content, re.DOTALL)
        if user_profile:
            sections.append(user_profile.group(1).strip())
        
        important_facts = re.search(r'## 重要事实\n(.*?)(?=\n##|\Z)', content, re.DOTALL)
        if important_facts:
            sections.append(important_facts.group(1).strip())
        
        return "\n\n".join(sections)
    
    def _extract_recent_summary(self, content: str) -> str:
        """提取最近的摘要"""
        import re
        
        today = datetime.now()
        recent_summaries = []
        
        for i in range(3):
            date = (today - timedelta(days=i)).strftime("%Y-%m-%d")
            pattern = rf'### {date}\n(.*?)(?=\n###|\n##|\Z)'
            match = re.search(pattern, content, re.DOTALL)
            if match:
                recent_summaries.append(f"**{date}**: {match.group(1).strip()}")
        
        return "\n".join(recent_summaries)
    
    def _extract_current_task(self, content: str) -> str:
        """提取当前任务"""
        import re
        
        task_match = re.search(r'## 当前任务\n(.*?)(?=\n##|\Z)', content, re.DOTALL)
        if task_match:
            return task_match.group(1).strip()
        return ""
    
    def schedule_extraction(self, messages: List[Dict]):
        """调度异步记忆提取"""
        with self._extraction_lock:
            self._pending_extractions.extend(messages)
    
    def process_pending_extractions(self):
        """处理待提取的记忆"""
        with self._extraction_lock:
            if not self._pending_extractions:
                return
            
            messages = self._pending_extractions.copy()
            self._pending_extractions.clear()
        
        try:
            info = self.extract_memories_from_messages(messages)
            
            if self.extractor.should_remember(info):
                self.consolidate_to_short_term(info)
                
                if info.get("important_facts"):
                    self.consolidate_to_long_term(info["important_facts"], is_user_told=True)
                
                if info.get("user_preferences"):
                    self.consolidate_to_long_term(info["user_preferences"], is_user_told=False)
            
            logger.info("完成记忆提取处理")
        except Exception as e:
            logger.error(f"记忆提取处理失败: {e}")
    
    def archive_session(self, session_id: str):
        """归档会话到中期记忆"""
        if not self.db_storage:
            return
        
        try:
            messages = self.db_storage.get_messages(session_id)
            if messages:
                summary = self.extractor.summarize_day(messages)
                if summary:
                    date = datetime.now().strftime("%Y-%m-%d")
                    self.consolidate_to_mid_term(summary, date)
            
            self.storage.clear_short_term()
            logger.info(f"归档会话: {session_id}")
        except Exception as e:
            logger.error(f"归档会话失败: {e}")
    
    def get_memory_stats(self) -> Dict[str, Any]:
        """获取记忆统计信息"""
        stats = self.storage.get_memory_stats()
        stats["pending_extractions"] = len(self._pending_extractions)
        return stats
    
    def clear_all_memories(self):
        """清空所有记忆"""
        self.storage.clear_short_term()
        self.storage.save_mid_term("")
        self.storage.save_long_term("")
        logger.warning("已清空所有记忆")
    
    def export_memories(self) -> Dict[str, str]:
        """导出所有记忆"""
        return {
            "short_term": self.storage.load_short_term(),
            "mid_term": self.storage.load_mid_term(),
            "long_term": self.storage.load_long_term(),
            "exported_at": datetime.now().isoformat()
        }
    
    def import_memories(self, memories: Dict[str, str]):
        """导入记忆"""
        if memories.get("short_term"):
            self.storage.save_short_term(memories["short_term"])
        if memories.get("mid_term"):
            self.storage.save_mid_term(memories["mid_term"])
        if memories.get("long_term"):
            self.storage.save_long_term(memories["long_term"])
        logger.info("导入记忆完成")
