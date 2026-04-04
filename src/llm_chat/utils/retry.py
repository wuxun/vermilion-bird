"""重试装饰器模块

提供通用的重试装饰器，支持多种重试策略。
"""

import time
import logging
from typing import Callable, Type, Tuple, Optional, Any
from functools import wraps

logger = logging.getLogger(__name__)


def retry(
    max_retries: int = 3,
    retry_delay: float = 1.0,
    backoff_factor: float = 2.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    on_retry: Optional[Callable[[int, Exception], None]] = None,
):
    """重试装饰器

    Args:
        max_retries: 最大重试次数
        retry_delay: 初始重试延迟（秒）
        backoff_factor: 退避因子，每次重试延迟乘以该因子
        exceptions: 需要重试的异常类型元组
        on_retry: 重试时的回调函数，参数为 (尝试次数, 异常)

    Returns:
        装饰器函数
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            last_exception = None
            current_delay = retry_delay

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e

                    if attempt >= max_retries:
                        logger.error(f"函数 {func.__name__} 执行失败，重试耗尽: {e}")
                        raise

                    if on_retry:
                        on_retry(attempt + 1, e)
                    else:
                        logger.warning(
                            f"函数 {func.__name__} 执行失败，{current_delay}秒后重试 "
                            f"({attempt + 1}/{max_retries}): {e}"
                        )

                    time.sleep(current_delay)
                    current_delay *= backoff_factor

            # 理论上不会执行到这里，但为了类型安全
            raise last_exception

        return wrapper

    return decorator


def async_retry(
    max_retries: int = 3,
    retry_delay: float = 1.0,
    backoff_factor: float = 2.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    on_retry: Optional[Callable[[int, Exception], None]] = None,
):
    """异步重试装饰器

    Args:
        max_retries: 最大重试次数
        retry_delay: 初始重试延迟（秒）
        backoff_factor: 退避因子，每次重试延迟乘以该因子
        exceptions: 需要重试的异常类型元组
        on_retry: 重试时的回调函数，参数为 (尝试次数, 异常)

    Returns:
        装饰器函数
    """
    import asyncio

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            last_exception = None
            current_delay = retry_delay

            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e

                    if attempt >= max_retries:
                        logger.error(
                            f"异步函数 {func.__name__} 执行失败，重试耗尽: {e}"
                        )
                        raise

                    if on_retry:
                        on_retry(attempt + 1, e)
                    else:
                        logger.warning(
                            f"异步函数 {func.__name__} 执行失败，{current_delay}秒后重试 "
                            f"({attempt + 1}/{max_retries}): {e}"
                        )

                    await asyncio.sleep(current_delay)
                    current_delay *= backoff_factor

            # 理论上不会执行到这里，但为了类型安全
            raise last_exception

        return wrapper

    return decorator
