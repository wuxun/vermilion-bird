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
        system_instruction = None

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "system":
                # Gemini 使用 systemInstruction 而非 message
                if system_instruction is None:
                    system_instruction = {"parts": [{"text": content}]}
                else:
                    system_instruction["parts"].append({"text": content})
            elif role in ("user", "function"):
                contents.append({
                    "role": "user",
                    "parts": [{"text": content}]
                })
            elif role == "tool":
                # 工具结果消息 (从 build_tool_result_message 来，有 parts 字段)
                parts_data = msg.get("parts", [{"text": content}])
                contents.append({
                    "role": "function",
                    "parts": parts_data
                })
            else:
                # assistant / model / fallback
                contents.append({
                    "role": "model",
                    "parts": [{"text": content}]
                })
        
        generation_config = {}
        
        if kwargs.get("temperature") is not None:
            generation_config["temperature"] = kwargs["temperature"]
        
        if kwargs.get("max_tokens"):
            generation_config["maxOutputTokens"] = kwargs["max_tokens"]
        
        if kwargs.get("top_p") is not None:
            generation_config["topP"] = kwargs["top_p"]
        
        if kwargs.get("reasoning_effort"):
            budget_map = {
                "low": 1024,
                "medium": 8192,
                "high": 24576
            }
            generation_config["thinkingBudget"] = budget_map.get(kwargs["reasoning_effort"], 8192)
        
        data = {
            "contents": contents,
            "generationConfig": generation_config
        }
        if system_instruction:
            data["systemInstruction"] = system_instruction
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

    def parse_stream_chunk(self, chunk: Dict[str, Any]) -> Optional[str]:
        """解析 Gemini SSE 流式 chunk。

        Gemini 流式格式:
          {"candidates": [{"content": {"parts": [{"text": "..."}]}}]}
        """
        candidates = chunk.get("candidates", [])
        if not candidates:
            return None
        parts = candidates[0].get("content", {}).get("parts", [])
        if parts and "text" in parts[0]:
            return parts[0]["text"]
        return None
