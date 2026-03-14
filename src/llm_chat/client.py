import time
from typing import List, Dict, Any, Optional
import requests
from llm_chat.config import Config


class LLMClient:
    """大模型客户端"""
    
    def __init__(self, config: Config):
        """初始化客户端"""
        self.config = config
        self.session = requests.Session()
        self.session.timeout = config.llm.timeout
        
    def chat(self, message: str, history: Optional[List[Dict[str, str]]] = None) -> str:
        """发送聊天消息
        
        Args:
            message: 用户输入的消息
            history: 对话历史，格式为 [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]
            
        Returns:
            模型的回复
        """
        if history is None:
            history = []
        
        # 构建消息列表
        messages = history.copy()
        messages.append({"role": "user", "content": message})
        
        # 构建请求数据
        data = {
            "model": self.config.llm.model,
            "messages": messages,
            "temperature": 0.7
        }
        
        # 发送请求
        return self._send_request(data)
    
    def _send_request(self, data: Dict[str, Any]) -> str:
        """发送请求到模型 API
        
        Args:
            data: 请求数据
            
        Returns:
            模型的回复
        """
        url = f"{self.config.llm.base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json"
        }
        
        if self.config.llm.api_key:
            headers["Authorization"] = f"Bearer {self.config.llm.api_key}"
        
        # 重试机制
        for i in range(self.config.llm.max_retries):
            try:
                response = self.session.post(url, json=data, headers=headers)
                response.raise_for_status()
                
                # 解析响应
                result = response.json()
                return result["choices"][0]["message"]["content"].strip()
                
            except requests.RequestException as e:
                if i == self.config.llm.max_retries - 1:
                    raise
                print(f"请求失败，{i+1}秒后重试: {e}")
                time.sleep(1)
    
    def generate(self, prompt: str) -> str:
        """生成文本
        
        Args:
            prompt: 提示词
            
        Returns:
            生成的文本
        """
        data = {
            "model": self.config.llm.model,
            "prompt": prompt,
            "temperature": 0.7,
            "max_tokens": 1000
        }
        
        url = f"{self.config.llm.base_url}/completions"
        headers = {
            "Content-Type": "application/json"
        }
        
        if self.config.llm.api_key:
            headers["Authorization"] = f"Bearer {self.config.llm.api_key}"
        
        # 重试机制
        for i in range(self.config.llm.max_retries):
            try:
                response = self.session.post(url, json=data, headers=headers)
                response.raise_for_status()
                
                # 解析响应
                result = response.json()
                return result["choices"][0]["text"].strip()
                
            except requests.RequestException as e:
                if i == self.config.llm.max_retries - 1:
                    raise
                print(f"请求失败，{i+1}秒后重试: {e}")
                time.sleep(1)
