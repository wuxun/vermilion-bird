"""Frontend factory with optional adapters loaded on demand."""

from .base import BaseFrontend, ConversationContext, Message, MessageType


def get_frontend(frontend_type: str, **kwargs):
    """Create a frontend without importing optional GUI dependencies eagerly."""
    frontend_lower = frontend_type.lower()
    if frontend_lower == "cli":
        from .cli import CLIFrontend

        frontend_class = CLIFrontend
    elif frontend_lower == "gui":
        try:
            from .gui import GUIFrontend
        except ImportError as exc:
            raise RuntimeError(
                "GUI dependencies are not installed. "
                "Install with: pip install 'vermilion-bird[gui]'"
            ) from exc
        frontend_class = GUIFrontend
    else:
        raise ValueError(f"不支持的前端类型: {frontend_type}，支持的前端: ['cli', 'gui']")
    return frontend_class(**kwargs)


def __getattr__(name: str):
    """Preserve legacy `from llm_chat.frontends import ...Frontend` imports."""
    if name == "CLIFrontend":
        from .cli import CLIFrontend

        return CLIFrontend
    if name == "GUIFrontend":
        from .gui import GUIFrontend

        return GUIFrontend
    raise AttributeError(name)


__all__ = [
    "BaseFrontend",
    "Message",
    "ConversationContext",
    "MessageType",
    "CLIFrontend",
    "GUIFrontend",
    "get_frontend",
]
