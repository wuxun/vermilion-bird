from typing import Dict, Any, List, Optional
from .base import BaseProtocol


class GeminiProtocol(BaseProtocol):
    """Google Gemini 协议适配器"""
    
    def get_headers(self) -> Dict[str, str]:
        return {"Content-Type": "application/json"}
    
    def get_chat_url(self) -> str:
        return f"{self.base_url}/models/{self.model}:generateContent?key={self.api_key}"
    
    def build_chat_request(self, messages: List[Dict[str, str]], **kwargs) -> Dict[str, Any]:
        contents = []
        for msg in messages:
            role = "user" if msg["role"] == "user" else "model"
            contents.append({
                "role": role,
                "parts": [{"text": msg["content"]}]
            })
        
        data = {
            "contents": contents,
            "generationConfig": {
                "temperature": kwargs.get("temperature", 0.7),
                "maxOutputTokens": kwargs.get("max_tokens", 8192),
            }
        }
        return data
    
    def parse_chat_response(self, response: Dict[str, Any]) -> str:
        return response["candidates"][0]["content"]["parts"][0]["text"].strip()
    
    def get_generate_url(self) -> str:
        return f"{self.base_url}/models/{self.model}:generateContent?key={self.api_key}"
    
    def build_generate_request(self, prompt: str, **kwargs) -> Dict[str, Any]:
        data = {
            "contents": [{
                "parts": [{"text": prompt}]
            }],
            "generationConfig": {
                "temperature": kwargs.get("temperature", 0.7),
                "maxOutputTokens": kwargs.get("max_tokens", 8192),
            }
        }
        return data
    
    def parse_generate_response(self, response: Dict[str, Any]) -> str:
        return response["candidates"][0]["content"]["parts"][0]["text"].strip()
