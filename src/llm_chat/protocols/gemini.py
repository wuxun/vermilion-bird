import json
from typing import Dict, Any, List, Optional
from .base import BaseProtocol, ToolCall


class GeminiProtocol(BaseProtocol):
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
            function_declarations = []
            for tool in tools:
                if tool.get("type") == "function":
                    func = tool.get("function", {})
                    function_declarations.append({
                        "name": func.get("name", ""),
                        "description": func.get("description", ""),
                        "parameters": func.get("parameters", {})
                    })
            
            if function_declarations:
                data["tools"] = [{
                    "functionDeclarations": function_declarations
                }]
        
        return data
    
    def has_tool_calls(self, response: Dict[str, Any]) -> bool:
        parts = response.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        for part in parts:
            if "functionCall" in part:
                return True
        return False
    
    def parse_tool_calls(self, response: Dict[str, Any]) -> List[ToolCall]:
        result = []
        parts = response.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        
        for part in parts:
            if "functionCall" in part:
                fc = part["functionCall"]
                result.append(ToolCall(
                    id=f"gemini_{fc['name']}_{id(fc)}",
                    name=fc["name"],
                    arguments=fc.get("args", {})
                ))
        
        return result
    
    def build_tool_result_message(
        self, 
        tool_call: ToolCall, 
        result: str,
        is_error: bool = False
    ) -> Dict[str, Any]:
        return {
            "role": "function",
            "parts": [{
                "functionResponse": {
                    "name": tool_call.name,
                    "response": {
                        "content": result,
                        "error": is_error
                    }
                }
            }]
        }
    
    def get_assistant_message_from_response(self, response: Dict[str, Any]) -> Dict[str, Any]:
        parts = response.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        content_parts = []
        
        for part in parts:
            if "text" in part:
                content_parts.append({"text": part["text"]})
            elif "functionCall" in part:
                content_parts.append({"functionCall": part["functionCall"]})
        
        return {
            "role": "model",
            "parts": content_parts
        }
