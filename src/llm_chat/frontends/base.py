from abc import ABC, abstractmethod
from typing import Callable, Optional, Any
from dataclasses import dataclass
from enum import Enum


class MessageType(Enum):
    TEXT = "text"
    IMAGE = "image"
    FILE = "file"


@dataclass
class Message:
    content: str
    role: str
    msg_type: MessageType = MessageType.TEXT
    metadata: Optional[dict] = None


@dataclass
class ConversationContext:
    conversation_id: str
    user_id: Optional[str] = None
    channel_id: Optional[str] = None
    metadata: Optional[dict] = None


class BaseFrontend(ABC):
    """前端适配器基类
    
    所有前端（CLI、GUI、Web、机器人等）都需要继承此类并实现相应方法。
    """
    
    def __init__(self, name: str):
        self.name = name
        self._on_message_callback: Optional[Callable] = None
        self._on_clear_callback: Optional[Callable] = None
        self._on_exit_callback: Optional[Callable] = None
    
    def set_on_message(self, callback: Callable[[Message, ConversationContext], None]):
        """设置消息回调"""
        self._on_message_callback = callback
    
    def set_on_clear(self, callback: Callable[[ConversationContext], None]):
        """设置清空对话回调"""
        self._on_clear_callback = callback
    
    def set_on_exit(self, callback: Callable[[], None]):
        """设置退出回调"""
        self._on_exit_callback = callback
    
    @abstractmethod
    def start(self):
        """启动前端"""
        pass
    
    @abstractmethod
    def stop(self):
        """停止前端"""
        pass
    
    @abstractmethod
    def display_message(self, message: Message):
        """显示消息"""
        pass
    
    @abstractmethod
    def display_error(self, error: str):
        """显示错误"""
        pass
    
    @abstractmethod
    def display_info(self, info: str):
        """显示信息"""
        pass
    
    def _handle_message(self, message: Message, context: ConversationContext):
        """处理用户消息"""
        if self._on_message_callback:
            self._on_message_callback(message, context)
    
    def _handle_clear(self, context: ConversationContext):
        """处理清空命令"""
        if self._on_clear_callback:
            self._on_clear_callback(context)
    
    def _handle_exit(self):
        """处理退出命令"""
        if self._on_exit_callback:
            self._on_exit_callback()
