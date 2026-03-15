import time
from typing import List, Dict, Any, Optional
from llm_chat.client import LLMClient
from llm_chat.storage import Storage


class Conversation:
    def __init__(self, client: LLMClient, conversation_id: Optional[str] = None, storage: Optional[Storage] = None):
        self.client = client
        self.conversation_id = conversation_id or f"conv_{int(time.time())}"
        self.storage = storage or Storage()
        self._ensure_conversation()
    
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
        
        response = self.client.chat(message, self._get_simple_history())
        
        self.add_assistant_message(response)
        
        return response
    
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


class ConversationManager:
    def __init__(self, client: LLMClient, storage: Optional[Storage] = None):
        self.client = client
        self.storage = storage or Storage()
        self._conversations: Dict[str, Conversation] = {}
    
    def get_conversation(self, conversation_id: str) -> Conversation:
        if conversation_id not in self._conversations:
            self._conversations[conversation_id] = Conversation(
                self.client, conversation_id, self.storage
            )
        return self._conversations[conversation_id]
    
    def create_conversation(self, title: Optional[str] = None) -> Conversation:
        conversation_id = f"conv_{int(time.time())}"
        self.storage.create_conversation(conversation_id, title)
        conv = Conversation(self.client, conversation_id, self.storage)
        self._conversations[conversation_id] = conv
        return conv
    
    def list_conversations(self, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        return self.storage.list_conversations(limit, offset)
    
    def delete_conversation(self, conversation_id: str) -> bool:
        if conversation_id in self._conversations:
            del self._conversations[conversation_id]
        return self.storage.delete_conversation(conversation_id)
    
    def search_messages(self, query: str, conversation_id: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        return self.storage.search_messages(query, conversation_id, limit)
    
    def migrate_from_json(self, json_dir: str = ".vb/history") -> int:
        return self.storage.migrate_from_json(json_dir)
