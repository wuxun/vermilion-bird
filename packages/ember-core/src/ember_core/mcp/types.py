"""MCP type definitions — pure Pydantic, zero MCP SDK dependency."""

from __future__ import annotations

from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field
from enum import Enum


class TransportType(str, Enum):
    STDIO = "stdio"
    SSE = "sse"
    HTTP = "http"


class MCPServerConfig(BaseModel):
    """Configuration for one MCP server."""

    name: str = Field(..., description="MCP 服务器名称")
    transport: TransportType = Field(
        default=TransportType.STDIO, description="传输方式"
    )
    command: Optional[str] = Field(None, description="stdio 模式下的启动命令")
    args: List[str] = Field(default_factory=list, description="命令参数")
    env: Dict[str, str] = Field(default_factory=dict, description="环境变量")
    url: Optional[str] = Field(None, description="SSE/HTTP 模式下的服务器 URL")
    enabled: bool = Field(default=True, description="是否启用")
    description: Optional[str] = Field(None, description="服务器描述")
    http_proxy: Optional[str] = Field(None, description="HTTP 代理地址")
    https_proxy: Optional[str] = Field(None, description="HTTPS 代理地址")
    timeout: int = Field(
        default=60,
        description="连接超时时间(秒)，首次 npx 下载可能需要更长时间",
    )

    class Config:
        use_enum_values = True


class MCPToolParameter(BaseModel):
    type: str = Field(default="string", description="参数类型")
    description: Optional[str] = Field(None, description="参数描述")
    required: bool = Field(default=False, description="是否必需")
    enum: Optional[List[str]] = Field(None, description="枚举值")
    default: Optional[Any] = Field(None, description="默认值")


class MCPTool(BaseModel):
    name: str = Field(..., description="工具名称")
    description: Optional[str] = Field(None, description="工具描述")
    input_schema: Dict[str, Any] = Field(
        default_factory=dict, description="输入参数 schema"
    )
    server_name: str = Field(..., description="所属服务器名称")

    def to_openai_tool(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description or "",
                "parameters": self.input_schema,
            },
        }

    def to_anthropic_tool(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description or "",
            "input_schema": self.input_schema,
        }


class MCPResource(BaseModel):
    uri: str = Field(..., description="资源 URI")
    name: str = Field(..., description="资源名称")
    description: Optional[str] = Field(None, description="资源描述")
    mime_type: Optional[str] = Field(None, description="MIME 类型")
    server_name: str = Field(..., description="所属服务器名称")


class MCPServerStatus(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


class MCPServerInfo(BaseModel):
    config: MCPServerConfig
    status: MCPServerStatus = Field(default=MCPServerStatus.DISCONNECTED)
    tools: List[MCPTool] = Field(default_factory=list)
    resources: List[MCPResource] = Field(default_factory=list)
    error_message: Optional[str] = Field(None)


class MCPConfig(BaseModel):
    """Multi-server MCP configuration."""

    servers: List[MCPServerConfig] = Field(
        default_factory=list, description="MCP 服务器配置列表"
    )

    def get_server(self, name: str) -> Optional[MCPServerConfig]:
        for server in self.servers:
            if server.name == name:
                return server
        return None

    def add_server(self, server: MCPServerConfig) -> None:
        existing = self.get_server(server.name)
        if existing:
            self.servers.remove(existing)
        self.servers.append(server)

    def remove_server(self, name: str) -> bool:
        server = self.get_server(name)
        if server:
            self.servers.remove(server)
            return True
        return False

    def get_enabled_servers(self) -> List[MCPServerConfig]:
        return [s for s in self.servers if s.enabled]

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MCPConfig":
        if not data:
            return cls()
        servers_data = data.get("servers", [])
        servers = [
            MCPServerConfig(**s) for s in servers_data if isinstance(s, dict)
        ]
        return cls(servers=servers)

    def to_dict(self) -> Dict[str, Any]:
        return {"servers": [s.model_dump() for s in self.servers]}
