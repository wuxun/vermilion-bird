from typing import Dict, Any, List, Optional
from .base import BaseProtocol


class AnthropicProtocol(BaseProtocol):
    """Anthropic Claude 协议适配器"""
    
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
