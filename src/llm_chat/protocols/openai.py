import json
import logging
import uuid
from typing import Dict, Any, List, Optional
from .base import BaseProtocol, ToolCall

logger = logging.getLogger(__name__)


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
        }
        
        if kwargs.get("temperature") is not None:
            data["temperature"] = kwargs["temperature"]
        
        # max_tokens 始终发送默认值，避免依赖 API 提供方不确定的默认值
        # 4096 覆盖绝大多数场景；调用方可通过传参覆盖
        data["max_tokens"] = kwargs.get("max_tokens", 8192)
        
        if kwargs.get("top_p") is not None:
            data["top_p"] = kwargs["top_p"]
        
        if kwargs.get("stream"):
            data["stream"] = kwargs["stream"]
        
        if kwargs.get("reasoning_effort"):
            data["reasoning_effort"] = kwargs["reasoning_effort"]
        
        return data
    
    def parse_chat_response(self, response: Dict[str, Any]) -> str:
        choice = response["choices"][0]
        message = choice["message"]
        content = message.get("content") or ""
        reason = choice.get("finish_reason", "unknown")
        refusal = message.get("refusal", "")
        if not content or refusal:
            logger.warning(
                f"LLM 返回空内容或拒绝: finish_reason={reason}, "
                f"refusal={refusal!r}, content={content!r}"
            )
        return content.strip()
    
    def get_generate_url(self) -> str:
        return f"{self.base_url}/completions"
    
    def build_generate_request(self, prompt: str, **kwargs) -> Dict[str, Any]:
        data = {
            "model": self.model,
            "prompt": prompt,
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens", 8192),
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

        # DeepSeek R1 / OpenAI o1 等推理模型的思考内容，必须传回
        if message.get("reasoning_content"):
            msg["reasoning_content"] = message["reasoning_content"]

        if message.get("tool_calls"):
            msg["tool_calls"] = message["tool_calls"]

        return msg

    @staticmethod
    def parse_stream_reasoning_content(chunk: Dict[str, Any]) -> Optional[str]:
        """提取流式 chunk 中的 reasoning_content (DeepSeek R1 / OpenAI o1)。"""
        choices = chunk.get("choices", [])
        if not choices:
            return None
        delta = choices[0].get("delta", {})
        return delta.get("reasoning_content")

    def parse_stream_chunk(self, chunk: Dict[str, Any]) -> Optional[str]:
        choices = chunk.get("choices", [])
        if not choices:
            return None

        delta = choices[0].get("delta", {})
        content = delta.get("content")

        return content if content else None
