"""MCP 配置 — 从 config/mcp_config 重新导出，保持向后兼容。"""

from llm_chat.config.mcp_config import MCPConfig, MCPServerConfig

__all__ = ["MCPConfig", "MCPServerConfig"]
