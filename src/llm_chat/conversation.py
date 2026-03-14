import json
import os
import time
from typing import List, Dict, Optional
from llm_chat.client import LLMClient
from llm_chat.config import Config


class Conversation:
    """对话管理类"""
    
    def __init__(self, client: LLMClient, conversation_id: Optional[str] = None):
        """初始化对话
        
        Args:
            client: 大模型客户端
            conversation_id: 对话 ID，用于持久化
        """
        self.client = client
        self.conversation_id = conversation_id or f"conv_{int(time.time())}"
        self.history: List[Dict[str, str]] = []
        self._load_history()
    
    def add_message(self, role: str, content: str):
        """添加消息到对话历史
        
        Args:
            role: 角色，"user" 或 "assistant"
            content: 消息内容
        """
        self.history.append({"role": role, "content": content})
        self._save_history()
    
    def send_message(self, message: str) -> str:
        """发送消息并获取回复
        
        Args:
            message: 用户输入的消息
            
        Returns:
            模型的回复
        """
        # 添加用户消息到历史
        self.add_message("user", message)
        
        # 发送消息到模型
        response = self.client.chat(message, self.history[:-1])  # 不包含当前消息
        
        # 添加模型回复到历史
        self.add_message("assistant", response)
        
        return response
    
    def get_history(self) -> List[Dict[str, str]]:
        """获取对话历史
        
        Returns:
            对话历史列表
        """
        return self.history.copy()
    
    def clear_history(self):
        """清空对话历史"""
        self.history = []
        self._save_history()
    
    def _load_history(self):
        """从文件加载对话历史"""
        history_file = f".vb/history/{self.conversation_id}.json"
        if os.path.exists(history_file):
            try:
                with open(history_file, "r", encoding="utf-8") as f:
                    self.history = json.load(f)
            except Exception as e:
                print(f"加载对话历史失败: {e}")
                self.history = []
    
    def _save_history(self):
        """保存对话历史到文件"""
        history_dir = ".vb/history"
        os.makedirs(history_dir, exist_ok=True)
        history_file = f"{history_dir}/{self.conversation_id}.json"
        
        try:
            with open(history_file, "w", encoding="utf-8") as f:
                json.dump(self.history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存对话历史失败: {e}")
