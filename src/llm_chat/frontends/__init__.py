from .base import BaseFrontend, Message, ConversationContext, MessageType
from .cli import CLIFrontend
from .gui import GUIFrontend

FRONTEND_MAP = {
    "cli": CLIFrontend,
    "gui": GUIFrontend,
}


def get_frontend(frontend_type: str, **kwargs):
    """获取前端实例
    
    Args:
        frontend_type: 前端类型 (cli, gui)
        **kwargs: 传递给前端构造函数的参数
        
    Returns:
        前端实例
    """
    frontend_lower = frontend_type.lower()
    if frontend_lower not in FRONTEND_MAP:
        raise ValueError(f"不支持的前端类型: {frontend_type}，支持的前端: {list(FRONTEND_MAP.keys())}")
    
    frontend_class = FRONTEND_MAP[frontend_lower]
    return frontend_class(**kwargs)


__all__ = [
    "BaseFrontend",
    "Message",
    "ConversationContext",
    "MessageType",
    "CLIFrontend",
    "GUIFrontend",
    "get_frontend",
]
