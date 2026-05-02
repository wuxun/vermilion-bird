"""错误处理与重试机制。

统一的错误处理类、重试装饰器和异常基类。
"""

import logging
import signal as signal_module
import time
from functools import wraps
from typing import Any, Callable, Type, List, Optional


logger = logging.getLogger(__name__)


# 异常基类
class FeishuError(Exception):
    """飞书集成的基异常类。

    所有飞书相关的异常都应继承此类，用于统一异常处理。
    """

    pass


class FeishuTimeoutError(FeishuError):
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
    logger_instance: Optional[Any] = None,
    silent: bool = False,
    on_error: Optional[Callable[[Exception], None]] = None,
    max_retries: int = 3,
    backoff: bool = True,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
):
    """错误处理装饰器工厂函数。

    Args:
        func: 要装饰的函数
        logger_instance: 日志记录器（可选）
        silent: 是否静默处理错误
        on_error: 错误回调函数
        max_retries: 最大重试次数
        backoff: 是否使用指数退避策略
        initial_delay: 初始延迟（秒）
        backoff_factor: 退避因子

    Returns:
        装饰后的函数，带有重试和错误处理机制
    """
    if logger_instance is None:
        logger_instance = logging.getLogger(__name__)

    def wrapper(*args, **kwargs):
        current_attempt = 0
        last_exception = None

        while current_attempt < max_retries:
            try:
                return func(*args, **kwargs)
            except FeishuTimeoutError as e:
                last_exception = e
                if not silent:
                    logger_instance.warning(f"TimeoutError in {func.__name__}: {e}")

                if on_error:
                    on_error(e)

                if backoff and current_attempt > 0:
                    delay = initial_delay * (backoff_factor**current_attempt)
                    logger_instance.info(f"Retrying {func.__name__} in {delay:.2f}s...")
                    time.sleep(delay)

                current_attempt += 1
            except AuthenticationError as e:
                last_exception = e
                if not silent:
                    logger_instance.error(
                        f"AuthenticationError in {func.__name__}: {e}"
                    )

                if on_error:
                    on_error(e)

                if current_attempt < max_retries:
                    logger_instance.warning(
                        f"Authentication failed, will retry... {current_attempt}/{max_retries}"
                    )
                    if backoff:
                        delay = initial_delay * (backoff_factor**current_attempt)
                        logger_instance.info(
                            f"Backing off {delay:.2f}s before retry..."
                        )
                        time.sleep(delay)
                    current_attempt += 1
                else:
                    raise
            except APIError as e:
                last_exception = e
                if not silent:
                    logger_instance.critical(f"APIError in {func.__name__}: {e}")

                if on_error:
                    on_error(e)

                # API 错误不重试
                logger_instance.error(f"API error, no retry: {func.__name__} - {e}")
                raise
            except ConfigurationError as e:
                last_exception = e
                if not silent:
                    logger_instance.error(f"ConfigurationError in {func.__name__}: {e}")

                if on_error:
                    on_error(e)
                raise
            except ValidationError as e:
                last_exception = e
                if not silent:
                    logger_instance.error(f"ValidationError in {func.__name__}: {e}")

                if on_error:
                    on_error(e)
                raise
            except Exception as e:
                last_exception = e
                if not silent:
                    logger_instance.critical(
                        f"Unexpected error in {func.__name__}: {e}"
                    )

                if on_error:
                    on_error(e)
                raise

        # 如果所有重试都失败，抛出最后一个异常
        if last_exception:
            raise last_exception

    return wrapper


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
                    FeishuTimeoutError,
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

            # 如果所有重试都失败，抛出最后一个异常
            if last_exception:
                raise last_exception

        return wrapper

    return decorator


# 超时处理器
def timeout_handler(timeout_seconds: int = 30):
    """超时处理函数。

    Args:
        timeout_seconds: 超时时间（秒）

    Returns:
        装饰器工厂函数，在超时时抛出 FeishuTimeoutError

    注意: signal.SIGALRM 在 Windows 上不可用，此装饰器仅适用于 Unix-like 系统。
    """

    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            def _timeout_handler(signum, frame):
                raise FeishuTimeoutError(
                    f"{func.__name__} timed out after {timeout_seconds}s"
                )

            # 设置信号处理器
            old_handler = signal_module.signal(signal_module.SIGALRM, _timeout_handler)
            signal_module.alarm(timeout_seconds)

            try:
                result = func(*args, **kwargs)
                # 成功执行后取消闹钟
                signal_module.alarm(0)
                return result
            finally:
                # 恢复旧的信号处理器
                signal_module.signal(signal_module.SIGALRM, old_handler)

        return wrapper

    return decorator


# 使用示例
if __name__ == "__main__":
    # 示例：带重试和错误处理的函数
    def call_feishu_api(user_id: str) -> str:
        """模拟飞书 API 调用，可能超时"""
        time.sleep(2)  # 模拟延迟
        return f"Success for user {user_id}"

    # 使用 error_handler 包装函数
    wrapped_api = error_handler(call_feishu_api, max_retries=3, backoff=True)

    # 调用
    try:
        result = wrapped_api("user_123")
        print(f"Result: {result}")
    except FeishuTimeoutError as e:
        print(f"Caught timeout: {e}")
    except Exception as e:
        print(f"Caught error: {e}")
