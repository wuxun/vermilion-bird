# Vermilion Bird - 项目知识库

**生成时间**: 2026-05-02
**Commit**: 164afc6
**Branch**: main

## 概述

大模型对话客户端，支持多协议（OpenAI/Anthropic/Gemini）、MCP 工具调用、飞书集成、定时任务调度、多层记忆系统。
核心栈：Python 3.9+ / Poetry / PyQt6 / MCP / APScheduler。

## 项目结构

```
vermilion-bird/
├── src/llm_chat/              # 主包 (~19.7K 行)
│   ├── __init__.py
│   ├── app.py                 # 应用核心协调器
│   ├── cli.py                 # CLI 入口（Click），含 chat/feishu/skills/schedule/memory 命令组
│   ├── client.py              # LLM 客户端 API（chat/chat_stream/chat_with_tools）
│   ├── config.py              # Pydantic 配置管理（YAML/环境变量/CLI）
│   ├── conversation.py        # 会话管理 + ConversationManager
│   ├── storage.py             # SQLite 持久化（单例），含任务/执行/飞书记录表
│   ├── exceptions.py          # 统一异常层次（VermilionBirdError → 13 子类）
│   ├── health.py              # 组件健康检查（HealthChecker）
│   ├── service_manager.py     # 通用服务生命周期管理（Service 协议）
│   │
│   ├── protocols/             # 协议适配器（OpenAI/Anthropic/Gemini）
│   │   ├── base.py            # BaseProtocol + ToolCall/ToolCallResult 数据类
│   │   ├── openai.py          # OpenAI + 兼容服务（DeepSeek/Qwen 等）
│   │   ├── anthropic.py       # Anthropic Claude
│   │   └── gemini.py          # Google Gemini
│   │
│   ├── frontends/             # 用户界面
│   │   ├── base.py            # BaseFrontend 抽象基类 + Message/ConversationContext
│   │   ├── cli.py             # CLI 终端前端
│   │   ├── gui.py             # PyQt6 GUI 前端 (~1900 行)
│   │   ├── mcp_dialog.py      # MCP 配置对话框
│   │   ├── models_dialog.py   # 模型选择对话框
│   │   ├── skills_dialog.py   # 技能配置对话框
│   │   ├── scheduler_dialog.py # 定时任务管理界面
│   │   └── feishu/            # 飞书/Lark 集成
│   │       ├── adapter.py     # 飞书消息适配器（含安全检查）
│   │       ├── server.py      # WebSocket 服务器（lark-oapi）
│   │       ├── mapper.py      # 会话 ID 映射（feishu ↔ 本地）
│   │       ├── models.py      # 飞书数据模型
│   │       ├── push.py        # 推送服务
│   │       ├── security.py    # 安全模块（签名验证/加密）
│   │       └── error_handler.py # 错误处理/重试
│   │
│   ├── mcp/                   # MCP 工具集成
│   │   ├── types.py           # MCPServerConfig/MCPServerStatus
│   │   ├── config.py          # MCPConfig 配置
│   │   ├── client.py          # MCPClient（stdio/SSE 传输）
│   │   └── manager.py         # MCPManager（服务器生命周期/工具发现）
│   │
│   ├── scheduler/             # 定时任务调度
│   │   ├── __init__.py        # 懒加载导出（Python 3.14 pkg_resources 兼容）
│   │   ├── models.py          # Task/TaskExecution/TaskType/TaskStatus
│   │   ├── scheduler.py       # SchedulerService（APScheduler + ThreadPoolExecutor）
│   │   ├── task_executor.py   # TaskExecutor（独立执行器，含重试逻辑）
│   │   └── notification.py    # NotificationService（飞书/前端通知）
│   │
│   ├── memory/                # 多层记忆系统
│   │   ├── storage.py         # MemoryStorage（文件持久化）
│   │   ├── manager.py         # MemoryManager（提取/压缩/进化）
│   │   ├── extractor.py       # MemoryExtractor（LLM 辅助提取）
│   │   └── templates.py       # short/mid/long/soul 模板
│   │
│   ├── context/               # 上下文管理
│   │   ├── types.py           # CompressionLevel/ContextMessage/CompressionResult
│   │   ├── manager.py         # ContextManager（多级压缩 + 缓存）
│   │   ├── compressor.py      # ContextCompressor（摘要/截断/微压缩）
│   │   └── cache.py           # ContextCache（SQLite 缓存）
│   │
│   ├── skills/                # 技能插件系统（10 个内置）
│   │   ├── base.py            # BaseSkill 抽象基类
│   │   ├── manager.py         # SkillManager（加载/卸载/重载/发现）
│   │   ├── registry.py        # 全局 BUILTIN_SKILLS 注册表
│   │   ├── calculator/        # 安全数学表达式计算
│   │   ├── file_editor/       # 文件编辑
│   │   ├── file_reader/       # 文件读取
│   │   ├── file_writer/       # 文件写入
│   │   ├── scheduler/         # 定时任务技能（LLM 可调用的 CRUD）
│   │   ├── shell_exec/        # 受控 Shell 执行（白名单 + 超时 + 目录限制）
│   │   ├── task_delegator/    # 任务委托（子代理 + 工具编排）
│   │   ├── todo_manager/      # 待办事项管理
│   │   ├── web_fetch/         # 网页抓取（trafilatura + playwright 回退）
│   │   └── web_search/        # 网页搜索（DuckDuckGo）
│   │
│   ├── tools/                 # 工具基础设施
│   │   ├── base.py            # BaseTool 抽象基类
│   │   ├── registry.py        # ToolRegistry（单例注册表）
│   │   └── executor.py        # ToolExecutor（并行执行 + 重试）
│   │
│   ├── services/              # 业务服务层
│   │   └── conversation_service.py # ConversationService
│   │
│   └── utils/                 # 工具类
│       ├── token_counter.py   # tiktoken 封装 + 模型上下文限制表
│       └── retry.py           # 重试工具
│
├── tests/                     # pytest 测试（25 文件, ~4.7K 行）
│   ├── conftest.py            # Mock APScheduler 模块
│   ├── test_app.py
│   ├── test_client.py
│   ├── test_config.py
│   ├── test_context_management.py
│   ├── test_conversation.py
│   ├── test_storage.py
│   ├── test_skills_shell_exec.py
│   ├── test_task_delegator.py
│   ├── test_cli_schedule.py
│   ├── test_feishu_*.py       # 飞书相关测试（8 个）
│   ├── test_scheduler/        # 调度器单元测试
│   └── integration/           # 集成测试
│
├── skills/                    # 外部技能模板
├── deploy/                    # 部署配置
│   ├── install.sh
│   ├── vermilion-bird.service
│   └── vermilion-bird-chat.service
├── docs/                      # 项目文档
├── work/                      # 研究文档（大模型对比等）
├── config.yaml                # 运行时配置
├── config.example.yaml        # 配置示例
├── pyproject.toml             # Poetry 打包配置
├── requirements.txt           # pip 安装依赖
└── pkg_resources.py           # Python 3.14 pkg_resources shim
```

## 快速定位

| 任务 | 位置 | 说明 |
|------|------|------|
| 添加新协议 | `src/llm_chat/protocols/` | 继承 BaseProtocol，注册到 PROTOCOL_MAP |
| 添加新技能 | `src/llm_chat/skills/` | 继承 BaseSkill，实现 get_tools()，注册到 registry.py |
| 添加新前端 | `src/llm_chat/frontends/` | 继承 BaseFrontend，注册到 FRONTEND_MAP |
| 添加新 CLI 命令组 | `src/llm_chat/cli.py` | 使用 @click.group() 装饰器 |
| 修改配置加载 | `src/llm_chat/config.py` | Config.from_yaml() 处理优先级 |
| 修改 GUI | `src/llm_chat/frontends/gui.py` | PyQt6 实现 |
| 修改 CLI | `src/llm_chat/frontends/cli.py` | Rich 终端输出 |
| MCP 集成 | `src/llm_chat/mcp/` | 工具发现/调用 |
| 记忆系统 | `src/llm_chat/memory/` | 短期/中期/长期记忆 |
| 定时任务 | `src/llm_chat/scheduler/` | APScheduler 调度 + 通知 |
| 上下文管理 | `src/llm_chat/context/` | 多级压缩/缓存/子代理 |
| 飞书集成 | `src/llm_chat/frontends/feishu/` | WebSocket 机器人 |
| 异常定义 | `src/llm_chat/exceptions.py` | 统一异常基类 |
| 健康检查 | `src/llm_chat/health.py` | 组件健康状态 |

## 代码地图

| 符号 | 类型 | 位置 | 职责 |
|------|------|------|------|
| `LLMClient` | Class | client.py | 对外 API，chat/chat_stream/chat_with_tools |
| `Config` | Class | config.py | 全局配置，from_yaml() 加载，Pydantic 验证 |
| `App` | Class | app.py | 应用协调器，连接 client/storage/frontend/scheduler |
| `BaseProtocol` | Class | protocols/base.py | 协议基类，工具调用支持 |
| `BaseFrontend` | Class | frontends/base.py | 前端基类，回调模式 |
| `BaseSkill` | Class | skills/base.py | 技能基类，get_tools() 接口 |
| `BaseTool` | Class | tools/base.py | 工具基类，to_openai_tool() |
| `MCPManager` | Class | mcp/manager.py | MCP 服务器生命周期管理 |
| `SchedulerService` | Class | scheduler/scheduler.py | APScheduler 封装，任务调度 |
| `TaskExecutor` | Class | scheduler/task_executor.py | 独立任务执行器，含重试 |
| `NotificationService` | Class | scheduler/notification.py | 任务结果通知（飞书/前端） |
| `MemoryManager` | Class | memory/manager.py | 记忆提取/压缩/进化 |
| `MemoryStorage` | Class | memory/storage.py | 记忆文件持久化 |
| `ContextManager` | Class | context/manager.py | 上下文多级压缩+缓存 |
| `Storage` | Class | storage.py | SQLite 持久化（单例） |
| `Conversation` | Class | conversation.py | 单会话管理，记忆/上下文集成 |
| `ConversationManager` | Class | conversation.py | 多会话管理 + 共享 MemoryManager |
| `SkillManager` | Class | skills/manager.py | 技能加载/卸载/发现 |
| `ToolRegistry` | Class | tools/registry.py | 工具注册表（单例） |
| `ToolExecutor` | Class | tools/executor.py | 工具并行执行 + 重试 |
| `ServiceManager` | Class | service_manager.py | 通用服务生命周期管理 |
| `HealthChecker` | Class | health.py | 组件健康检查器 |
| `FeishuAdapter` | Class | frontends/feishu/adapter.py | 飞书消息处理适配 |
| `FeishuServer` | Class | frontends/feishu/server.py | 飞书 WebSocket 服务器 |
| `ConversationService` | Class | services/conversation_service.py | 对话业务逻辑层 |

## 配置体系

### 优先级（从高到低）
1. **CLI 参数** - `--model`, `--base-url`, `--api-key` 等
2. **环境变量** - `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`, `LLM_PROTOCOL` 等
3. **config.yaml** - YAML 配置文件
4. **Pydantic 默认值** - 代码中定义的 Field(default=...)

### 配置节点（config.yaml）

| 节点 | 对应 Pydantic 类 | 说明 |
|------|-------------------|------|
| `llm` | LLMConfig | 模型连接参数 + 模型参数 + available_models |
| `mcp` | MCPConfig | MCP 服务器列表（stdio/SSE） |
| `feishu` | FeishuConfig | 飞书应用 ID/Secret/加密/验证 |
| `scheduler` | SchedulerConfig | 调度器并发数/时区 |
| `memory` | MemoryConfig | 多层记忆参数 |
| `context` | ContextConfig | 上下文压缩/缓存参数 |
| `skills` | SkillsConfig | 各技能启用/配置（extra="allow" 支持自定义） |
| `tools` | ToolsConfig | 工具执行并并行/重试/超时 |
| `notification` | NotificationConfig | 任务通知默认目标 |
| `enable_tools` | bool | 全局工具开关 |
| `external_skill_dirs` | list | 外部技能目录 |

## 数据流

```
用户输入 (CLI/GUI/飞书)
    │
    v
BaseFrontend._handle_message()
    │
    v
App._handle_message() 回调
    │
    ├── MemoryManager.build_system_prompt()   → 注入记忆
    ├── ContextManager.process_context()      → 上下文压缩
    │
    v
LLMClient.chat / chat_with_tools()
    │
    ├── BaseProtocol.build_chat_request()
    ├── requests.Session.post()
    │
    ├── [如有 tool_calls]
    │   ├── ToolExecutor.execute_tools_parallel()
    │   │   ├── ToolRegistry (内置技能工具)
    │   │   └── MCPManager (外部 MCP 工具)
    │   └── 结果注入 messages，继续迭代
    │
    v
Conversation.add_user_message() / add_assistant_message()
    │
    ├── Storage.add_message()  → SQLite
    └── MemoryManager.schedule_extraction() → 异步记忆提取
```

## 约定

### 打包与依赖
- 使用 Poetry（`pyproject.toml`），兼容 `pip install -r requirements.txt`
- 开发依赖：pytest, pytest-cov, black, flake8
- 入口点：`vermilion-bird = "llm_chat.cli:main"`
- Python >= 3.9

### 类型注解
- 广泛使用 typing 模块（Optional, List, Dict, Any）
- Pydantic v2 BaseModel 用于配置模型
- `TYPE_CHECKING` 用于避免循环导入

### 导入顺序
- 标准库 → 第三方库 → 本地导入（组间空行）

### 文档
- 中文 docstrings，部分模块使用 Google 风格
- 项目文档集中在 `docs/`、`work/`、`deploy/`

### 测试
- 测试文件：`tests/test_*.py`，使用 pytest
- `tests/conftest.py` 在 pytest_configure 中 mock APScheduler 避免导入问题
- 使用 `setup_module/teardown_module` 进行环境清理

### 单例模式
- `Storage` - SQLite 存储（`__new__` 实现）
- `ToolRegistry` - 工具注册表（`__new__` 实现）
- `_scheduler_registry` - 调度器全局注册表（字典）

### 懒加载
- `scheduler/__init__.py` 的 `SchedulerService` 通过 `__getattr__` 懒加载
- `pkg_resources.py` shim 在导入 APScheduler 前加载（Python 3.14 兼容）

## 反模式（本项目）

### 安全
- `skills/calculator/skill.py` 已使用 `SafeCalculator(ast.NodeVisitor)` 进行安全表达式解析，不涉及 `eval()`
- `skills/shell_exec/skill.py` 使用白名单 + 目录限制 + 超时控制确保安全

### 代码风格
- black 配置: `line-length=100`, `target-version=py39` (见 pyproject.toml)
- flake8 配置: `max-line-length=100`, 忽略 E203/W503 (见 pyproject.toml)

### 依赖
- Python 3.14 需要 `pkg_resources.py` shim（`src/llm_chat/` 内），用于 APScheduler 兼容

## 常用命令

```bash
# 安装
poetry install
pip install -r requirements.txt

# 运行 CLI
poetry run vermilion-bird

# 运行 GUI
poetry run vermilion-bird chat --gui

# 启动飞书机器人
poetry run vermilion-bird feishu

# 记忆管理
poetry run vermilion-bird memory status
poetry run vermilion-bird memory soul

# 技能管理
poetry run vermilion-bird skills list

# 定时任务管理
poetry run vermilion-bird schedule list
poetry run vermilion-bird schedule create --name "每日问候" --cron "0 9 * * *" --message "早上好！"

# 测试
poetry run pytest
poetry run pytest tests/test_scheduler/ -v

# 代码格式化
poetry run black .
poetry run flake8
```

## 注意事项

- 记忆文件存储在 `~/.vermilion-bird/memory/`
- 会话数据存储在 `.vb/vermilion_bird.db`（SQLite）
- 技能配置通过 `config.yaml` 的 `skills` 节点控制
- MCP 服务器配置在 `config.yaml` 的 `mcp.servers` 节点
- 定时任务也持久化到同一 SQLite 数据库（tasks/task_executions 表）
- 飞书集成需要 `lark-oapi` 包，且使用 `LogLevel` 枚举而非字符串
- Python 3.14 需要 pkg_resources shim（项目自带）

## 子目录文档

- [protocols/](src/llm_chat/protocols/AGENTS.md) - 协议适配器
- [mcp/](src/llm_chat/mcp/AGENTS.md) - MCP 工具集成
- [frontends/](src/llm_chat/frontends/AGENTS.md) - CLI/GUI/飞书前端
- [memory/](src/llm_chat/memory/AGENTS.md) - 记忆系统
- [scheduler/](src/llm_chat/scheduler/AGENTS.md) - 定时任务调度系统
