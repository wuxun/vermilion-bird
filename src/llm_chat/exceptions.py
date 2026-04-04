"""统一异常处理模块

定义项目中统一的异常基类和子类，便于统一错误处理和追踪。
"""

from typing import Optional, Dict, Any


class VermilionBirdError(Exception):
    """项目异常基类

    所有项目自定义异常的基类，便于统一捕获和处理。
    """

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        """初始化异常

        Args:
            message: 异常消息
            details: 异常详情字典，包含更多上下文信息
        """
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        """将异常转换为字典格式

        Returns:
            包含异常信息的字典
        """
        return {
            "type": self.__class__.__name__,
            "message": self.message,
            "details": self.details,
        }

    def __str__(self) -> str:
        """字符串表示"""
        if self.details:
            return f"{self.message} (details: {self.details})"
        return self.message


class ConfigError(VermilionBirdError):
    """配置错误

    当配置无效或缺失时抛出。
    """

    pass


class ProtocolError(VermilionBirdError):
    """协议错误

    当 LLM 协议处理出错时抛出。
    """

    pass


class LLMError(VermilionBirdError):
    """LLM API 错误

    当 LLM API 调用失败时抛出。
    """

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        """初始化 LLM API 错误

        Args:
            message: 异常消息
            status_code: HTTP 状态码（如果有）
            details: 异常详情字典
        """
        super().__init__(message, details)
        self.status_code = status_code


class StorageError(VermilionBirdError):
    """存储错误

    当数据库或文件存储操作失败时抛出。
    """

    pass


class MCPServerError(VermilionBirdError):
    """MCP 服务器错误

    当 MCP 服务器操作失败时抛出。
    """

    pass


class SkillError(VermilionBirdError):
    """技能错误

    当技能执行失败时抛出。
    """

    pass


class FeishuError(VermilionBirdError):
    """飞书错误

    当飞书 API 调用失败时抛出。
    """

    def __init__(
        self,
        message: str,
        error_code: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        """初始化飞书错误

        Args:
            message: 异常消息
            error_code: 飞书 API 错误码（如果有）
            details: 异常详情字典
        """
        super().__init__(message, details)
        self.error_code = error_code


class SchedulerError(VermilionBirdError):
    """调度器错误

    当调度器操作失败时抛出。
    """

    pass


class ValidationError(VermilionBirdError):
    """验证错误

    当数据验证失败时抛出。
    """

    pass


class TimeoutError(VermilionBirdError):
    """超时错误

    当操作超时时抛出。
    """

    pass


class AuthenticationError(VermilionBirdError):
    """认证错误

    当认证失败时抛出。
    """

    pass


class AuthorizationError(VermilionBirdError):
    """授权错误

    当权限不足时抛出。
    """

    pass
