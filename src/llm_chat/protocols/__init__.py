from typing import Optional
from .base import BaseProtocol
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
    """获取协议适配器
    
    Args:
        protocol: 协议类型 (openai, anthropic, gemini)
        base_url: API 基础 URL
        api_key: API 密钥
        model: 模型名称
        timeout: 超时时间
        max_retries: 最大重试次数
        
    Returns:
        协议适配器实例
    """
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


__all__ = ["BaseProtocol", "OpenAIProtocol", "AnthropicProtocol", "GeminiProtocol", "get_protocol"]
