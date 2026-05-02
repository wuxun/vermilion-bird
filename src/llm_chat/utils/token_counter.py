import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

try:
    import tiktoken
    TIKTOKEN_AVAILABLE = True
except ImportError:
    TIKTOKEN_AVAILABLE = False
    tiktoken = None


MODEL_CONTEXT_LIMITS = {
    # OpenAI
    "gpt-4": 8192,
    "gpt-4-32k": 32768,
    "gpt-4-turbo": 128000,
    "gpt-4o": 128000,
    "gpt-4o-mini": 128000,
    "gpt-3.5-turbo": 4096,
    "gpt-3.5-turbo-16k": 16384,
    "o1": 200000,
    "o1-mini": 128000,
    "o3-mini": 200000,
    # Anthropic
    "claude-3-opus": 200000,
    "claude-3-5-sonnet": 200000,
    "claude-3-5-haiku": 200000,
    "claude-3-sonnet": 200000,
    "claude-3-haiku": 200000,
    "claude-2": 100000,
    "claude-instant": 100000,
    # Google
    "gemini-2.5-pro": 1048576,
    "gemini-2.0-flash": 1048576,
    "gemini-1.5-pro": 1048576,
    "gemini-1.5-flash": 1048576,
    "gemini-pro": 32760,
    # DeepSeek
    "deepseek-chat": 1048576,        # DeepSeek V3
    "deepseek-reasoner": 65536,      # DeepSeek R1
    "deepseek-coder": 64000,
    "deepseek-ai/DeepSeek-V3": 1048576,
    "deepseek-ai/DeepSeek-R1": 65536,
    "deepseek-ai/DeepSeek-V4": 1048576,
    # Qwen (通义千问)
    "Qwen/Qwen2.5-72B-Instruct": 32768,
    "Qwen/Qwen2.5-32B-Instruct": 32768,
    "Qwen/Qwen2.5-14B-Instruct": 32768,
    "Qwen/Qwen2.5-7B-Instruct": 32768,
    "qwen-turbo": 1048576,
    "qwen-plus": 131072,
    "qwen-max": 32768,
}

DEFAULT_CONTEXT_LIMIT = 8192


def get_encoding_for_model(model: str) -> Optional[Any]:
    if not TIKTOKEN_AVAILABLE:
        return None
    
    try:
        return tiktoken.encoding_for_model(model)
    except KeyError:
        try:
            return tiktoken.get_encoding("cl100k_base")
        except Exception:
            return None


def count_tokens(text: str, model: str = "gpt-3.5-turbo") -> int:
    if not TIKTOKEN_AVAILABLE:
        return len(text) // 4
    
    encoding = get_encoding_for_model(model)
    if encoding is None:
        return len(text) // 4
    
    try:
        return len(encoding.encode(text))
    except Exception as e:
        logger.warning(f"Token 计算失败: {e}")
        return len(text) // 4


def count_messages_tokens(messages: List[Dict[str, Any]], model: str = "gpt-3.5-turbo") -> int:
    if not messages:
        return 0
    
    if not TIKTOKEN_AVAILABLE:
        total_chars = sum(
            len(str(m.get("content", ""))) + len(str(m.get("role", "")))
            for m in messages
        )
        return total_chars // 4
    
    encoding = get_encoding_for_model(model)
    if encoding is None:
        total_chars = sum(
            len(str(m.get("content", ""))) + len(str(m.get("role", "")))
            for m in messages
        )
        return total_chars // 4
    
    tokens_per_message = 3
    tokens_per_name = 1
    
    total_tokens = 0
    for message in messages:
        total_tokens += tokens_per_message
        for key, value in message.items():
            if value is not None:
                try:
                    total_tokens += len(encoding.encode(str(value)))
                except Exception:
                    total_tokens += len(str(value)) // 4
                if key == "name":
                    total_tokens += tokens_per_name
    total_tokens += 3
    
    return total_tokens


def get_context_limit(model: str) -> int:
    """获取模型的上下文上限 token 数。

    匹配策略：精确匹配 → 最长子串匹配 → 聚类 fallback。
    """
    if not model:
        return DEFAULT_CONTEXT_LIMIT

    model_lower = model.lower()

    # 1. 精确匹配
    if model_lower in MODEL_CONTEXT_LIMITS:
        return MODEL_CONTEXT_LIMITS[model_lower]

    # 2. 最长子串匹配（短 key 可能误匹配，所以按长度降序）
    for key, limit in sorted(
        MODEL_CONTEXT_LIMITS.items(), key=lambda x: -len(x[0])
    ):
        if key.lower() in model_lower:
            return limit

    # 3. 聚类 fallback
    if "gpt" in model_lower or "o1" in model_lower or "o3" in model_lower:
        return 128000
    if "claude" in model_lower:
        return 200000
    if "gemini" in model_lower:
        return 1048576
    if "deepseek" in model_lower:
        return 1048576
    if "qwen" in model_lower:
        return 32768

    return DEFAULT_CONTEXT_LIMIT


def calculate_context_usage(
    messages: List[Dict[str, Any]], 
    model: str = "gpt-3.5-turbo"
) -> Dict[str, Any]:
    used_tokens = count_messages_tokens(messages, model)
    limit = get_context_limit(model)
    usage_percent = (used_tokens / limit) * 100 if limit > 0 else 0
    
    return {
        "used_tokens": used_tokens,
        "limit": limit,
        "usage_percent": round(usage_percent, 1),
        "remaining_tokens": max(0, limit - used_tokens),
        "model": model
    }


def format_context_usage(usage: Dict[str, Any]) -> str:
    used = usage["used_tokens"]
    limit = usage["limit"]
    percent = usage["usage_percent"]
    
    if percent < 50:
        status = "🟢"
    elif percent < 80:
        status = "🟡"
    else:
        status = "🔴"
    
    return f"{status} 上下文: {used:,} / {limit:,} tokens ({percent:.1f}%)"


def format_context_usage_short(usage: Dict[str, Any]) -> str:
    used = usage["used_tokens"]
    limit = usage["limit"]
    percent = usage["usage_percent"]
    
    return f"上下文: {used:,} / {limit:,} tokens ({percent:.1f}%)"
