# Vermilion Bird

一个简单的大模型对话客户端，支持多种 API 协议和 MCP 工具调用。

## 功能特性

- 支持多种大模型 API 协议（OpenAI、Anthropic、Gemini）
- **MCP (Model Context Protocol) 工具支持** - 连接外部 MCP 服务器，- **图形化界面 (PyQt6)** - 提供友好的 GUI 交互
- 配置化模型设置（base URL、模型名称、协议类型等）
- 支持多种配置方式（YAML 文件、环境变量、命令行参数）
- 命令行交互式聊天界面
- 对话历史管理与持久化
- 多轮对话上下文保持
- 工具调用支持（Function Calling / Tool Use）

## 安装

### 使用 Poetry

```bash
poetry install
```

### 使用 pip

```bash
pip install -e .
```

### 依赖

- PyQt6 - GUI 界面
- mcp - MCP 协议支持
- httpx / httpx-sse - HTTP 客户端

## 支持的协议

| 协议 | 适用平台 | 工具调用 |
|------|----------|----------|
| **openai** | OpenAI、Azure OpenAI、Ollama、vLLM、智谱 GLM、通义千问等 | ✅ Function Calling |
| **anthropic** | Claude 系列 | ✅ Tool Use |
| **gemini** | Google Gemini | ✅ Function Declarations |

## 配置

### 方式一：YAML 配置文件

创建 `config.yaml` 文件：

```yaml
llm:
  base_url: "https://api.openai.com/v1"
  model: "gpt-3.5-turbo"
  api_key: "your-api-key"
  timeout: 30
  max_retries: 3
  protocol: "openai"

enable_tools: true

mcp:
  servers:
    - name: "weather"
      transport: "stdio"
      command: "npx"
      args:
        - "-y"
        - "@modelcontextprotocol/server-weather"
      enabled: true
      description: "天气查询服务"
```

#### 不同平台配置示例

```yaml
# OpenAI
llm:
  base_url: "https://api.openai.com/v1"
  model: "gpt-4"
  api_key: "sk-xxx"
  protocol: "openai"

# Azure OpenAI
llm:
  base_url: "https://your-resource.openai.azure.com/openai/deployments/your-deployment"
  model: "gpt-4"
  api_key: "your-azure-key"
  protocol: "openai"

# Ollama 本地模型
llm:
  base_url: "http://localhost:11434/v1"
  model: "llama2"
  protocol: "openai"

# Anthropic Claude
llm:
  base_url: "https://api.anthropic.com/v1"
  model: "claude-3-opus-20240229"
  api_key: "sk-ant-xxx"
  protocol: "anthropic"

# Google Gemini
llm:
  base_url: "https://generativelanguage.googleapis.com/v1beta"
  model: "gemini-pro"
  api_key: "your-google-api-key"
  protocol: "gemini"

# 智谱 GLM（兼容 OpenAI 协议）
llm:
  base_url: "https://open.bigmodel.cn/api/paas/v4"
  model: "glm-4"
  api_key: "your-zhipu-api-key"
  protocol: "openai"
```

#### MCP 服务器配置示例

```yaml
# 天气查询服务
mcp:
  servers:
    - name: "weather"
      transport: "stdio"
      command: "npx"
      args: ["-y", "@modelcontextprotocol/server-weather"]
      enabled: true

# Brave Search 搜索服务
mcp:
  servers:
    - name: "brave-search"
      transport: "stdio"
      command: "npx"
      args: ["-y", "@modelcontextprotocol/server-brave-search"]
      env:
        BRAVE_API_KEY: "your-brave-api-key"
      enabled: true

# 远程 SSE MCP 服务器
mcp:
  servers:
    - name: "remote-server"
      transport: "sse"
      url: "http://localhost:8080/sse"
      enabled: true
```

### 方式二：环境变量

```bash
export LLM_BASE_URL="https://api.openai.com/v1"
export LLM_MODEL="gpt-3.5-turbo"
export LLM_API_KEY="your-api-key"
export LLM_PROTOCOL="openai"
export LLM_TIMEOUT="30"
export LLM_MAX_RETRIES="3"
```

### 方式三：命令行参数

```bash
vermilion-bird --protocol anthropic --model claude-3-opus-20240229 --api-key your-api-key
```

## 使用方法

### 图形界面 (GUI)

```bash
# 启动 GUI
vermilion-bird --gui

# 或使用 --frontend 参数
vermilion-bird --frontend gui
```

#### GUI 功能

- 对话界面 - 发送消息、查看历史
- **MCP Tools 按钮** - 打开 MCP 工具配置界面
  - 添加/编辑/删除 MCP 服务器
  - 连接/断开服务器
  - 查看可用工具列表
- Clear 按钮 - 清空对话历史

### 命令行界面 (CLI)

#### 基本使用

```bash
vermilion-bird
```

#### 使用命令行参数

```bash
# 指定协议和模型
vermilion-bird --protocol anthropic --model claude-3-opus-20240229 --api-key your-api-key

# 使用本地 Ollama 模型
vermilion-bird --base-url http://localhost:11434/v1 --model llama2 --protocol openai

# 指定对话 ID（用于恢复之前的对话）
vermilion-bird --conversation-id conv_1234567890

# 禁用工具调用
vermilion-bird --no-tools
```

#### 交互命令

- 输入消息后按回车发送
- 输入 `exit` 退出程序
- 输入 `clear` 清空对话历史

### Python API

#### 基本使用

```python
from llm_chat.client import LLMClient
from llm_chat.config import Config

config = Config()

client = LLMClient(config)

response = client.chat("Hello, how are you?")
print(response)
```

#### 使用工具调用

```python
from llm_chat.client import LLMClient
from llm_chat.config import Config
from llm_chat.mcp import MCPManager, MCPServerConfig

config = Config()

# 配置 MCP 服务器
mcp_config = MCPServerConfig(
    name="weather",
    transport="stdio",
    command="npx",
    args=["-y", "@modelcontextprotocol/server-weather"],
    enabled=True
)

manager = MCPManager()
manager.add_server(mcp_config)
manager.connect_server("weather").result()

client = LLMClient(config)

# 设置工具执行器
client.set_tool_executor(lambda name, args: manager.call_tool(name, args).result())

# 获取工具列表
tools = manager.get_tools_for_openai()

# 带工具调用发送消息
response = client.chat_with_tools("What's the weather in Beijing?", tools)
print(response)
```

#### 对话管理

```python
from llm_chat.client import LLMClient
from llm_chat.config import Config
from llm_chat.conversation import Conversation

config = Config()

client = LLMClient(config)

conversation = Conversation(client, "my_conversation")

response1 = conversation.send_message("Hello, how are you?")
print(response1)

response2 = conversation.send_message("What's the weather like today?")
print(response2)

history = conversation.get_history()
print(history)

conversation.clear_history()
```

## 项目结构

```
src/llm_chat/
├── __init__.py
├── cli.py              # 命令行接口
├── client.py           # 大模型客户端
├── config.py           # 配置管理
├── conversation.py     # 对话管理
├── app.py              # 应用核心
├── protocols/          # 协议适配器
│   ├── __init__.py
│   ├── base.py         # 协议基类（含工具调用支持）
│   ├── openai.py       # OpenAI 协议
│   ├── anthropic.py    # Anthropic 协议
│   └── gemini.py       # Gemini 协议
├── frontends/          # 前端适配器
│   ├── __init__.py
│   ├── base.py         # 前端基类
│   ├── cli.py          # CLI 前端
│   ├── gui.py          # PyQt6 GUI 前端
│   └── mcp_dialog.py   # MCP 配置对话框
└── mcp/                # MCP 客户端
    ├── __init__.py
    ├── types.py         # 类型定义
    ├── config.py        # MCP 配置
    ├── client.py        # MCP 客户端封装
    └── manager.py       # MCP 服务器管理器
```

## MCP 工具支持

### 什么是 MCP

MCP (Model Context Protocol) 是 Anthropic 推出的开放协议，用于连接 AI 助手与外部系统。通过 MCP，Vermilion Bird 可以：

- 连接外部工具服务（天气、搜索、数据库等）
- 动态发现和调用工具
- 支持本地 (stdio) 和远程 (SSE) MCP 服务器

### 支持的传输方式

| 传输方式 | 说明 | 适用场景 |
|----------|------|----------|
| **stdio** | 通过标准输入输出通信 | 本地 MCP 服务器 |
| **sse** | Server-Sent Events | 远程 MCP 服务器 |

### 常用 MCP 服务器

| 服务器 | 说明 | 安装命令 |
|--------|------|----------|
| weather | 天气查询 | `npx -y @modelcontextprotocol/server-weather` |
| brave-search | Brave 搜索 | `npx -y @modelcontextprotocol/server-brave-search` |
| filesystem | 文件系统操作 | `npx -y @modelcontextprotocol/server-filesystem` |
| sqlite | SQLite 数据库 | `npx -y @modelcontextprotocol/server-sqlite` |

## 扩展协议

如需添加新的协议支持：

1. 在 `src/llm_chat/protocols/` 下创建新的协议适配器文件
2. 继承 `BaseProtocol` 类并实现所有抽象方法
3. 实现 `supports_tools()` 返回 `True` 以支持工具调用
4. 在 `protocols/__init__.py` 的 `PROTOCOL_MAP` 中注册

```python
# protocols/custom.py
from .base import BaseProtocol, ToolCall

class CustomProtocol(BaseProtocol):
    def supports_tools(self) -> bool:
        return True
    
    def build_chat_request_with_tools(self, messages, tools, **kwargs):
        # 构建带工具的请求
        pass
    
    def parse_tool_calls(self, response) -> list[ToolCall]:
        # 解析工具调用
        pass
    
    # ... 其他方法
```

## 测试

```bash
pytest
```

## 许可证

MIT
