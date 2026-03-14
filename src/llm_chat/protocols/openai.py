from typing import Dict, Any, List, Optional
from .base import BaseProtocol


class OpenAIProtocol(BaseProtocol):
    """OpenAI 协议适配器
    
    兼容: OpenAI, Azure OpenAI, Ollama, vLLM, 智谱 GLM 等
    """
    
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
