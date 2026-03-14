import time
from typing import List, Dict, Any, Optional
import requests
from llm_chat.config import Config
from llm_chat.protocols import get_protocol


class LLMClient:
    """大模型客户端"""
    
    def __init__(self, config: Config):
        """初始化客户端"""
        self.config = config
        self.session = requests.Session()
        self.session.timeout = config.llm.timeout
        self.protocol = get_protocol(
            protocol=config.llm.protocol,
            base_url=config.llm.base_url,
            api_key=config.llm.api_key,
            model=config.llm.model,
            timeout=config.llm.timeout,
            max_retries=config.llm.max_retries
        )
        
    def chat(self, message: str, history: Optional[List[Dict[str, str]]] = None, **kwargs) -> str:
        """发送聊天消息
        
        Args:
            message: 用户输入的消息
            history: 对话历史，格式为 [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]
            **kwargs: 其他参数 (temperature, max_tokens, stream 等)
            
        Returns:
            模型的回复
        """
        if history is None:
            history = []
        
        messages = history.copy()
        messages.append({"role": "user", "content": message})
        
        return self._send_chat_request(messages, **kwargs)
    
    def _send_chat_request(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """发送聊天请求"""
        url = self.protocol.get_chat_url()
        headers = self.protocol.get_headers()
        data = self.protocol.build_chat_request(messages, **kwargs)
        
        for i in range(self.config.llm.max_retries):
            try:
                response = self.session.post(url, json=data, headers=headers)
                response.raise_for_status()
                result = response.json()
                return self.protocol.parse_chat_response(result)
            except requests.RequestException as e:
                if i == self.config.llm.max_retries - 1:
                    raise
                print(f"请求失败，{i+1}秒后重试: {e}")
                time.sleep(1)
    
    def generate(self, prompt: str, **kwargs) -> str:
        """生成文本
        
        Args:
            prompt: 提示词
            **kwargs: 其他参数 (temperature, max_tokens 等)
            
        Returns:
            生成的文本
        """
        url = self.protocol.get_generate_url()
        headers = self.protocol.get_headers()
        data = self.protocol.build_generate_request(prompt, **kwargs)
        
        for i in range(self.config.llm.max_retries):
            try:
                response = self.session.post(url, json=data, headers=headers)
                response.raise_for_status()
                result = response.json()
                return self.protocol.parse_generate_response(result)
            except requests.RequestException as e:
                if i == self.config.llm.max_retries - 1:
                    raise
                print(f"请求失败，{i+1}秒后重试: {e}")
                time.sleep(1)
