import re
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from llm_chat.memory.summarizer import Summarizer

logger = logging.getLogger(__name__)


SENSITIVE_PATTERNS = [
    r'密码',
    r'password',
    r'token',
    r'api[_-]?key',
    r'secret',
    r'密钥',
    r'私钥',
    r'private[_-]?key',
    r'access[_-]?key',
    r'auth[_-]?token',
    r'credential',
]


class MemoryExtractor:
    """从对话中提取记忆信息"""
    
    EXTRACTION_PROMPT = """分析以下对话，提取值得记忆的信息。

对话内容：
{conversation}

请提取以下类型的信息（如果存在）：

1. 用户偏好：用户明确表达的偏好（如语言风格、回复格式、代码风格等）
2. 重要事实：用户主动告知的个人信息、工作信息、习惯等
3. 当前任务：用户正在进行的工作或任务
4. 待办事项：用户提到需要做的事情
5. 重要事件：值得记录的重要事件

请以JSON格式输出，格式如下：
{{
    "user_preferences": ["偏好1", "偏好2"],
    "important_facts": ["事实1", "事实2"],
    "current_task": "当前任务描述",
    "pending_items": ["待办1", "待办2"],
    "important_events": ["事件1", "事件2"]
}}

注意：
- 不要包含敏感信息（密码、token、密钥等）
- 只提取用户明确表达或可以合理推断的信息
- 如果某类信息不存在，对应字段留空数组或空字符串"""

    SUMMARIZE_DAY_PROMPT = """请为以下对话生成一个简洁的每日摘要。

对话内容：
{conversation}

要求：
1. 总结今天讨论的主要话题
2. 记录完成的工作或任务
3. 提及重要的决定或结论
4. 保持简洁，不超过100字

请直接输出摘要内容，不要包含其他内容。"""

    PREFERENCE_DETECTION_PROMPT = """分析以下对话，检测用户的沟通偏好。

对话内容：
{conversation}

请检测以下偏好（如果可以确定）：
1. 语言偏好（中文/英文/混合）
2. 回复风格偏好（简洁/详细）
3. 代码风格偏好
4. 其他明显的沟通偏好

请以JSON格式输出：
{{
    "language": "中文/英文/混合",
    "style": "简洁/详细",
    "code_style": "描述",
    "other": ["其他偏好"]
}}"""

    def __init__(self, llm_client=None, summarizer: Optional["Summarizer"] = None):
        self.llm_client = llm_client  # 向后兼容，已弃用
        self._summarizer = summarizer

    def _get_summarizer(self) -> Optional["Summarizer"]:
        """获取摘要器：优先用注入的 Summarizer，否则尝试用 llm_client 构建。"""
        if self._summarizer is not None:
            return self._summarizer
        if self.llm_client is not None:
            from llm_chat.memory.summarizer import LLMSummarizer
            return LLMSummarizer(self.llm_client)
        return None

    def extract(self, messages: List[Dict]) -> Dict[str, Any]:
        """从消息列表中提取记忆信息"""
        if not messages:
            return self._empty_result()
        
        conversation_text = self._format_conversation(messages)
        
        if self._contains_sensitive_info(conversation_text):
            logger.warning("对话包含敏感信息，跳过记忆提取")
            return self._empty_result()

        summarizer = self._get_summarizer()
        if summarizer is not None:
            return self._extract_with_llm(conversation_text, summarizer)
        else:
            return self._extract_with_rules(messages)
    
    def summarize_day(self, messages: List[Dict]) -> str:
        """生成每日摘要"""
        if not messages:
            return ""
        
        conversation_text = self._format_conversation(messages)
        
        if self._contains_sensitive_info(conversation_text):
            conversation_text = self._redact_sensitive_info(conversation_text)

        summarizer = self._get_summarizer()
        if summarizer is not None:
            return self._summarize_with_llm(conversation_text, summarizer)
        else:
            return self._summarize_with_rules(messages)
    
    def detect_user_preferences(self, messages: List[Dict]) -> Dict[str, Any]:
        """检测用户偏好"""
        if not messages:
            return {}
        
        preferences = {
            "language": self._detect_language(messages),
            "style": self._detect_style(messages),
            "code_style": self._detect_code_style(messages),
        }
        
        return {k: v for k, v in preferences.items() if v}
    
    def _format_conversation(self, messages: List[Dict]) -> str:
        """格式化对话内容"""
        lines = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if content:
                lines.append(f"[{role}]: {content}")
        return "\n".join(lines)
    
    def _contains_sensitive_info(self, text: str) -> bool:
        """检查是否包含敏感信息"""
        text_lower = text.lower()
        for pattern in SENSITIVE_PATTERNS:
            if re.search(pattern, text_lower, re.IGNORECASE):
                return True
        return False
    
    def _redact_sensitive_info(self, text: str) -> str:
        """替换敏感信息"""
        redacted = text
        for pattern in SENSITIVE_PATTERNS:
            redacted = re.sub(
                rf'({pattern}[\s:=]+)\S+',
                r'\1[REDACTED]',
                redacted,
                flags=re.IGNORECASE
            )
        return redacted
    
    @staticmethod
    def _parse_llm_json(response: str) -> Dict[str, Any]:
        """从 LLM 响应中解析 JSON，处理 Markdown 代码块包裹等常见格式"""
        import json

        text = response.strip()

        # 尝试从 ```json ... ``` 或 ``` ... ``` 代码块中提取
        code_block_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
        if code_block_match:
            text = code_block_match.group(1).strip()

        return json.loads(text)

    def _extract_with_llm(
        self, conversation: str, summarizer: "Summarizer"
    ) -> Dict[str, Any]:
        """使用 LLM (通过 Summarizer) 提取记忆"""
        try:
            prompt = self.EXTRACTION_PROMPT.format(conversation=conversation)
            response = summarizer.generate(prompt, max_tokens=300)
            if response is None:
                raise ValueError("Summarizer 返回 None")
            result = self._parse_llm_json(response)
            logger.info("使用LLM成功提取记忆")
            return result
        except Exception as e:
            logger.error(f"LLM提取记忆失败: {e}")
            return self._empty_result()
    
    def _extract_with_rules(self, messages: List[Dict]) -> Dict[str, Any]:
        """使用规则提取记忆"""
        result = self._empty_result()
        
        for msg in messages:
            if msg.get("role") == "user":
                content = msg.get("content", "")
                
                task_match = re.search(r'(正在|开始|继续|完成).{0,20}(工作|任务|项目|功能)', content)
                if task_match:
                    result["current_task"] = task_match.group(0)
                
                todo_match = re.findall(r'(需要|要|得|应该).{0,30}[做写修看学]', content)
                result["pending_items"].extend(todo_match)
                
                preference_patterns = [
                    r'我喜欢(.{1,20})',
                    r'我偏好(.{1,20})',
                    r'请(.{1,20})回复',
                    r'用(.{1,20})格式',
                ]
                for pattern in preference_patterns:
                    matches = re.findall(pattern, content)
                    result["user_preferences"].extend(matches)
        
        return result
    
    def _summarize_with_llm(
        self, conversation: str, summarizer: "Summarizer"
    ) -> str:
        """使用 LLM (通过 Summarizer) 生成摘要"""
        try:
            prompt = self.SUMMARIZE_DAY_PROMPT.format(conversation=conversation)
            response = summarizer.generate(prompt, max_tokens=200)
            if response is None:
                raise ValueError("Summarizer 返回 None")
            logger.info("使用LLM成功生成摘要")
            return response.strip()
        except Exception as e:
            logger.error(f"LLM生成摘要失败: {e}")
            return ""
    
    def _summarize_with_rules(self, messages: List[Dict]) -> str:
        """使用规则生成摘要"""
        topics = set()
        for msg in messages:
            content = msg.get("content", "")
            words = re.findall(r'[\u4e00-\u9fa5]{2,4}', content)
            topics.update(words[:5])
        
        if topics:
            return f"讨论了：{', '.join(list(topics)[:5])}"
        return ""
    
    def _detect_language(self, messages: List[Dict]) -> str:
        """检测语言偏好"""
        chinese_count = 0
        english_count = 0
        
        for msg in messages:
            content = msg.get("content", "")
            chinese_chars = len(re.findall(r'[\u4e00-\u9fa5]', content))
            english_chars = len(re.findall(r'[a-zA-Z]', content))
            chinese_count += chinese_chars
            english_count += english_chars
        
        if chinese_count > english_count * 2:
            return "中文"
        elif english_count > chinese_count * 2:
            return "英文"
        else:
            return "混合"
    
    def _detect_style(self, messages: List[Dict]) -> str:
        """检测回复风格偏好"""
        for msg in messages:
            content = msg.get("content", "").lower()
            if "简洁" in content or "简单" in content:
                return "简洁"
            if "详细" in content or "详细解释" in content:
                return "详细"
        return ""
    
    def _detect_code_style(self, messages: List[Dict]) -> str:
        """检测代码风格偏好"""
        style_keywords = []
        
        for msg in messages:
            content = msg.get("content", "")
            
            if "高内聚" in content or "低耦合" in content:
                style_keywords.append("高内聚低耦合")
            if "注释" in content:
                style_keywords.append("需要注释")
            if "日志" in content:
                style_keywords.append("关键位置打印日志")
            if "类型提示" in content or "type hint" in content.lower():
                style_keywords.append("类型提示")
        
        return ", ".join(style_keywords) if style_keywords else ""
    
    def _empty_result(self) -> Dict[str, Any]:
        """返回空结果"""
        return {
            "user_preferences": [],
            "important_facts": [],
            "current_task": "",
            "pending_items": [],
            "important_events": []
        }
    
    def calculate_importance(self, info: Dict) -> float:
        """计算信息重要性分数"""
        score = 0.0
        
        if info.get("important_facts"):
            score += 0.4
        
        if info.get("user_preferences"):
            score += 0.3
        
        if info.get("current_task"):
            score += 0.2
        
        if info.get("important_events"):
            score += 0.1
        
        return min(score, 1.0)
    
    def should_remember(self, info: Dict, threshold: float = 0.3) -> bool:
        """判断是否值得记忆"""
        return self.calculate_importance(info) >= threshold
    
    EXTRACT_LONG_TERM_PROMPT = """分析以下中期记忆内容，提取值得长期保存的重要事实和用户偏好。

中期记忆内容：
{mid_term_content}

请提取以下类型的信息：
1. 用户偏好：用户明确表达的长期偏好（如语言风格、工作习惯等）
2. 重要事实：用户的个人信息、职业、兴趣等长期有效的事实
3. 关键事件：对用户有长期影响的重要事件

请以JSON格式输出：
{{
    "user_preferences": ["偏好1", "偏好2"],
    "important_facts": ["事实1", "事实2"],
    "key_events": ["事件1", "事件2"]
}}

注意：
- 只提取长期有效的信息，不要提取临时性的内容
- 不要包含敏感信息
- 如果某类信息不存在，对应字段留空数组"""

    def extract_long_term_facts(self, mid_term_content: str) -> List[str]:
        """从中期记忆提取长期事实"""
        if not mid_term_content or len(mid_term_content) < 50:
            return []
        
        if self._contains_sensitive_info(mid_term_content):
            mid_term_content = self._redact_sensitive_info(mid_term_content)

        summarizer = self._get_summarizer()
        if summarizer is not None:
            return self._extract_long_term_with_llm(mid_term_content, summarizer)
        else:
            return self._extract_long_term_with_rules(mid_term_content)

    def _extract_long_term_with_llm(
        self, content: str, summarizer: "Summarizer"
    ) -> List[str]:
        """使用LLM提取长期事实"""
        try:
            prompt = self.EXTRACT_LONG_TERM_PROMPT.format(mid_term_content=content)
            response = summarizer.generate(prompt, max_tokens=400)
            if response is None:
                raise ValueError("Summarizer 返回 None")
            result = self._parse_llm_json(response)

            facts = []
            facts.extend(result.get("user_preferences", []))
            facts.extend(result.get("important_facts", []))
            facts.extend(result.get("key_events", []))
            
            logger.info(f"使用LLM提取长期事实: {len(facts)} 条")
            return facts
        except Exception as e:
            logger.error(f"LLM提取长期事实失败: {e}")
            return []
    
    def _extract_long_term_with_rules(self, content: str) -> List[str]:
        """使用规则提取长期事实"""
        facts = []
        
        preference_patterns = [
            r'偏好[：:]\s*(.+)',
            r'喜欢[：:]\s*(.+)',
            r'习惯[：:]\s*(.+)',
        ]
        
        for pattern in preference_patterns:
            matches = re.findall(pattern, content)
            facts.extend(matches)
        
        logger.info(f"使用规则提取长期事实: {len(facts)} 条")
        return facts
