import json
import uuid
from typing import Dict, Any, List, Optional
from .base import BaseProtocol, ToolCall


class AnthropicProtocol(BaseProtocol):
    def get_headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        }
        if self.api_key:
            headers["x-api-key"] = self.api_key
        return headers
    
    def get_chat_url(self) -> str:
        return f"{self.base_url}/messages"
    
    def build_chat_request(self, messages: List[Dict[str, str]], **kwargs) -> Dict[str, Any]:
        system_prompt = kwargs.get("system", "")
        data = {
            "model": self.model,
            "messages": messages,
            "max_tokens": kwargs.get("max_tokens", 4096),
        }
        if system_prompt:
            data["system"] = system_prompt
        return data
    
    def parse_chat_response(self, response: Dict[str, Any]) -> str:
        for block in response["content"]:
            if block["type"] == "text":
                return block["text"].strip()
        return ""
    
    def get_generate_url(self) -> str:
        return f"{self.base_url}/complete"
    
    def build_generate_request(self, prompt: str, **kwargs) -> Dict[str, Any]:
        data = {
            "model": self.model,
            "prompt": prompt,
            "max_tokens_to_sample": kwargs.get("max_tokens", 1000),
        }
        return data
    
    def parse_generate_response(self, response: Dict[str, Any]) -> str:
        return response["completion"].strip()
    
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
        return data
    
    def has_tool_calls(self, response: Dict[str, Any]) -> bool:
        for block in response.get("content", []):
            if block.get("type") == "tool_use":
                return True
        return False
    
    def parse_tool_calls(self, response: Dict[str, Any]) -> List[ToolCall]:
        result = []
        for block in response.get("content", []):
            if block.get("type") == "tool_use":
                result.append(ToolCall(
                    id=block["id"],
                    name=block["name"],
                    arguments=block.get("input", {})
                ))
        return result
    
    def build_tool_result_message(
        self, 
        tool_call: ToolCall, 
        result: str,
        is_error: bool = False
    ) -> Dict[str, Any]:
        content = []
        if is_error:
            content.append({
                "type": "tool_result",
                "tool_use_id": tool_call.id,
                "content": result,
                "is_error": True
            })
        else:
            content.append({
                "type": "tool_result",
                "tool_use_id": tool_call.id,
                "content": result
            })
        
        return {
            "role": "user",
            "content": content
        }
    
    def get_assistant_message_from_response(self, response: Dict[str, Any]) -> Dict[str, Any]:
        content = []
        for block in response.get("content", []):
            if block.get("type") == "text":
                content.append({"type": "text", "text": block["text"]})
            elif block.get("type") == "tool_use":
                content.append(block)
        
        return {
            "role": "assistant",
            "content": content
        }
