from typing import Optional
from .base import BaseProtocol, ToolCall, ToolCallResult, ToolCallStatus
from .openai import OpenAIProtocol
from .anthropic import AnthropicProtocol
from .gemini import GeminiProtocol


PROTOCOL_MAP = {
    "openai": OpenAIProtocol,
    "anthropic": AnthropicProtocol,
    "gemini": GeminiProtocol,
}


def get_protocol(
    protocol: str,
    base_url: str,
    api_key: Optional[str],
    model: str,
    timeout: int,
    max_retries: int
) -> BaseProtocol:
    protocol_lower = protocol.lower()
    if protocol_lower not in PROTOCOL_MAP:
        raise ValueError(f"不支持的协议类型: {protocol}，支持的协议: {list(PROTOCOL_MAP.keys())}")
    
    protocol_class = PROTOCOL_MAP[protocol_lower]
    return protocol_class(
        base_url=base_url,
        api_key=api_key,
        model=model,
        timeout=timeout,
        max_retries=max_retries
    )


__all__ = [
    "BaseProtocol", 
    "ToolCall", 
    "ToolCallResult", 
    "ToolCallStatus",
    "OpenAIProtocol", 
    "AnthropicProtocol", 
    "GeminiProtocol", 
    "get_protocol"
]
