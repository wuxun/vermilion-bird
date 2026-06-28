# Re-export from ember-core (canonical source)
# 保留此文件以维持 config/__init__.py 的无 MCP SDK 导入路径
from ember_core.mcp.types import (
    TransportType,
    MCPServerConfig,
    MCPServerInfo,
    MCPServerStatus,
    MCPTool,
    MCPToolParameter,
    MCPResource,
    MCPConfig,
)

__all__ = [
    "TransportType",
    "MCPServerConfig",
    "MCPServerInfo",
    "MCPServerStatus",
    "MCPTool",
    "MCPToolParameter",
    "MCPResource",
    "MCPConfig",
]
