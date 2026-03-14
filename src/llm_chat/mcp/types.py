from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field
from enum import Enum


class TransportType(str, Enum):
    STDIO = "stdio"
    SSE = "sse"
    HTTP = "http"


class MCPServerConfig(BaseModel):
    name: str = Field(..., description="MCP 服务器名称")
    transport: TransportType = Field(default=TransportType.STDIO, description="传输方式")
    command: Optional[str] = Field(None, description="stdio 模式下的启动命令")
    args: List[str] = Field(default_factory=list, description="命令参数")
    env: Dict[str, str] = Field(default_factory=dict, description="环境变量")
    url: Optional[str] = Field(None, description="SSE/HTTP 模式下的服务器 URL")
    enabled: bool = Field(default=True, description="是否启用")
    description: Optional[str] = Field(None, description="服务器描述")
    
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
    input_schema: Dict[str, Any] = Field(default_factory=dict, description="输入参数 schema")
    server_name: str = Field(..., description="所属服务器名称")
    
    def to_openai_tool(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description or "",
                "parameters": self.input_schema
            }
        }
    
    def to_anthropic_tool(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description or "",
            "input_schema": self.input_schema
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
