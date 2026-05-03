import logging
import threading
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, TYPE_CHECKING

from llm_chat.memory.storage import MemoryStorage
from llm_chat.memory.extractor import MemoryExtractor

if TYPE_CHECKING:
    from llm_chat.memory.summarizer import Summarizer

logger = logging.getLogger(__name__)


class MemoryManager:
    """记忆系统核心管理器"""
    
    def __init__(
        self,
        storage: Optional[MemoryStorage] = None,
        db_storage=None,
        llm_client=None,
        summarizer: Optional["Summarizer"] = None,
        config: Optional[Dict] = None
    ):
        self.storage = storage or MemoryStorage()
        self.db_storage = db_storage
        self.llm_client = llm_client  # 向后兼容，已弃用
        self._summarizer = summarizer
        self.config = config or {}
        
        # 延迟创建 Extractor，确保 summarizer/llm_client 参数可用
        self.extractor = MemoryExtractor(
            llm_client=llm_client,
            summarizer=summarizer,
        )
        self._extraction_lock = threading.Lock()
        self._pending_extractions: List[Dict] = []
        
        self._conversation_count = 0
        self._last_extraction_time = datetime.now()
        self._last_compress_time = datetime.now()
        self._last_evolve_time = datetime.now()
        self._extraction_interval = self.config.get("extraction_interval", 10)
        self._extraction_time_interval = self.config.get("extraction_time_interval", 3600)
        self._short_term_max_entries = self.config.get("short_term_max_entries", 50)
        # 中期压缩 & 长期进化配置
        mid_cfg = self.config.get("mid_term", {})
        self._mid_term_max_days = mid_cfg.get("max_days", 30)
        self._mid_term_compress_days = mid_cfg.get("compress_after_days", 7)
        long_cfg = self.config.get("long_term", {})
        self._long_term_auto_evolve = long_cfg.get("auto_evolve", True)
        self._long_term_evolve_interval_days = long_cfg.get("evolve_interval_days", 7)
        # Token 预算
        self._max_memory_tokens = self.config.get("max_memory_tokens", 2000)
    
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
        """压缩中期记忆：删除过期条目 + 合并相似摘要。"""
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

        # 去重：合并相似摘要
        self._dedup_mid_term()

    def _dedup_mid_term(self, min_entries: int = 7) -> int:
        """合并中期记忆中语意相似的每日摘要。

        使用 LLM 对近期摘要进行主题聚类，将相似主题合并为一条精炼条目。
        仅在摘要条目 ≥ min_entries 时触发，避免频繁调用 LLM。

        Returns:
            合并的条目数
        """
        if not self._summarizer:
            return 0

        content = self.storage.load_mid_term()

        import re
        # 提取所有每日摘要
        summary_section = re.search(
            r'## 近期摘要\n(.*?)(?=\n##|\Z)', content, re.DOTALL
        )
        if not summary_section:
            return 0

        summaries_text = summary_section.group(1)
        entries = re.findall(
            r'### (\d{4}-\d{2}-\d{2})\n(.*?)(?=\n###|\Z)',
            summaries_text,
            re.DOTALL,
        )

        if len(entries) < min_entries:
            logger.debug(
                f"中期记忆去重跳过: {len(entries)} < {min_entries} 条目"
            )
            return 0

        # 构建 LLM 提示
        summaries_list = "\n".join(
            f"[{date}] {text.strip()[:200]}"
            for date, text in entries
        )

        prompt = f"""你是一个记忆整理助手。以下是最近 {len(entries)} 天的每日摘要：

{summaries_list}

请分析这些摘要，找出语意相似的条目（如讨论同一主题、同一项目、同一任务的连续多天记录），将它们合并为一条精炼的摘要。

要求：
1. 合并后保留最早日期作为新日期
2. 去重重复信息，保留关键内容
3. 每条合并摘要不超过 200 字
4. 不要改变任何事实

输出格式 (JSON array):
[
  {{"date": "合并后日期", "merged_dates": ["原始日期1", "原始日期2"], "summary": "合并后的摘要"}},
  ...
]

只返回 JSON，不要其他内容。"""

        try:
            response = self._summarizer.generate(prompt, max_tokens=2000)
            if not response:
                return 0

            import json
            # 提取 JSON (LLM 可能包裹在 markdown code block 中)
            json_match = re.search(r'```(?:json)?\s*(\[.*?\])\s*```', response, re.DOTALL)
            if json_match:
                clusters = json.loads(json_match.group(1))
            else:
                # 尝试直接解析
                clusters = json.loads(response.strip())

            if not isinstance(clusters, list):
                return 0

            # 构建合并后的摘要块
            merged = {}
            all_merged_dates = set()
            for cluster in clusters:
                date = cluster.get("date", "")
                merged_dates = cluster.get("merged_dates", [])
                summary = cluster.get("summary", "")
                if date and summary:
                    merged[date] = summary
                    all_merged_dates.update(merged_dates)

            if not merged:
                return 0

            # 重建近期摘要块：保留未合并的 + 添加合并后的
            kept_entries = []
            for date, text in entries:
                if date not in all_merged_dates:
                    kept_entries.append(f"### {date}\n{text.strip()}")

            for date, summary in merged.items():
                kept_entries.append(f"### {date}\n{summary.strip()}")

            # 按日期排序
            kept_entries.sort()
            new_section = "## 近期摘要\n" + "\n".join(kept_entries) + "\n"

            # 替换原摘要段
            content = (
                content[:summary_section.start()]
                + new_section
                + content[summary_section.end():]
            )
            self.storage.save_mid_term(content)

            merged_count = len(all_merged_dates) - len(merged)
            logger.info(
                f"中期记忆去重完成: {len(entries)} → {len(kept_entries)} 条目 "
                f"(合并 {merged_count} 条)"
            )
            return merged_count

        except Exception as e:
            logger.warning(f"中期记忆去重失败: {e}")
            return 0
    
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
    
    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """粗略估算文本 token 数（中文约 1 字 = 1 token，英文约 4 字符 = 1 token）"""
        if not text:
            return 0
        import re
        # 中文字符、日韩字符
        cjk_chars = len(re.findall(r'[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af]', text))
        # 其余字符按 4 字符 ≈ 1 token 估算
        other_chars = len(text) - cjk_chars
        return cjk_chars + (other_chars // 4)

    def build_system_prompt(self) -> str:
        """构建注入到LLM的系统提示，按 soul > long_term > mid_term > short_term 优先级控制在 token 预算内"""
        budget = self._max_memory_tokens
        if budget <= 0:
            return ""

        sections = []  # List of (priority, header, content)
        budget_remaining = budget

        # 优先级 0: 人格设定（最高，不可截断）
        soul = self.storage.load_soul()
        if soul:
            soul_content = self._extract_soul_content(soul)
            soul_tokens = self._estimate_tokens(soul_content)
            if soul_tokens > 0 and soul_tokens <= budget_remaining:
                sections.append("## 你的人格设定\n" + soul_content)
                budget_remaining -= soul_tokens

        # 优先级 1: 长期记忆（用户画像 + 重要事实）
        long_term = self.storage.load_long_term()
        if long_term and budget_remaining > 0:
            lt_content = self._extract_relevant_sections(long_term)
            lt_tokens = self._estimate_tokens(lt_content)
            if lt_tokens > 0:
                if lt_tokens <= budget_remaining:
                    sections.append("## 关于用户\n" + lt_content)
                    budget_remaining -= lt_tokens
                else:
                    # 截断到剩余预算
                    truncated = self._truncate_by_tokens(lt_content, budget_remaining)
                    if truncated:
                        sections.append("## 关于用户\n" + truncated)
                        budget_remaining = 0

        # 优先级 2: 中期记忆（近期上下文摘要）
        mid_term = self.storage.load_mid_term()
        if mid_term and budget_remaining > 0:
            recent_summary = self._extract_recent_summary(mid_term)
            if recent_summary:
                ms_tokens = self._estimate_tokens(recent_summary)
                if ms_tokens <= budget_remaining:
                    sections.append("## 近期上下文\n" + recent_summary)
                    budget_remaining -= ms_tokens
                else:
                    truncated = self._truncate_by_tokens(recent_summary, budget_remaining)
                    if truncated:
                        sections.append("## 近期上下文\n" + truncated)
                        budget_remaining = 0

        # 优先级 3: 短期记忆（当前任务）
        short_term = self.storage.load_short_term()
        if short_term and budget_remaining > 0:
            current_task = self._extract_current_task(short_term)
            if current_task:
                ct_tokens = self._estimate_tokens(current_task)
                if ct_tokens <= budget_remaining:
                    sections.append("## 当前任务\n" + current_task)
                    budget_remaining -= ct_tokens
                else:
                    truncated = self._truncate_by_tokens(current_task, budget_remaining)
                    if truncated:
                        sections.append("## 当前任务\n" + truncated)

        if sections:
            result = "\n\n".join(sections)
            logger.debug(f"构建系统提示: {self._estimate_tokens(result)} tokens (预算 {budget})")
            return result
        return ""

    @staticmethod
    def _truncate_by_tokens(text: str, max_tokens: int) -> str:
        """按 token 预算截断文本，保留完整行"""
        if not text or max_tokens <= 0:
            return ""

        lines = text.split('\n')
        result_lines = []
        current_tokens = 0

        for line in lines:
            line_tokens = MemoryManager._estimate_tokens(line)
            if current_tokens + line_tokens > max_tokens:
                break
            result_lines.append(line)
            current_tokens += line_tokens

        return '\n'.join(result_lines) if result_lines else ""
    
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
        """处理待提取的记忆 - 短期记忆直接写入 + 周期性维护"""
        with self._extraction_lock:
            if not self._pending_extractions:
                return

            messages = self._pending_extractions.copy()
            self._pending_extractions.clear()

        self._write_short_term_directly(messages)
        self._increment_conversation_count()

        mid_term_extracted = False
        if self._should_extract_mid_term():
            self._extract_to_mid_term()
            mid_term_extracted = True

        # 周期性维护：压缩过期中期记忆
        self._maybe_compress_mid_term()

        # 周期性维护：进化长期记忆（中期记忆有更新时更频繁检查）
        self._maybe_evolve_understanding(mid_term_extracted)

    def _maybe_compress_mid_term(self):
        """按周期压缩过期中期记忆"""
        elapsed = (datetime.now() - self._last_compress_time).total_seconds()
        compress_seconds = self._mid_term_compress_days * 86400

        if elapsed >= compress_seconds:
            try:
                self.compress_mid_term(max_days=self._mid_term_max_days)
                self._last_compress_time = datetime.now()
                logger.info(f"中期记忆压缩完成 (保留 {self._mid_term_max_days} 天)")
            except Exception as e:
                logger.error(f"中期记忆压缩失败: {e}")

    def _maybe_evolve_understanding(self, force: bool = False):
        """按周期进化长期记忆"""
        if not self._long_term_auto_evolve:
            return

        elapsed = (datetime.now() - self._last_evolve_time).total_seconds()
        evolve_seconds = self._long_term_evolve_interval_days * 86400

        if force or elapsed >= evolve_seconds:
            try:
                self.evolve_understanding()
                self._last_evolve_time = datetime.now()
                logger.info(f"长期记忆进化完成")
            except Exception as e:
                logger.error(f"长期记忆进化失败: {e}")
    
    def _increment_conversation_count(self):
        """增加对话计数"""
        self._conversation_count += 1
        logger.debug(f"对话计数: {self._conversation_count}/{self._extraction_interval}")
    
    def _should_extract_mid_term(self) -> bool:
        """判断是否需要提取中期记忆"""
        if self._conversation_count >= self._extraction_interval:
            logger.info(f"达到对话次数阈值 ({self._extraction_interval})，触发中期记忆提取")
            return True
        
        elapsed = (datetime.now() - self._last_extraction_time).total_seconds()
        if elapsed >= self._extraction_time_interval:
            logger.info(f"达到时间间隔阈值 ({self._extraction_time_interval}秒)，触发中期记忆提取")
            return True
        
        return False
    
    def _write_short_term_directly(self, messages: List[Dict]):
        """直接写入短期记忆，不调用 LLM"""
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            
            if role == "user" and content:
                self._append_short_term_entry("用户", content[:200])
            elif role == "assistant" and content:
                self._append_short_term_entry("助手", content[:200])
        
        self._trim_short_term_entries()
        logger.info("短期记忆直接写入完成")
    
    def _append_short_term_entry(self, role: str, content: str):
        """追加短期记忆条目"""
        current = self.storage.load_short_term()
        timestamp = datetime.now().strftime("%H:%M")
        
        entry = f"- [{timestamp}] {role}: {content}"
        
        current = self._update_section(current, "## 最近对话", entry)
        self.storage.save_short_term(current)
    
    def _trim_short_term_entries(self):
        """修剪短期记忆条目，保持最大数量"""
        content = self.storage.load_short_term()
        
        import re
        dialog_section = re.search(r'## 最近对话\n(.*?)(?=\n##|\Z)', content, re.DOTALL)
        
        if dialog_section:
            entries = dialog_section.group(1).strip().split('\n')
            if len(entries) > self._short_term_max_entries:
                entries = entries[-self._short_term_max_entries:]
                new_dialog = '\n'.join(entries)
                content = content[:dialog_section.start(1)] + new_dialog + "\n" + content[dialog_section.end(1):]
                self.storage.save_short_term(content)
                logger.debug(f"修剪短期记忆到 {self._short_term_max_entries} 条")
    
    def _extract_to_mid_term(self):
        """从短期记忆提取到中期记忆"""
        self._conversation_count = 0
        self._last_extraction_time = datetime.now()
        
        if self.db_storage:
            messages = self.load_recent_conversations(days=1)
        else:
            messages = self._pending_extractions.copy()
        
        if messages and self._summarizer:
            try:
                summary = self.extractor.summarize_day(messages)
                if summary:
                    self.consolidate_to_mid_term(summary)
                    logger.info("中期记忆提取完成")
            except Exception as e:
                logger.error(f"中期记忆提取失败: {e}")
    
    def consolidate_mid_to_long_term(self):
        """从中期记忆整理到长期记忆"""
        mid_term = self.storage.load_mid_term()
        
        if self._summarizer and mid_term:
            try:
                facts = self.extractor.extract_long_term_facts(mid_term)
                if facts:
                    self.consolidate_to_long_term(facts, is_user_told=False)
                    logger.info("中期记忆已整理到长期记忆")
            except Exception as e:
                logger.error(f"中期到长期记忆整理失败: {e}")
    
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
