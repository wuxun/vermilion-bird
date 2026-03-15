import time
import logging
from typing import List, Dict, Any, Optional
from llm_chat.client import LLMClient
from llm_chat.storage import Storage

logger = logging.getLogger(__name__)


class Conversation:
    def __init__(
        self, 
        client: LLMClient, 
        conversation_id: Optional[str] = None, 
        storage: Optional[Storage] = None,
        memory_config: Optional[Dict] = None
    ):
        self.client = client
        self.conversation_id = conversation_id or f"conv_{int(time.time())}"
        self.storage = storage or Storage()
        self.memory_config = memory_config or {}
        self._ensure_conversation()
        self._memory_manager = None
        self._init_memory()
    
    def _init_memory(self):
        """初始化记忆管理器"""
        if self.memory_config.get("enabled", False):
            try:
                from llm_chat.memory import MemoryManager, MemoryStorage
                memory_storage = MemoryStorage(
                    self.memory_config.get("storage_dir", "~/.vermilion-bird/memory")
                )
                self._memory_manager = MemoryManager(
                    storage=memory_storage,
                    db_storage=self.storage,
                    llm_client=self.client,
                    config=self.memory_config
                )
                logger.info("记忆系统已初始化")
            except Exception as e:
                logger.warning(f"记忆系统初始化失败: {e}")
                self._memory_manager = None
    
    def _ensure_conversation(self):
        existing = self.storage.get_conversation(self.conversation_id)
        if not existing:
            self.storage.create_conversation(self.conversation_id)
    
    def add_message(self, role: str, content: str, **kwargs):
        metadata = kwargs if kwargs else None
        self.storage.add_message(self.conversation_id, role, content, metadata)
        
        if role == "user" and not self._get_title():
            title = content[:30]
            if len(content) > 30:
                title += "..."
            self.storage.update_conversation(self.conversation_id, title=title)
    
    def add_user_message(self, content: str):
        self.add_message("user", content)
    
    def add_assistant_message(self, content: str, tool_calls: Optional[List[Dict]] = None):
        metadata = {"tool_calls": tool_calls} if tool_calls else None
        self.storage.add_message(self.conversation_id, "assistant", content, metadata)
    
    def add_tool_message(self, tool_call_id: str, content: str):
        metadata = {"tool_call_id": tool_call_id}
        self.storage.add_message(self.conversation_id, "tool", content, metadata)
    
    def send_message(self, message: str) -> str:
        self.add_user_message(message)
        
        memory_context = self._get_memory_context()
        
        response = self.client.chat(
            message, 
            self._get_simple_history(),
            system_context=memory_context
        )
        
        self.add_assistant_message(response)
        
        self._extract_memory_async(message, response)
        
        return response
    
    def _get_memory_context(self) -> Optional[str]:
        """获取记忆上下文"""
        if self._memory_manager:
            return self._memory_manager.build_system_prompt()
        return None
    
    def _extract_memory_async(self, user_message: str, assistant_response: str):
        """异步提取记忆"""
        if self._memory_manager:
            try:
                messages = [
                    {"role": "user", "content": user_message},
                    {"role": "assistant", "content": assistant_response}
                ]
                self._memory_manager.schedule_extraction(messages)
                self._memory_manager.process_pending_extractions()
            except Exception as e:
                logger.warning(f"记忆提取失败: {e}")
    
    def end_session(self):
        """结束会话，归档记忆"""
        if self._memory_manager:
            try:
                self._memory_manager.archive_session(self.conversation_id)
                logger.info(f"会话已归档: {self.conversation_id}")
            except Exception as e:
                logger.warning(f"会话归档失败: {e}")
    
    def _get_simple_history(self) -> List[Dict[str, str]]:
        messages = self.storage.get_messages(self.conversation_id)
        result = []
        for msg in messages[:-1]:
            if msg.get("role") in ("user", "assistant") and msg.get("content"):
                result.append({
                    "role": msg["role"],
                    "content": msg["content"]
                })
        return result
    
    def get_history(self) -> List[Dict[str, Any]]:
        return self.storage.get_messages(self.conversation_id)
    
    def clear_history(self):
        self.storage.clear_messages(self.conversation_id)
    
    def _get_title(self) -> Optional[str]:
        conv = self.storage.get_conversation(self.conversation_id)
        return conv.get("title") if conv else None
    
    def set_title(self, title: str):
        self.storage.update_conversation(self.conversation_id, title=title)
    
    def get_memory_stats(self) -> Optional[Dict]:
        """获取记忆统计信息"""
        if self._memory_manager:
            return self._memory_manager.get_memory_stats()
        return None


class ConversationManager:
    def __init__(self, client: LLMClient, storage: Optional[Storage] = None, memory_config: Optional[Dict] = None):
        self.client = client
        self.storage = storage or Storage()
        self.memory_config = memory_config or {}
        self._conversations: Dict[str, Conversation] = {}
    
    def get_conversation(self, conversation_id: str) -> Conversation:
        if conversation_id not in self._conversations:
            self._conversations[conversation_id] = Conversation(
                self.client, conversation_id, self.storage, self.memory_config
            )
        return self._conversations[conversation_id]
    
    def create_conversation(self, title: Optional[str] = None) -> Conversation:
        conversation_id = f"conv_{int(time.time())}"
        self.storage.create_conversation(conversation_id, title)
        conv = Conversation(self.client, conversation_id, self.storage, self.memory_config)
        self._conversations[conversation_id] = conv
        return conv
    
    def list_conversations(self, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        return self.storage.list_conversations(limit, offset)
    
    def delete_conversation(self, conversation_id: str) -> bool:
        if conversation_id in self._conversations:
            conv = self._conversations[conversation_id]
            conv.end_session()
            del self._conversations[conversation_id]
        return self.storage.delete_conversation(conversation_id)
    
    def search_messages(self, query: str, conversation_id: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        return self.storage.search_messages(query, conversation_id, limit)
    
    def migrate_from_json(self, json_dir: str = ".vb/history") -> int:
        return self.storage.migrate_from_json(json_dir)
    
    def evolve_memories(self):
        """进化所有记忆"""
        for conv in self._conversations.values():
            if conv._memory_manager:
                conv._memory_manager.evolve_understanding()
