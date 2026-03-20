# MCP 工具集成

## 概述

MCP (Model Context Protocol) 客户端实现，支持连接外部工具服务器（stdio/SSE）。

## 结构

```
mcp/
├── __init__.py      # 公共导出
├── types.py         # 类型定义（MCPServerConfig, MCPTool 等）
├── config.py        # MCPConfig 配置类
├── client.py        # MCPClient 单服务器客户端
└── manager.py       # MCPManager 多服务器管理器
```

## 快速定位

| 任务 | 文件 | 说明 |
|------|------|------|
| 添加服务器配置 | `config.py` | MCPServerConfig |
| 连接服务器 | `manager.py` | MCPManager.connect_server() |
| 调用工具 | `manager.py` | MCPManager.call_tool() |
| 获取工具列表 | `manager.py` | MCPManager.get_tools_for_openai() |

## 核心类型

```python
class TransportType(Enum):
    STDIO = "stdio"  # 本地进程
    SSE = "sse"      # 远程 HTTP

@dataclass
class MCPServerConfig:
    name: str
    transport: TransportType
    command: Optional[str]      # stdio 模式
    args: Optional[List[str]]   # stdio 模式
    url: Optional[str]          # sse 模式
    env: Optional[Dict[str, str]]
    enabled: bool
```

## 使用示例

```python
from llm_chat.mcp import MCPManager, MCPServerConfig

manager = MCPManager()

# 添加服务器
config = MCPServerConfig(
    name="weather",
    transport="stdio",
    command="npx",
    args=["-y", "@modelcontextprotocol/server-weather"],
    enabled=True
)
manager.add_server(config)

# 连接
manager.connect_server("weather").result()

# 获取工具列表（OpenAI 格式）
tools = manager.get_tools_for_openai()

# 调用工具
result = manager.call_tool("get_weather", {"city": "Beijing"}).result()
```

## 配置示例

```yaml
mcp:
  servers:
    - name: "weather"
      transport: "stdio"
      command: "npx"
      args: ["-y", "@modelcontextprotocol/server-weather"]
      enabled: true
    
    - name: "brave-search"
      transport: "stdio"
      command: "npx"
      args: ["-y", "@modelcontextprotocol/server-brave-search"]
      env:
        BRAVE_API_KEY: "your-key"
      enabled: true
    
    - name: "remote"
      transport: "sse"
      url: "http://localhost:8080/sse"
      enabled: true
```

## 常用 MCP 服务器

| 服务器 | 安装命令 |
|--------|----------|
| weather | `npx -y @modelcontextprotocol/server-weather` |
| brave-search | `npx -y @modelcontextprotocol/server-brave-search` |
| filesystem | `npx -y @modelcontextprotocol/server-filesystem` |
| sqlite | `npx -y @modelcontextprotocol/server-sqlite` |

## 约定

- 所有 MCP 操作返回 `Future`（异步）
- 工具调用失败抛出 `MCPClientError`
- 服务器状态通过 `MCPServerStatus` 枚举管理

## 注意事项

- MCP 服务器需要 Node.js 环境（npx 命令）
- SSE 模式适用于远程服务
- 敏感信息（API Key）通过 `env` 配置传递
