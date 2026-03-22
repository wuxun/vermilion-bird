"""错误处理与重试机制。

统一的错误处理类、重试装饰器和异常基类。
"""

import time
from functools import wraps
from typing import Any, Callable, TypeVar
import logging

# 导入已存在的异常基类
from src.llm_chat.frontends.feishu import FeishuError, FeishuAdapterError


logger = logging.getLogger(__name__)


# 异常基类
class FeishuError(Exception):
    """飞书集成的基异常类。

    所有飞书相关的异常都应继承此类，用于统一异常处理。
    """

    pass


class TimeoutError(FeishuError):
    """超时错误。"""

    pass


class AuthenticationError(FeishuError):
    """认证错误。"""

    pass


class APIError(FeishuError):
    """API 调用错误。"""

    pass


class ConfigurationError(FeishuError):
    """配置错误。"""

    pass


class ValidationError(FeishuError):
    """验证错误。"""

    pass


# 错误处理器
def error_handler(
    func: Callable,
    logger: Any = None,
    silent: bool = False,
    on_error: Callable[[Type[Exception], Exception]] = None,
    max_retries: int = 3,
    backoff: bool = True,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
):
    """错误处理装饰器工厂函数。

    Args:
        func: 要装饰的函数
        logger: 日志记录器（可选）
        silent: 是否静默处理错误
        on_error: 错误回调函数列表
        max_retries: 最大重试次数
        backoff: 是否使用指数退避策略
        initial_delay: 初始延迟（秒）
        backoff_factor: 退避因子

    Returns:
        装饰后的函数，带有重试和错误处理机制
    """
    if logger is None:
        logger = logging.getLogger(__name__)

    def wrapper(*args, **kwargs):
        current_attempt = 0
        last_exception = None

        while current_attempt < max_retries:
            try:
                return func(*args, **kwargs)
            except TimeoutError as e:
                last_exception = e
                if not silent and logger:
                    logger.warning(f"TimeoutError in {func.__name__}: {e}")

                if on_error:
                    on_error(
                        e,
                        *args,
                        **kwargs,
                        last_exception=current_exception,
                        current_attempt=current_attempt + 1,
                    )

                if backoff and current_attempt > 0:
                    delay = initial_delay * (backoff_factor**current_attempt)
                    logger.info(f"Retrying {func.__name__} in {delay:.2f}s...")
                    time.sleep(delay)

                current_attempt += 1
            except AuthenticationError as e:
                last_exception = e
                if not silent and logger:
                    logger.error(f"AuthenticationError in {func.__name__}: {e}")

                if on_error:
                    on_error(
                        e,
                        *args,
                        **kwargs,
                        last_exception=current_exception,
                        current_attempt=current_attempt + 1,
                    )

                if current_attempt < max_retries:
                    logger.warning(
                        f"Authentication failed, will retry... {current_attempt}/{max_retries}"
                    )
                    if backoff:
                        delay = initial_delay * (backoff_factor**current_attempt)
                        logger.info(f"Backing off {delay:.2f}s before retry...")
                        time.sleep(delay)
                    current_attempt += 1
            except APIError as e:
                last_exception = e
                if not silent and logger:
                    logger.critical(f"APIError in {func.__name__}: {e}")

                if on_error:
                    on_error(
                        e,
                        *args,
                        **kwargs,
                        last_exception=current_exception,
                        current_attempt=current_attempt + 1,
                    )

                # API 错误不重试
                logger.error(f"API error, no retry: {func.__name__} - {e}")
                if on_error:
                    on_error(
                        e,
                        *args,
                        **kwargs,
                        last_exception=current_exception,
                        current_attempt=current_attempt + 1,
                    )
            except ConfigurationError as e:
                last_exception = e
                if not silent and logger:
                    logger.error(f"ConfigurationError in {func.__name__}: {e}")

                if on_error:
                    on_error(
                        e,
                        *args,
                        **kwargs,
                        last_exception=current_exception,
                        current_attempt=current_attempt + 1,
                    )
            except ValidationError as e:
                last_exception = e
                if not silent and logger:
                    logger.error(f"ValidationError in {func.__name__}: {e}")

                if on_error:
                    on_error(
                        e,
                        *args,
                        **kwargs,
                        last_exception=current_exception,
                        current_attempt=curent_attempt + 1,
                    )
            except Exception as e:
                last_exception = e
                if not silent and logger:
                    logger.critical(f"Unexpected error in {func.__name__}: {e}")

                if on_error:
                    on_error(
                        e,
                        *args,
                        **kwargs,
                        last_exception=current_exception,
                        current_attempt=current_attempt + 1,
                    )

        return wrapper(*args, **kwargs)


# 便捷装饰器
def retry_on_exception(max_retries: int = 3, initial_delay: float = 1.0):
    """重试装饰器，适用于超时和临时性错误。

    Args:
        max_retries: 最大重试次数
        initial_delay: 初始延迟（秒）

    Returns:
        装饰器
    """

    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            current_attempt = 0
            last_exception = None

            while current_attempt < max_retries:
                try:
                    return func(*args, **kwargs)
                except (
                    TimeoutError,
                    APIError,
                    AuthenticationError,
                    ConfigurationError,
                ) as e:
                    last_exception = e
                    logger.warning(
                        f"{func.__name__} failed attempt {current_attempt + 1}/{max_retries}: {e}"
                    )

                    if current_attempt < max_retries - 1:
                        delay = initial_delay * (2**current_attempt)
                        logger.info(f"Retrying {func.__name__} in {delay:.2f}s...")
                        time.sleep(delay)

                    current_attempt += 1
                except ValidationError as e:
                    # 验证错误不重试
                    logger.error(f"{func.__name__} failed with validation error: {e}")
                    raise
                except Exception as e:
                    logger.critical(
                        f"{func.__name__} failed with unexpected error: {e}"
                    )
                    raise
            return wrapper(*args, **kwargs)


# 超时处理器
def timeout_handler(timeout_seconds: int = 30):
    """超时处理函数。

    Args:
        timeout_seconds: 超时时间（秒）

    Returns:
        装饰器工厂函数，在超时时抛出 TimeoutError
    """

    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            signal.signal(signal.SIGALRM, timeout_handler)

            def _timeout_handler(signum, frame):
                signal.alarm(timeout_seconds)
                raise TimeoutError(
                    f"{func.__name__} timed out after {timeout_seconds}s"
                )

            def inner(*inner_args, **inner_kwargs):
                signal.signal(signal.SIGALRM, _timeout_handler)
                return func(*inner_args, **inner_kwargs)

            return inner(*args, **kwargs)

        return wrapper(*args, **kwargs)


# 使用示例
if __name__ == "__main__":
    # 示例：带重试和错误处理的函数
    @error_handler(max_retries=3, backoff=True)
    def call_feishu_api(user_id: str) -> str:
        """模拟飞书 API 调用，可能超时"""
        time.sleep(2)  # 模拟延迟
        return f"Success for user {user_id}"

    # 调用
    try:
        result = call_feishu_api("user_123")
        print(f"Result: {result}")
    except TimeoutError as e:
        print(f"Caught timeout: {e}")
    except Exception as e:
        print(f"Caught error: {e}")
