# Vermilion Bird - 项目架构文档

## 概述

Vermilion Bird 是一个大模型对话工具，支持多协议 LLM（OpenAI、Anthropic、Gemini）、MCP 工具客户端、Skills 扩展系统。

---

## 项目结构

```
src/llm_chat/
├── __init__.py
├── app.py                 # 应用入口，整合各组件
├── cli.py                 # CLI 启动入口和日志配置
├── client.py              # LLMClient，与大模型交互的核心类
├── config.py              # 配置系统（LLMConfig, SkillsConfig, Config）
├── conversation.py        # 会话管理（Conversation, ConversationManager）
├── storage.py             # 数据存储（SQLite）
│
├── protocols/             # API 协议实现
│   ├── __init__.py
│   ├── base.py            # BaseProtocol 基类
│   ├── openai.py          # OpenAI 协议
│   ├── anthropic.py       # Anthropic 协议
│   └── gemini.py          # Gemini 协议
│
├── skills/                # Skills 扩展系统
│   ├── __init__.py
│   ├── base.py            # BaseSkill 基类
│   ├── manager.py         # SkillManager
│   ├── web_search/        # 网络搜索技能
│   │   ├── __init__.py
│   │   └── skill.py
│   └── calculator/        # 计算器技能
│       ├── __init__.py
│       └── skill.py
│
├── tools/                 # 工具基础设施
│   ├── __init__.py
│   ├── base.py            # BaseTool 基类
│   └── registry.py        # ToolRegistry（单例）
│
├── frontends/             # 前端界面
│   ├── __init__.py
│   ├── base.py            # BaseFrontend 基类
│   ├── cli.py             # CLI 前端
│   ├── gui.py             # PyQt6 GUI 前端
│   └── mcp_dialog.py      # MCP 配置对话框
│
└── mcp/                   # MCP 客户端
    ├── __init__.py
    ├── client.py
    ├── config.py
    ├── manager.py
    └── types.py
```

---

## 核心组件

### 1. Config（配置系统）

```python
class LLMConfig(BaseSettings):
    base_url: str          # API 基础 URL
    model: str             # 模型名称
    api_key: Optional[str] # API 密钥
    timeout: int           # 请求超时（秒）
    max_retries: int       # 最大重试次数
    protocol: str          # 协议类型: openai, anthropic, gemini
    http_proxy: Optional[str]  # HTTP 代理
    https_proxy: Optional[str] # HTTPS 代理

class SkillConfig(BaseSettings):
    enabled: bool          # 是否启用
    # 支持额外字段（extra = "allow"）

class SkillsConfig(BaseSettings):
    web_search: SkillConfig
    calculator: SkillConfig
    # 支持自定义 Skills

class Config(BaseSettings):
    llm: LLMConfig
    mcp: MCPConfig
    enable_tools: bool
    skills: SkillsConfig
    external_skill_dirs: List[str]
```

### 2. LLMClient（大模型客户端）

核心职责：
- 与大模型 API 交互
- 管理工具调用流程
- 协调 SkillManager

```python
class LLMClient:
    def __init__(self, config: Config)
    
    # 基础聊天
    def chat(self, message: str, history: List[Dict]) -> str
    def chat_stream(self, message: str, history: List[Dict]) -> Generator[str]
    
    # 带工具的聊天
    def chat_with_tools(self, message: str, tools: List, history: List[Dict]) -> str
    def chat_stream_with_tools(self, message: str, tools: List, history: List[Dict]) -> Generator
    
    # 工具管理
    def has_builtin_tools(self) -> bool
    def get_builtin_tools(self) -> List[Dict]
    def execute_builtin_tool(self, name: str, arguments: Dict) -> str
```

### 3. SkillManager（技能管理器）

核心职责：
- 发现和加载 Skills
- 管理 Skill 生命周期
- 协调 Skill 与 ToolRegistry

```python
class SkillManager:
    def register_skill_class(self, skill_class: Type[BaseSkill]) -> None
    def discover_skills(self, skill_dirs: List[str]) -> List[Type[BaseSkill]]
    def load_skill(self, skill_name: str, config: Dict) -> bool
    def unload_skill(self, name: str) -> bool
    def load_from_config(self, skills_config: Dict) -> None
    def list_skill_names(self) -> List[str]
```

### 4. BaseSkill（技能基类）

```python
class BaseSkill(ABC):
    @property
    def name(self) -> str          # Skill 唯一标识
    @property
    def description(self) -> str   # Skill 描述
    @property
    def version(self) -> str       # 版本号
    
    def get_tools(self) -> List[BaseTool]  # 返回工具列表
    def on_load(self, config: Dict) -> None  # 加载时调用
    def on_unload(self) -> None    # 卸载时调用
```

### 5. BaseTool（工具基类）

```python
class BaseTool(ABC):
    @property
    def name(self) -> str          # 工具名称
    @property
    def description(self) -> str   # 工具描述
    
    def get_parameters_schema(self) -> Dict  # OpenAI 格式参数 schema
    def execute(self, **kwargs) -> str       # 执行工具
    
    def to_openai_tool(self) -> Dict    # 转换为 OpenAI 工具格式
    def to_anthropic_tool(self) -> Dict # 转换为 Anthropic 工具格式
```

### 6. ToolRegistry（工具注册表）

单例模式，管理所有已注册的工具。

```python
class ToolRegistry:
    def register(self, tool: BaseTool) -> None
    def unregister(self, name: str) -> bool
    def get_tool(self, name: str) -> Optional[BaseTool]
    def get_all_tools(self) -> List[BaseTool]
    def has_tool(self, name: str) -> bool
    def execute_tool(self, name: str, **kwargs) -> str
    def get_tools_for_openai(self) -> List[Dict]
    def get_tools_for_anthropic(self) -> List[Dict]
```

### 7. Storage（数据存储）

单例模式，SQLite 数据库存储会话和消息。

```python
class Storage:
    def create_conversation(self, conversation_id: str, title: str) -> Dict
    def get_conversation(self, conversation_id: str) -> Optional[Dict]
    def list_conversations(self, limit: int, offset: int) -> List[Dict]
    def update_conversation(self, conversation_id: str, title: str) -> bool
    def delete_conversation(self, conversation_id: str) -> bool
    
    def add_message(self, conversation_id: str, role: str, content: str) -> int
    def get_messages(self, conversation_id: str) -> List[Dict]
    def clear_messages(self, conversation_id: str) -> bool
    def search_messages(self, query: str, conversation_id: str) -> List[Dict]
```

---

## 数据流

### 1. 普通聊天流程

```
用户输入 → Frontend → App → Conversation → LLMClient.chat()
    → Protocol.build_chat_request() → API 请求
    → Protocol.parse_chat_response() → 响应文本
    → Frontend.display_message()
```

### 2. 带工具的聊天流程

```
用户输入 → Frontend → App → LLMClient.chat_stream_with_tools()
    │
    ├─→ 迭代 1: 发送请求（带 tools 参数）
    │       ↓
    │   检测 tool_calls
    │       ↓
    │   执行工具: ToolRegistry.execute_tool()
    │       ↓
    │   添加 tool 结果到消息
    │
    ├─→ 迭代 2: 发送请求（包含 tool 结果）
    │       ↓
    │   无 tool_calls，返回最终响应
    │
    └─→ Frontend.display_message()
```

### 3. Skill 加载流程

```
LLMClient.__init__()
    │
    ├─→ SkillManager 初始化
    │
    ├─→ 注册内置 Skill 类（WebSearchSkill, CalculatorSkill）
    │
    ├─→ 发现外部 Skills（external_skill_dirs）
    │
    ├─→ 从配置加载 Skills（load_from_config）
    │       │
    │       ▼
    │   Skill.on_load(config)
    │       │
    │       ▼
    │   注册 Tools 到 ToolRegistry
    │
    └─→ Skills 可用
```

---

## 配置文件

```yaml
# config.yaml
llm:
  base_url: "https://api.openai.com/v1"
  model: "gpt-3.5-turbo"
  api_key: "your-api-key"
  protocol: "openai"
  timeout: 30
  max_retries: 3
  http_proxy: "http://127.0.0.1:7890"
  https_proxy: "http://127.0.0.1:7890"

mcp:
  servers:
    - name: "example-server"
      command: "python"
      args: ["server.py"]

enable_tools: true

skills:
  web_search:
    enabled: true
    engine: "duckduckgo"
    timeout: 30
  calculator:
    enabled: true

external_skill_dirs:
  - "~/.vermilion-bird/skills"
```

---

## 日志系统

### 日志配置

```python
# cli.py
def setup_logging(level=logging.INFO, log_file: str = None):
    handlers = [logging.StreamHandler(sys.stdout)]
    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding='utf-8'))
    
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=handlers
    )
```

### 日志级别

| 级别 | 使用场景 |
|------|---------|
| INFO | 关键操作（请求发送、响应完成、工具调用） |
| DEBUG | 详细信息（URL、状态码、迭代详情） |
| WARNING | 警告信息（重试、协议不支持） |
| ERROR | 错误信息（请求失败、工具执行失败） |

### 启动参数

```bash
# 输出到控制台（默认 INFO）
python -m llm_chat.app

# 指定日志级别
python -m llm_chat.app --log-level DEBUG

# 输出到文件
python -m llm_chat.app --log-file app.log

# 同时输出到控制台和文件
python -m llm_chat.app --log-file app.log --log-level DEBUG
```

---

## 设计原则

1. **高内聚**：每个模块封装独立的功能
2. **低耦合**：模块之间通过接口交互
3. **易扩展**：支持自定义 Skills 和 Protocols
4. **可配置**：通过 YAML 文件管理配置
5. **日志支持**：关键位置打印日志，便于调试

---

## 更新历史

| 日期 | 版本 | 更新内容 |
|------|------|---------|
| 2024-01 | 1.0.0 | 初始架构 |
| 2024-01 | 1.1.0 | 添加 Skills 扩展系统 |
| 2024-01 | 1.2.0 | 移除废弃的 BuiltinToolsConfig |
| 2024-01 | 1.3.0 | 添加完整日志系统 |
