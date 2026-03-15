import json
import uuid
from typing import Dict, Any, List, Optional
from .base import BaseProtocol, ToolCall


class OpenAIProtocol(BaseProtocol):
    def get_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers
    
    def get_chat_url(self) -> str:
        return f"{self.base_url}/chat/completions"
    
    def build_chat_request(self, messages: List[Dict[str, str]], **kwargs) -> Dict[str, Any]:
        data = {
            "model": self.model,
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.7),
        }
        if kwargs.get("max_tokens"):
            data["max_tokens"] = kwargs["max_tokens"]
        if kwargs.get("stream"):
            data["stream"] = kwargs["stream"]
        return data
    
    def parse_chat_response(self, response: Dict[str, Any]) -> str:
        return response["choices"][0]["message"]["content"].strip()
    
    def get_generate_url(self) -> str:
        return f"{self.base_url}/completions"
    
    def build_generate_request(self, prompt: str, **kwargs) -> Dict[str, Any]:
        data = {
            "model": self.model,
            "prompt": prompt,
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens", 1000),
        }
        return data
    
    def parse_generate_response(self, response: Dict[str, Any]) -> str:
        return response["choices"][0]["text"].strip()
    
    def supports_tools(self) -> bool:
        return True
    
    def build_chat_request_with_tools(
        self, 
        messages: List[Dict[str, Any]], 
        tools: List[Dict[str, Any]],
        **kwargs
    ) -> Dict[str, Any]:
        data = self.build_chat_request(messages, **kwargs)
        if tools:
            data["tools"] = tools
            data["tool_choice"] = kwargs.get("tool_choice", "auto")
        return data
    
    def has_tool_calls(self, response: Dict[str, Any]) -> bool:
        message = response["choices"][0]["message"]
        return message.get("tool_calls") is not None and len(message["tool_calls"]) > 0
    
    def parse_tool_calls(self, response: Dict[str, Any]) -> List[ToolCall]:
        message = response["choices"][0]["message"]
        tool_calls = message.get("tool_calls", [])
        
        result = []
        for tc in tool_calls:
            if tc["type"] == "function":
                try:
                    arguments = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    arguments = {}
                
                result.append(ToolCall(
                    id=tc["id"],
                    name=tc["function"]["name"],
                    arguments=arguments
                ))
        
        return result
    
    def build_tool_result_message(
        self, 
        tool_call: ToolCall, 
        result: str,
        is_error: bool = False
    ) -> Dict[str, Any]:
        return {
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": result
        }
    
    def get_assistant_message_from_response(self, response: Dict[str, Any]) -> Dict[str, Any]:
        message = response["choices"][0]["message"]
        msg = {"role": "assistant"}
        
        if message.get("content"):
            msg["content"] = message["content"]
        
        if message.get("tool_calls"):
            msg["tool_calls"] = message["tool_calls"]
        
        return msg
    
    def parse_stream_chunk(self, chunk: Dict[str, Any]) -> Optional[str]:
        choices = chunk.get("choices", [])
        if not choices:
            return None
        
        delta = choices[0].get("delta", {})
        content = delta.get("content")
        
        return content if content else None
