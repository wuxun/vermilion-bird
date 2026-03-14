import time
from typing import List, Dict, Any, Optional, Callable
import requests
from llm_chat.config import Config
from llm_chat.protocols import get_protocol, ToolCall


class LLMClient:
    def __init__(self, config: Config):
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
        self._tool_executor: Optional[Callable[[str, Dict[str, Any]], str]] = None
    
    def set_tool_executor(self, executor: Callable[[str, Dict[str, Any]], str]):
        self._tool_executor = executor
    
    def chat(self, message: str, history: Optional[List[Dict[str, str]]] = None, **kwargs) -> str:
        if history is None:
            history = []
        
        messages = history.copy()
        messages.append({"role": "user", "content": message})
        
        return self._send_chat_request(messages, **kwargs)
    
    def chat_with_tools(
        self, 
        message: str, 
        tools: List[Dict[str, Any]],
        history: Optional[List[Dict[str, Any]]] = None,
        **kwargs
    ) -> str:
        if history is None:
            history = []
        
        messages = history.copy()
        messages.append({"role": "user", "content": message})
        
        return self._send_chat_request_with_tools(messages, tools, **kwargs)
    
    def _send_chat_request(self, messages: List[Dict[str, str]], **kwargs) -> str:
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
        
        return ""
    
    def _send_chat_request_with_tools(
        self, 
        messages: List[Dict[str, Any]], 
        tools: List[Dict[str, Any]],
        max_iterations: int = 10,
        **kwargs
    ) -> str:
        if not self.protocol.supports_tools():
            return self._send_chat_request(messages, **kwargs)
        
        url = self.protocol.get_chat_url()
        headers = self.protocol.get_headers()
        
        current_messages = messages.copy()
        
        for iteration in range(max_iterations):
            data = self.protocol.build_chat_request_with_tools(
                current_messages, 
                tools, 
                **kwargs
            )
            
            for i in range(self.config.llm.max_retries):
                try:
                    response = self.session.post(url, json=data, headers=headers)
                    response.raise_for_status()
                    result = response.json()
                    break
                except requests.RequestException as e:
                    if i == self.config.llm.max_retries - 1:
                        raise
                    print(f"请求失败，{i+1}秒后重试: {e}")
                    time.sleep(1)
            else:
                continue
            
            if not self.protocol.has_tool_calls(result):
                return self.protocol.parse_chat_response(result)
            
            assistant_message = self.protocol.get_assistant_message_from_response(result)
            current_messages.append(assistant_message)
            
            tool_calls = self.protocol.parse_tool_calls(result)
            
            for tool_call in tool_calls:
                if self._tool_executor:
                    try:
                        tool_result = self._tool_executor(tool_call.name, tool_call.arguments)
                        is_error = False
                    except Exception as e:
                        tool_result = str(e)
                        is_error = True
                else:
                    tool_result = f"Error: No tool executor configured for {tool_call.name}"
                    is_error = True
                
                tool_message = self.protocol.build_tool_result_message(
                    tool_call, 
                    tool_result, 
                    is_error
                )
                current_messages.append(tool_message)
        
        return self.protocol.parse_chat_response(result)
    
    def generate(self, prompt: str, **kwargs) -> str:
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
        
        return ""
