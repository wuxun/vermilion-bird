"""MCP 类型定义 — 从 config/mcp_config 重新导出，保持向后兼容。"""

from llm_chat.config.mcp_config import (
    TransportType,
    MCPServerConfig,
    MCPServerInfo,
    MCPServerStatus,
    MCPTool,
    MCPToolParameter,
    MCPResource,
)

__all__ = [
    "TransportType",
    "MCPServerConfig",
    "MCPServerInfo",
    "MCPServerStatus",
    "MCPTool",
    "MCPToolParameter",
    "MCPResource",
]
