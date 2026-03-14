from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional


class BaseProtocol(ABC):
    """协议适配器基类"""
    
    def __init__(self, base_url: str, api_key: Optional[str], model: str, timeout: int, max_retries: int):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
    
    @abstractmethod
    def get_headers(self) -> Dict[str, str]:
        """获取请求头"""
        pass
    
    @abstractmethod
    def get_chat_url(self) -> str:
        """获取聊天 API URL"""
        pass
    
    @abstractmethod
    def build_chat_request(self, messages: List[Dict[str, str]], **kwargs) -> Dict[str, Any]:
        """构建聊天请求体"""
        pass
    
    @abstractmethod
    def parse_chat_response(self, response: Dict[str, Any]) -> str:
        """解析聊天响应"""
        pass
    
    @abstractmethod
    def get_generate_url(self) -> str:
        """获取生成 API URL"""
        pass
    
    @abstractmethod
    def build_generate_request(self, prompt: str, **kwargs) -> Dict[str, Any]:
        """构建生成请求体"""
        pass
    
    @abstractmethod
    def parse_generate_response(self, response: Dict[str, Any]) -> str:
        """解析生成响应"""
        pass
