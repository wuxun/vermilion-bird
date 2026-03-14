import json
import os
import time
from typing import List, Dict, Any, Optional
from llm_chat.client import LLMClient
from llm_chat.config import Config


class Conversation:
    def __init__(self, client: LLMClient, conversation_id: Optional[str] = None):
        self.client = client
        self.conversation_id = conversation_id or f"conv_{int(time.time())}"
        self.history: List[Dict[str, Any]] = []
        self._load_history()
    
    def add_message(self, role: str, content: str, **kwargs):
        message: Dict[str, Any] = {"role": role, "content": content}
        message.update(kwargs)
        self.history.append(message)
        self._save_history()
    
    def add_user_message(self, content: str):
        self.add_message("user", content)
    
    def add_assistant_message(self, content: str, tool_calls: Optional[List[Dict]] = None):
        if tool_calls:
            self.history.append({
                "role": "assistant",
                "content": content,
                "tool_calls": tool_calls
            })
        else:
            self.add_message("assistant", content)
    
    def add_tool_message(self, tool_call_id: str, content: str):
        self.history.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": content
        })
    
    def send_message(self, message: str) -> str:
        self.add_user_message(message)
        
        response = self.client.chat(message, self._get_simple_history())
        
        self.add_assistant_message(response)
        
        return response
    
    def _get_simple_history(self) -> List[Dict[str, str]]:
        result = []
        for msg in self.history[:-1]:
            if msg.get("role") in ("user", "assistant") and msg.get("content"):
                result.append({
                    "role": msg["role"],
                    "content": msg["content"]
                })
        return result
    
    def get_history(self) -> List[Dict[str, Any]]:
        return self.history.copy()
    
    def clear_history(self):
        self.history = []
        self._save_history()
    
    def _load_history(self):
        history_file = f".vb/history/{self.conversation_id}.json"
        if os.path.exists(history_file):
            try:
                with open(history_file, "r", encoding="utf-8") as f:
                    self.history = json.load(f)
            except Exception as e:
                print(f"加载对话历史失败: {e}")
                self.history = []
    
    def _save_history(self):
        history_dir = ".vb/history"
        os.makedirs(history_dir, exist_ok=True)
        history_file = f"{history_dir}/{self.conversation_id}.json"
        
        try:
            with open(history_file, "w", encoding="utf-8") as f:
                json.dump(self.history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存对话历史失败: {e}")
