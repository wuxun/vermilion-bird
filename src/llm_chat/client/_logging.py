"""请求日志格式化（模块级函数，无 self 依赖）"""

import logging
from typing import List, Dict, Any

from llm_chat.utils.token_counter import count_messages_tokens, get_context_limit

logger = logging.getLogger(__name__)


def log_request_details(
    url: str,
    data: Dict[str, Any],
    messages: List[Dict[str, Any]],
    kwargs: Dict[str, Any],
) -> None:
    """打印请求详情日志"""
    logger.info(f"{'=' * 60}")
    logger.info(f"发送请求到: {url}")
    logger.info(f"模型: {data.get('model', 'unknown')}")

    if kwargs.get("temperature") is not None:
        logger.info(f"温度: {kwargs['temperature']}")
    if kwargs.get("reasoning_effort"):
        logger.info(f"推理深度: {kwargs['reasoning_effort']}")
    if kwargs.get("max_tokens"):
        logger.info(f"最大Token: {kwargs['max_tokens']}")

    logger.info(f"消息数量: {len(messages)}")

    total_tokens = count_messages_tokens(messages)
    model_name = data.get("model", "unknown")
    context_limit = get_context_limit(model_name)
    if context_limit:
        logger.info(
            f"请求总token数: {total_tokens}, 模型上下文窗口上限: {context_limit}, "
            f"使用率: {int(total_tokens / context_limit * 100)}%"
        )
    else:
        logger.info(f"请求总token数: {total_tokens}")

    for i, msg in enumerate(messages):
        role = msg.get("role", "unknown")
        content = msg.get("content", "")

        if role == "system":
            preview = (
                content[:200] + "..."
                if content is not None and len(content) > 200
                else content
            )
            logger.info(f"  [{i}] system: {preview}")
        elif role == "user":
            preview = (
                content[:100] + "..."
                if content is not None and len(content) > 100
                else content
            )
            logger.info(f"  [{i}] user: {preview}")
        elif role == "assistant":
            preview = (
                content[:100] + "..."
                if content is not None and len(content) > 100
                else content
            )
            logger.info(f"  [{i}] assistant: {preview}")
        else:
            logger.info(f"  [{i}] {role}: (content length: {len(content)})")

    logger.info(f"{'=' * 60}")
