from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from enum import Enum


class ToolCallStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: Dict[str, Any]
    status: ToolCallStatus = ToolCallStatus.PENDING
    result: Optional[str] = None
    error: Optional[str] = None


@dataclass
class ToolCallResult:
    tool_call_id: str
    content: str
    is_error: bool = False


class BaseProtocol(ABC):
    def __init__(self, base_url: str, api_key: Optional[str], model: str, timeout: int, max_retries: int):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
    
    @abstractmethod
    def get_headers(self) -> Dict[str, str]:
        pass
    
    @abstractmethod
    def get_chat_url(self) -> str:
        pass
    
    @abstractmethod
    def build_chat_request(self, messages: List[Dict[str, str]], **kwargs) -> Dict[str, Any]:
        pass
    
    @abstractmethod
    def parse_chat_response(self, response: Dict[str, Any]) -> str:
        pass
    
    @abstractmethod
    def get_generate_url(self) -> str:
        pass
    
    @abstractmethod
    def build_generate_request(self, prompt: str, **kwargs) -> Dict[str, Any]:
        pass
    
    @abstractmethod
    def parse_generate_response(self, response: Dict[str, Any]) -> str:
        pass
    
    def supports_tools(self) -> bool:
        return False
    
    def build_chat_request_with_tools(
        self, 
        messages: List[Dict[str, Any]], 
        tools: List[Dict[str, Any]],
        **kwargs
    ) -> Dict[str, Any]:
        return self.build_chat_request(messages, **kwargs)
    
    def parse_tool_calls(self, response: Dict[str, Any]) -> List[ToolCall]:
        return []
    
    def has_tool_calls(self, response: Dict[str, Any]) -> bool:
        return False
    
    def build_tool_result_message(
        self, 
        tool_call: ToolCall, 
        result: str,
        is_error: bool = False
    ) -> Dict[str, Any]:
        return {"role": "tool", "content": result}
    
    def get_assistant_message_from_response(self, response: Dict[str, Any]) -> Dict[str, Any]:
        return {"role": "assistant", "content": self.parse_chat_response(response)}
