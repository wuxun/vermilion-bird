# Vermilion Bird

一个简单的大模型对话客户端，支持多种 API 协议和 MCP 工具调用。

## 功能特性

- 支持多种大模型 API 协议（OpenAI、Anthropic、Gemini）
- **MCP (Model Context Protocol) 工具支持** - 连接外部 MCP 服务器
- **飞书（Lark）集成** - 飞书机器人集成，支持实时消息处理、Markdown 渲染、会话历史同步
- **图形化界面 (PyQt6)** - 提供友好的 GUI 交互
- **会话历史管理** - SQLite 持久化存储，支持会话切换、重命名、删除
- 配置化模型设置（base URL、模型名称、协议类型等）
- 支持多种配置方式（YAML 文件、环境变量、命令行参数）
- 命令行交互式聊天界面
- 流式输出支持，实时显示 AI 回复
- Markdown 渲染，代码高亮显示
- 多轮对话上下文保持
- 工具调用支持（Function Calling / Tool Use）
- **多层记忆系统** - 短期/中期/长期记忆，让AI更懂你
- **人格设定** - 自定义AI助手的性格和行为准则
- **Shell 执行技能** - 受控Shell命令执行，白名单限制确保安全

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
- lark-oapi - 飞书开放平台 SDK
- lark-oapi - 飞书 SDK

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

## 飞书（Lark）集成

Vermilion Bird 支持飞书机器人集成，可以接收飞书消息并通过 AI 模型自动回复。

### 飞书配置

在 `config.yaml` 中添加飞书配置：

```yaml
feishu:
  enabled: true
  app_id: "your-feishu-app-id"
  app_secret: "your-feishu-app-secret"
  tenant_key: "your-tenant-key"          # 可选
  encrypt_key: "your-encrypt-key"        # 可选，用于事件加密
  verification_token: "your-token"       # 可选，用于事件验证
```

### 飞书机器人配置步骤

1. **创建飞书应用**
   - 访问 [飞书开放平台](https://open.feishu.cn/)
   - 创建企业自建应用
   - 获取 `App ID` 和 `App Secret`

2. **配置事件订阅**
   - 在应用后台开启「事件订阅」
   - 订阅 `im.message.receive_v1` 事件（接收消息）
   - 配置 Encrypt Key 和 Verification Token（可选）

3. **配置权限**
   - 添加以下权限：
     - `im:message` - 获取与发送消息
     - `im:message:send_as_bot` - 以应用身份发消息

4. **发布应用**
   - 配置完成后发布应用
   - 将应用添加到需要使用的群聊或开启单聊

### 启动飞书服务

```bash
vermilion-bird feishu
```

服务启动后会连接到飞书 WebSocket 服务器，自动接收和处理消息。

### 飞书消息特性

- **Markdown 渲染** - 回复消息以 Markdown 卡片形式渲染，支持代码块、列表等格式
- **会话历史同步** - 飞书对话历史自动保存到本地数据库，可在 GUI 中查看
- **多会话支持** - 支持私聊和群聊，自动区分会话类型

### 飞书会话 ID 规则

飞书会话在本地数据库中使用以下 ID 格式：

| 会话类型 | ID 格式 | 示例 |
|----------|---------|------|
| 私聊 | `feishu_p2p_<chat_id>` | `feishu_p2p_oc_xxx` |
| 群聊 | `feishu_group_<chat_id>` | `feishu_group_oc_xxx` |

可以在 GUI 中直接查看飞书会话的历史记录。

## 使用方法

### 图形界面 (GUI)

```bash
# 启动 GUI
vermilion-bird chat --gui

# 或使用 --frontend 参数
vermilion-bird chat --frontend gui
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

### 记忆系统

Vermilion Bird 支持多层记忆系统，让AI助手能够记住你的偏好和重要信息。

#### 记忆层次

| 层次 | 文件 | 内容 |
|------|------|------|
| 短期记忆 | `short_term.md` | 当前任务、待办事项 |
| 中期记忆 | `mid_term.md` | 近期摘要、事件时间线 |
| 长期记忆 | `long_term.md` | 用户画像、重要事实 |
| 人格设定 | `soul.md` | AI助手的性格和行为准则 |

#### 记忆管理命令

```bash
# 查看记忆状态
vermilion-bird memory status

# 查看人格设定
vermilion-bird memory soul

# 查看各层记忆
vermilion-bird memory short-term
vermilion-bird memory mid-term
vermilion-bird memory long-term

# 备份记忆
vermilion-bird memory backup

# 清空记忆（危险操作）
vermilion-bird memory clear
```

#### 记忆文件位置

记忆文件存储在 `~/.vermilion-bird/memory/` 目录下，可以直接编辑 Markdown 文件来修改记忆内容。

#### 配置

```yaml
memory:
  enabled: true
  storage_dir: "~/.vermilion-bird/memory"
  short_term:
    max_items: 10
  mid_term:
    max_days: 30
    compress_after_days: 7
  long_term:
    auto_evolve: true
    evolve_interval_days: 7
  exclude_patterns:
    - "密码"
    - "password"
    - "token"
    - "api_key"
```

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
├── app.py              # 应用核心协调器
├── cli.py              # CLI 入口（Click），含 chat/feishu/skills/schedule/memory
├── client.py           # 大模型客户端 API
├── config.py           # Pydantic 配置管理（YAML/环境变量/CLI）
├── conversation.py     # 会话管理 + ConversationManager
├── storage.py          # SQLite 持久化（会话/消息/任务/执行/飞书记录）
├── exceptions.py       # 统一异常层次（13 子类）
├── health.py           # 组件健康检查（HealthChecker）
├── service_manager.py  # 通用服务生命周期管理
├── protocols/          # 协议适配器
│   ├── base.py         # BaseProtocol 基类 + ToolCall
│   ├── openai.py       # OpenAI 协议（兼容 DeepSeek/Qwen 等）
│   ├── anthropic.py    # Anthropic Claude 协议
│   └── gemini.py       # Google Gemini 协议
├── frontends/          # 用户界面
│   ├── base.py         # BaseFrontend 抽象基类
│   ├── cli.py          # CLI 终端前端
│   ├── gui.py          # PyQt6 GUI 前端
│   ├── mcp_dialog.py   # MCP 配置对话框
│   ├── skills_dialog.py # 技能配置对话框
│   ├── models_dialog.py # 模型选择对话框
│   ├── scheduler_dialog.py # 定时任务管理界面
│   └── feishu/         # 飞书集成
│       ├── adapter.py   # 消息适配器（含安全检查）
│       ├── server.py    # WebSocket 服务器
│       ├── mapper.py    # 会话 ID 映射
│       ├── models.py    # 数据模型
│       ├── push.py      # 推送服务
│       ├── security.py  # 签名验证/加密
│       └── error_handler.py # 错误处理/重试
├── mcp/                # MCP 客户端
│   ├── types.py        # MCPServerConfig/MCPServerStatus
│   ├── config.py       # MCP 配置
│   ├── client.py       # MCP 客户端封装
│   └── manager.py      # MCP 服务器生命周期管理
├── scheduler/          # 定时任务调度
│   ├── models.py       # Task/TaskExecution 数据模型
│   ├── scheduler.py    # SchedulerService（APScheduler）
│   ├── task_executor.py # TaskExecutor（含重试）
│   └── notification.py # NotificationService（飞书/前端通知）
├── memory/             # 多层记忆系统
│   ├── storage.py      # 记忆文件持久化
│   ├── manager.py      # MemoryManager（提取/压缩/进化）
│   ├── extractor.py    # MemoryExtractor（LLM 辅助提取）
│   └── templates.py    # short/mid/long/soul 模板
├── context/            # 上下文管理
│   ├── types.py        # CompressionLevel/ContextMessage
│   ├── manager.py      # ContextManager（多级压缩+缓存）
│   ├── compressor.py   # ContextCompressor
│   └── cache.py        # ContextCache
├── skills/             # 技能插件系统（10 个内置）
│   ├── base.py         # BaseSkill 抽象基类
│   ├── manager.py      # SkillManager（加载/卸载/发现）
│   ├── registry.py     # 全局 BUILTIN_SKILLS 注册表
│   ├── calculator/     # 安全数学表达式（AST 解析）
│   ├── file_editor/    # 文件编辑
│   ├── file_reader/    # 文件读取
│   ├── file_writer/    # 文件写入
│   ├── scheduler/      # 定时任务管理
│   ├── shell_exec/     # 受控 Shell 执行
│   ├── task_delegator/ # 任务委托（子代理+工具编排）
│   ├── todo_manager/   # 待办事项管理
│   ├── web_fetch/      # 网页抓取
│   └── web_search/     # 网页搜索
├── tools/              # 工具基础设施
│   ├── base.py         # BaseTool 抽象基类
│   ├── registry.py     # ToolRegistry（单例）
│   └── executor.py     # ToolExecutor（并行+重试）
├── services/           # 业务服务层
│   └── conversation_service.py # ConversationService
└── utils/              # 工具函数
    ├── token_counter.py # Token 计数器
    └── retry.py         # 重试工具
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

## Shell 执行技能

Vermilion Bird 内置了Shell执行技能，允许模型在受控环境中执行系统命令获取外部信息。

### 安全特性

- **白名单限制**：仅允许执行配置中指定的命令
- **工作目录限制**：仅允许在项目目录内执行命令
- **超时控制**：命令执行超时自动终止（默认5秒）
- **输出截断**：超过长度限制时自动截断（默认10000字符）
- **完整日志**：所有命令执行均记录日志

### 配置

在 `config.yaml` 中配置Shell执行技能：

```yaml
skills:
  shell_exec:
    enabled: true
    whitelist:
      - "ls"
      - "pwd"
      - "cat"
      - "grep"
      - "head"
      - "tail"
      - "wc"
      - "du"
      - "df"
      - "git"
      - "find"
      - "echo"
      - "date"
      - "whoami"
      - "uname"
      - "env"
      - "printenv"
    default_timeout: 5
    max_output_length: 10000
    allowed_workdir: "./"
```

### 使用示例

模型可以调用 `shell_exec` 工具执行白名单内的命令：

```
用户：当前目录有哪些文件？
模型：我来查看一下当前目录的文件列表。
     [调用 shell_exec: command="ls"]
     输出：README.md  config.yaml  src/  tests/ ...
```

### 默认白名单

| 命令 | 说明 |
|------|------|
| ls | 列出目录内容 |
| pwd | 显示当前工作目录 |
| cat | 查看文件内容 |
| grep | 文本搜索 |
| head | 查看文件头部 |
| tail | 查看文件尾部 |
| wc | 统计行数/字数 |
| du | 磁盘使用情况 |
| df | 文件系统空间 |
| git | Git 版本控制（常用命令） |
| find | 文件查找 |
| echo | 输出文本 |
| date | 显示日期时间 |
| whoami | 显示当前用户 |
| uname | 系统信息 |
| env/printenv | 环境变量 |

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

## 会话管理

### 存储方式

Vermilion Bird 使用 SQLite 数据库存储会话和消息，数据保存在 `.vb/vermilion_bird.db`。

### 数据库结构

- **conversations** - 会话表（ID、标题、创建时间、更新时间）
- **messages** - 消息表（会话ID、角色、内容、时间）
- **messages_fts** - 全文搜索索引

### Python API

```python
from llm_chat.storage import Storage

storage = Storage()

# 创建会话
storage.create_conversation("conv_123", title="我的会话")

# 添加消息
storage.add_message("conv_123", "user", "你好")
storage.add_message("conv_123", "assistant", "你好，有什么可以帮你的？")

# 获取消息
messages = storage.get_messages("conv_123")

# 搜索消息
results = storage.search_messages("关键词")

# 列出所有会话
conversations = storage.list_conversations()

# 更新会话标题
storage.update_conversation("conv_123", title="新标题")

# 删除会话
storage.delete_conversation("conv_123")
```

### 自动迁移

启动时会自动检测旧版 JSON 文件（`.vb/history/` 目录），并迁移到 SQLite 数据库。

## 测试

```bash
pytest
```

## 许可证

MIT
