# Vermilion Bird - 项目知识库

**更新时间**: 2026-06-28
**评分**: A (综合) | 三层架构拆分完成 + 多 Agent 协作 v2 + Decision Card 修复
**Branch**: main
**Commit**: 0bd38dc

## 🆕 三层架构拆分 (全部完成 ✅)

项目已拆分为三层独立包：

```
ember-core  (零 LLM 感知)  →  ember-agent  (Agent 协作)  →  vermilion-bird  (桌面应用)
    pip install ember-core       pip install ember-agent
```

| 包 | 位置 | 内容 |
|----|------|------|
| **ember-core** | `packages/ember-core/` | tools, storage, mcp, graph, pipeline, memory |
| **ember-agent** | `packages/ember-agent/` | agent, workflow, consensus, peer, CollaborationPattern |
| **vermilion-bird** | `src/llm_chat/` | 应用层，通过 re-export 使用 ember 包 |

详细设计文档：[docs/ember-architecture.md](docs/ember-architecture.md)

## 概述

大模型对话客户端，支持多协议（OpenAI/Anthropic/Gemini）、MCP 工具调用、容器化沙箱执行、意图识别路由、事件驱动触发器、多层记忆系统、Decision-First 交互范式、ProactiveAgent 主动推送。
核心栈：Python 3.9+ / Poetry / PyQt6 / MCP / APScheduler / Docker。

## 项目结构

```
vermilion-bird/
├── packages/                  # 🆕 独立可复用包
│   ├── ember-core/            #   零 LLM 感知基础设施
│   │   └── src/ember_core/
│   │       ├── tools/         #     BaseTool, ToolRegistry, ToolExecutor
│   │       ├── storage/       #     SQLiteStore (通用，无业务表)
│   │       ├── mcp/           #     MCPClient, MCPManager, MCP 类型
│   │       ├── graph/         #     StateGraph, Checkpointer, ChannelReducer
│   │       ├── pipeline/      #     PipelineStage, PipelineRunner
│   │       └── memory/        #     MemoryStorage (原子文件读写)
│   │
│   └── ember-agent/           #   Agent 协作层 (依赖 ember-core)
│       └── src/ember_agent/
│           ├── agent/         #     AgentContext, AgentRegistry, AgentRole, SharedBlackboard
│           ├── workflow/      #     WorkflowNode, WorkflowExecutor, AgentWorkflow
│           ├── consensus/     #     DecisionCard, SubmitCardTool, CardAggregator, DecisionLogStore
│           ├── peer/          #     PeerReviewTool, PeerDialogue
│           └── patterns.py    #     CollaborationPattern (6 种预设, YAML 可扩展)
│
├── src/llm_chat/              # 主包
│   ├── __init__.py
│   ├── app.py                 # 应用核心协调器
│   ├── chat_core.py           # 核心对话引擎 (意图识别→记忆→压缩→LLM→工具→持久化)
│   ├── cli.py                 # CLI 入口（Click）
│   ├── client/                # LLM 客户端
│   │   ├── __init__.py        # LLMClient 组合类
│   │   ├── _base.py           # HTTP 请求 + 指数退避重试
│   │   ├── _chat.py           # 同步 chat API
│   │   ├── _stream.py         # 流式 chat API
│   │   ├── _stream_tools.py   # 流式工具调用 (chat_stream_with_tools)
│   │   ├── _tools.py          # 同步工具调用 (统一 ToolExecutor)
│   │   ├── _generate.py       # generate() 文本生成 API
│   │   └── _logging.py        # 请求日志 + token 追踪
│   ├── config.py              # Pydantic 配置管理（YAML/环境变量/CLI/keyring）
│   ├── conversation.py        # 会话管理 + ConversationManager
│   ├── storage/               # SQLite 持久化
│   │   ├── __init__.py
│   │   ├── _core.py           # Storage 单例 + 建表/迁移
│   │   └── _conversation.py   # 对话 CRUD + FTS5 搜索 (jieba 分词)
│   ├── exceptions.py          # 统一异常层次
│   ├── health.py              # 组件健康检查 (5 项: db/services/llm/disk/mcp)
│   ├── service_manager.py     # 通用服务生命周期管理
│   │
│   ├── intent/                # 🆕 意图识别 — 三层路由
│   │   ├── __init__.py
│   │   ├── types.py           # Intent 枚举 + RoutingDecision
│   │   └── classifier.py      # IntentClassifier (L0: 快捷指令, L1: 模式匹配, L2: 模型映射)
│   │
│   ├── protocols/             # 协议适配器
│   │   ├── base.py            # BaseProtocol + ToolCall/ToolCallResult
│   │   ├── openai.py          # OpenAI + 兼容服务
│   │   ├── anthropic.py       # Anthropic Claude (system msg 自动提取)
│   │   └── gemini.py          # Google Gemini (systemInstruction + tool role)
│   │
│   ├── frontends/             # 用户界面
│   │   ├── base.py            # BaseFrontend 抽象基类
│   │   ├── cli.py             # CLI 终端前端
│   │   ├── gui.py             # PyQt6 GUI 前端
│   │   ├── model_config.py    # 配置按钮面板 (MCP/Skills/Models/Scheduler/Dashboard)
│   │   ├── mcp_dialog.py      # MCP 配置对话框
│   │   ├── models_dialog.py   # 模型选择对话框
│   │   ├── skills_dialog.py   # 技能配置对话框
│   │   ├── scheduler_dialog.py # 定时任务管理界面
│   │   ├── observability_dialog.py # 可观测性面板
│   │   └── feishu/            # 飞书/Lark 集成
│   │       ├── adapter.py     # 飞书消息适配器
│   │       ├── server.py      # WebSocket 服务器 (while 重连 + 事件去重)
│   │       ├── mapper.py      # 会话 ID 映射
│   │       ├── models.py      # 飞书数据模型
│   │       ├── push.py        # 推送服务
│   │       ├── security.py    # 安全模块
│   │       └── error_handler.py # 错误处理/重试
│   │
│   ├── mcp/                   # MCP 工具集成
│   │   ├── types.py           # MCPServerConfig/MCPServerStatus
│   │   ├── config.py          # MCPConfig 配置
│   │   ├── client.py          # MCPClient (stdio/SSE)
│   │   └── manager.py         # MCPManager (后台连接 + 健康检查)
│   │
│   ├── scheduler/             # 定时任务 + 事件驱动
│   │   ├── __init__.py        # 懒加载导出
│   │   ├── models.py          # Task/TaskExecution/TaskType (含 WEBHOOK)
│   │   ├── scheduler.py       # SchedulerService (APScheduler + ChatCore 管道)
│   │   ├── task_executor.py   # TaskExecutor (含重试)
│   │   ├── notification.py    # NotificationService (飞书/前端)
│   │   └── webhook.py         # 🆕 WebhookServer (事件驱动, 零依赖 HTTP)
│   │
│   ├── memory/                # 多层记忆系统
│   │   ├── storage.py         # MemoryStorage (原子写入)
│   │   ├── manager.py         # MemoryManager (提取/压缩/去重/进化)
│   │   ├── extractor.py       # MemoryExtractor (LLM 辅助)
│   │   ├── summarizer.py      # Summarizer 抽象 (LLM/Rule)
│   │   └── templates.py       # short/mid/long/soul 模板 + 6 种风格预设
│   │
│   ├── context/               # 上下文管理
│   │   ├── types.py           # CompressionLevel/ContextMessage/CompressionResult
│   │   ├── manager.py         # ContextManager (多级压缩 + 缓存)
│   │   ├── compressor.py      # ContextCompressor (system_context 摘要)
│   │   └── cache.py           # ContextCache (Storage 连接)
│   │
│   ├── decision/              # 🆕 Decision-First 决策卡片
│   │   ├── __init__.py
│   │   ├── schema.py          # DecisionCard/DecisionOption Pydantic 模型
│   │   ├── submit_tool.py     # SubmitDecisionCardTool + contextvar 卡片通道
│   │   ├── card_panel.py      # GUI 卡片渲染 (QFrame)
│   │   ├── log.py             # 决策日志持久化 (SQLite)
│   │   └── action_executor.py # 卡片选项确认文本
│   │
│   ├── proactive/             # 🆕 ProactiveAgent 主动推送
│   │   ├── __init__.py
│   │   └── agent.py           # ProactiveAgent (每日话题生成 + 飞书/GUI 推送)
│   │
│   ├── skills/                # 技能插件系统
│   │   ├── base.py            # BaseSkill 抽象基类
│   │   ├── manager.py         # SkillManager (hash 前缀防冲突)
│   │   ├── registry.py        # 全局 BUILTIN_SKILLS 注册表
│   │   ├── calculator/        # 安全数学表达式计算
│   │   ├── file_editor/       # 文件编辑
│   │   ├── file_reader/       # 文件读取
│   │   ├── file_writer/       # 文件写入
│   │   ├── scheduler/         # 定时任务技能 (LLM 可调用的 CRUD)
│   │   ├── shell_exec/        # 受控 Shell 执行
│   │   │   ├── skill.py       # ShellExecSkill + ShellExecTool (沙箱集成)
│   │   │   └── sandbox.py     # 🆕 SandboxExecutor (Docker/bwrap/subprocess)
│   │   ├── task_delegator/    # 任务委托 (子代理 + 工具编排)
│   │   │   ├── skill.py       # 技能入口
│   │   │   ├── tools.py       # SpawnSubagentTool (SAFE_SKILLS)
│   │   │   ├── registry.py    # AgentRegistry
│   │   │   ├── context.py     # AgentContext (预初始化 deadline)
│   │   │   └── workflow.py    # WorkflowExecutor
│   │   ├── todo_manager/      # 待办事项管理
│   │   ├── web_fetch/         # 网页抓取 (trafilatura + playwright)
│   │   └── web_search/        # 网页搜索 (DuckDuckGo)
│   │
│   └── utils/                 # 工具类
│       ├── token_counter.py   # tiktoken 封装 + 模型上下文限制
│       ├── secure_storage.py  # 🆕 keyring API Key 安全存储
│       ├── observability.py   # span/counter/gauge
│       └── retry.py           # 重试工具
│   │
│   ├── tools/                 # 工具基础设施
│   │   ├── base.py            # BaseTool 抽象基类
│   │   ├── registry.py        # ToolRegistry (单例)
│   │   └── executor.py        # ToolExecutor (并行 + 重试 + 超时)
│   │
│   ├── services/              # 业务服务层
│   │   └── conversation_service.py
│
├── tests/                     # pytest 测试
├── docs/                      # 项目文档
│   ├── 能力审计评估报告.md     # 全量审计 + 修复记录 (35 项, 评分 A)
│   └── ...
├── deploy/                    # 部署配置
├── config.yaml                # 运行时配置
├── config.example.yaml        # 🆕 完整配置示例 (意图识别/沙箱/Webhook/风格)
├── pyproject.toml             # Poetry (含 keyring, jieba 可选依赖)
└── .gitignore
```

## 快速定位

| 任务 | 位置 | 说明 |
|------|------|------|
| **ember 框架** | | |
| 工具注册/执行 | `packages/ember-core/src/ember_core/tools/` | BaseTool, ToolRegistry, ToolExecutor |
| 状态图引擎 | `packages/ember-core/src/ember_core/graph/` | StateGraph, Checkpointer, ChannelReducer |
| 管道执行器 | `packages/ember-core/src/ember_core/pipeline/` | PipelineStage, PipelineRunner |
| MCP 集成 | `packages/ember-core/src/ember_core/mcp/` | MCPClient, MCPManager |
| Agent 生命周期 | `packages/ember-agent/src/ember_agent/agent/` | AgentContext, AgentRegistry, AgentRole |
| 工作流编排 | `packages/ember-agent/src/ember_agent/workflow/` | WorkflowNode, WorkflowExecutor, AgentWorkflow |
| 决策卡片共识 | `packages/ember-agent/src/ember_agent/consensus/` | DecisionCard, CardAggregator, SubmitCardTool |
| Agent 协作拓扑 | `packages/ember-agent/src/ember_agent/patterns.py` | CollaborationPattern (6 种预设, YAML 扩展) |
| **vermilion-bird 应用** | | |
| 添加新协议 | `src/llm_chat/protocols/` | 继承 BaseProtocol，注册到 PROTOCOL_MAP |
| 添加新技能 | `src/llm_chat/skills/` | 继承 BaseSkill，实现 get_tools() |
| 添加新前端 | `src/llm_chat/frontends/` | 继承 BaseFrontend |
| 修改意图识别 | `src/llm_chat/intent/` | 快捷指令/模式匹配/模型路由 |
| 修改对话管道 | `src/llm_chat/chat_core.py` | 完整对话处理管道 |
| 修改配置 | `src/llm_chat/config.py` | Pydantic 验证 |
| 记忆系统 | `src/llm_chat/memory/` | 四层记忆 + LLM 去重 + 风格预设 |
| 定时/事件任务 | `src/llm_chat/scheduler/` | APScheduler + Webhook |
| 沙箱执行 | `src/llm_chat/skills/shell_exec/sandbox.py` | Docker/bwrap/subprocess |
| 上下文管理 | `src/llm_chat/context/` | 三级压缩 + SQLite 缓存 |
| 飞书集成 | `src/llm_chat/frontends/feishu/` | WebSocket (重连+去重) |
| API Key 安全 | `src/llm_chat/utils/secure_storage.py` | keyring 三层 fallback |

## 代码地图

### ember 框架

| 符号 | 类型 | 位置 | 职责 |
|------|------|------|------|
| `StateGraph[StateT]` | Class | ember-core/graph/state.py | 类型安全状态图构建器 |
| `CompiledGraph[StateT]` | Class | ember-core/graph/state.py | 编译后可执行图 (invoke/stream/resume) |
| `Checkpointer` | ABC | ember-core/graph/checkpoint.py | 抽象检查点接口 |
| `SQLiteCheckpointer` | Class | ember-core/graph/checkpoint.py | SQLite 持久化检查点 |
| `ChannelReducer` | ABC | ember-core/graph/reducer.py | 状态字段合并策略 (replace/append/merge) |
| `PipelineRunner` | Class | ember-core/pipeline/runner.py | 顺序管道执行器 |
| `PipelineStage` | ABC | ember-core/pipeline/stage.py | 管道阶段基类 |
| `SQLiteStore` | Class | ember-core/storage/sqlite.py | 通用 SQLite 存储 (WAL, 线程安全) |
| `MemoryStorage` | Class | ember-core/memory/storage.py | 原子文件读写存储 |
| `MCPManager` | Class | ember-core/mcp/manager.py | MCP 多服务器管理器 |
| `MCPClient` | Class | ember-core/mcp/client.py | MCP 单服务器客户端 |
| `AgentRegistry` | Class | ember-agent/agent/registry.py | 线程安全 Agent 注册表 |
| `AgentContext` | Class | ember-agent/agent/context.py | Agent 运行时上下文 |
| `AgentRole` | Class | ember-agent/agent/role.py | Agent 角色定义 + 4 种预设 |
| `SharedBlackboard` | Class | ember-agent/agent/blackboard.py | Agent 共享工作空间 |
| `WorkflowExecutor` | Class | ember-agent/workflow/executor.py | 工作流 DAG 执行引擎 |
| `AgentWorkflow` | Class | ember-agent/workflow/nodes.py | 工作流定义 (simple/parallel/pipeline) |
| `DecisionCard` | Class | ember-agent/consensus/card.py | 决策卡片 Pydantic 模型 |
| `CardAggregator` | Class | ember-agent/consensus/aggregator.py | 多 Agent 共识聚合 (vote/weighted/synthesize) |
| `DecisionLogStore` | Class | ember-agent/consensus/store.py | 决策日志持久化 (SQLiteStore DI) |
| `SubmitCardTool` | Class | ember-agent/consensus/submit.py | LLM tool-call 提交卡片 (contextvar 通道) |
| `PeerReviewTool` | Class | ember-agent/peer/review.py | Agent 互相审查 |
| `PeerDialogue` | Class | ember-agent/peer/dialogue.py | Agent 间多轮对话 |
| `CollaborationPattern` | Class | ember-agent/patterns.py | 预置协作模式 (6 种 + YAML) |

### vermilion-bird 应用

| 符号 | 类型 | 位置 | 职责 |
|------|------|------|------|
| `App` | Class | app.py | 应用协调器，装配所有组件 |
| `ChatCore` | Class | chat_core.py | 对话引擎 (意图→记忆→压缩→LLM→工具) |
| `LLMClient` | Class | client/__init__.py | LLM 客户端 (chat/stream/tools/generate) |
| `Config` | Class | config.py | 全局 Pydantic 配置 |
| `Storage` | Class | storage/_core.py | SQLite 单例 (WAL + FTS5) |
| `IntentClassifier` | Class | intent/classifier.py | 意图分类 (3 层路由) |
| `RoutingDecision` | Class | intent/types.py | 路由决策 (skip_llm/model/tools) |
| `BaseProtocol` | Class | protocols/base.py | 协议基类 |
| `BaseFrontend` | Class | frontends/base.py | 前端基类 |
| `BaseSkill` | Class | skills/base.py | 技能基类 |
| `BaseTool` | Class | tools/base.py | 工具基类 |
| `ToolRegistry` | Class | tools/registry.py | 工具注册表 (单例) |
| `ToolExecutor` | Class | tools/executor.py | 工具并行 + 重试 |
| `MCPManager` | Class | mcp/manager.py | MCP 服务器管理 |
| `SandboxExecutor` | Class | skills/shell_exec/sandbox.py | Docker/bwrap/subprocess 沙箱 |
| `SchedulerService` | Class | scheduler/scheduler.py | APScheduler + Webhook |
| `WebhookServer` | Class | scheduler/webhook.py | 事件驱动 HTTP 触发器 |
| `MemoryManager` | Class | memory/manager.py | 记忆提取/压缩/去重/进化 |
| `MemoryStorage` | Class | memory/storage.py | 记忆文件原子写入 |
| `ContextManager` | Class | context/manager.py | 上下文压缩 + 缓存 |
| `Conversation` | Class | conversation.py | 单会话管理 |
| `ConversationManager` | Class | conversation.py | 多会话管理 + FTS5 搜索 |
| `SkillManager` | Class | skills/manager.py | 技能生命周期 + 模块隔离 |
| `HealthChecker` | Class | health.py | 5 项健康检查 |
| `FeishuAdapter` | Class | frontends/feishu/adapter.py | 飞书消息处理 |
| `FeishuServer` | Class | frontends/feishu/server.py | 飞书 WebSocket (重连+去重) |
| `NotificationService` | Class | scheduler/notification.py | 任务通知 |
| `ServiceManager` | Class | service_manager.py | 通用服务生命周期 |
| `AgentContext` | Class | skills/task_delegator/context.py | 子 agent 运行时上下文 |
| `WorkflowExecutor` | Class | skills/task_delegator/workflow.py | 工作流引擎 |
| `DecisionCard` | Class | decision/schema.py | 决策卡片 Pydantic 模型 |
| `SubmitDecisionCardTool` | Class | decision/submit_tool.py | LLM tool-call 提交卡片 |
| `ProactiveAgent` | Class | proactive/agent.py | 每日主动话题推送 |
| `_repair_json` | Func | client/_stream_tools.py | 流式截断 JSON 修复 |

## 核心数据流

### 主对话管道

```
用户输入 (CLI/GUI/飞书/Webhook)
    │
    ▼
ChatCore.send_message()
    │
    ├── 0. IntentClassifier.classify()          # 🆕 意图识别
    │       ├── skip_llm? → 直接返回 (问候/感谢/再见)
    │       ├── shortcut? → /new /clear /style
    │       └── routing  → 模型映射 + 工具预加载
    │
    ├── 1. 持久化用户消息 → Storage
    ├── 2. _build_system_context()
    │       ├── MemoryManager.build_system_prompt()  # 四层记忆 + 风格注入
    │       ├── FTS5 相关历史搜索 (jieba 分词)
    │       ├── Prompt skills 上下文
    │       └── Decision card prompt (决策卡片触发规则)
    ├── 3. ContextManager.process_context()          # 三级压缩 + 缓存
    │
    ▼
LLMClient (chat / chat_with_tools / chat_stream_with_tools)
    │
    ├── BaseProtocol.build_chat_request()
    │   └── max_tokens 默认 8192 (可传参覆盖)
    ├── HTTP POST (指数退避重试: min(2^n,60) + 10% jitter)
    │
    ├── [如有 tool_calls]
    │   ├── submit_decision_card → 卡片构建 (跳过 execute)
    │   │   ├── 成功 → card_submitted=True → break 迭代
    │   │   └── 失败 → 错误反馈给 LLM 重试
    │   ├── ToolExecutor.execute_tools_parallel()
    │   │   ├── ToolRegistry (内置技能工具)
    │   │   ├── MCPManager (MCP 工具, 优先 Tavily/Brave)
    │   │   └── SandboxExecutor (Docker/bwrap/subprocess)
    │   └── 结果注入 messages，继续迭代
    │
    ▼
ChatCore._extract_pending_card()  # contextvar 提取卡片
    ├── on_card 回调 → GUI DecisionCardWidget 渲染
    └── 飞书端纯文本摘要推送

Conversation.add_assistant_message()
    ├── Storage 持久化 → SQLite
    └── MemoryManager 异步提取 → 多层记忆
```

### ProactiveAgent 主动推送管道

```
SchedulerService (cron 每日触发)
    │
    ▼
ProactiveAgent.generate_and_push()
    │
    ├── _build_context()
    │   ├── 🌐 网络搜索 (DDGS, 按星期轮换主题, 3词×4条 + 兴趣2维×3条)
    │   └── 📝 用户记忆 (辅助, 判断相关性)
    │
    ├── _generate_card()
    │   ├── init_card_context()  # 设置 contextvar
    │   ├── client.chat_with_tools(submit_decision_card)
    │   ├── get_pending_card()   # 提取卡片
    │   └── clear_card_context()
    │
    ▼
DecisionCard
    ├──→ GUI: card_created signal → DecisionCardWidget
    └──→ 飞书: 纯文本摘要 + 独立会话
```

## 配置体系

### 优先级（从高到低）
1. **CLI 参数**
2. **环境变量**
3. **config.yaml**
4. **keyring** (API Key 安全存储)
5. **Pydantic 默认值**

### 配置节点

| 节点 | 类 | 说明 |
|------|-----|------|
| `llm` | LLMConfig | 模型连接 + base_url + protocol |
| `mcp` | MCPConfig | MCP 服务器列表 (stdio/SSE) |
| `feishu` | FeishuConfig | 飞书应用配置 |
| `scheduler` | SchedulerConfig | 调度器 + webhook 端口 |
| `memory` | MemoryConfig | 多层记忆参数 + 去重 |
| `context` | ContextConfig | 上下文压缩参数 |
| `skills` | SkillsConfig | 各技能配置 (含 sandbox_enabled) |
| `tools` | ToolsConfig | 工具执行 + 意图识别 + 模型映射 |
| `notification` | NotificationConfig | 任务通知 |

### 🆕 关键新配置

```yaml
# 意图识别 + 模型路由
tools:
  enable_intent: true
  intent_model_map:
    small: "gpt-4o-mini"
    medium: "gpt-4o"
    large: "claude-3-5-sonnet"

# Webhook 事件驱动
scheduler:
  webhook_enabled: true
  webhook_port: 9100

# 容器化沙箱
skills:
  shell_exec:
    sandbox_enabled: true          # 显式启用
    sandbox_timeout: 60
    sandbox_max_memory_mb: 256

# API Key 安全
# 推荐: keyring 系统密钥链
# vermilion-bird keyring set openai default
```

## 🆕 增量优化 (2026-05-16, 8 项)

| 能力 | 位置 | 说明 |
|------|------|------|
| **ProactiveAgent web-first** | `proactive/agent.py` | 网络搜索为主要话题燃料, 记忆退为辅助; 搜索深度 3×4+兴趣×2×3 |
| **决策卡片节流** | `chat_core.py` | 新增"默认不用卡片"原则 + 3 问自检清单 + 严格约束文本回复为 1 句 |
| **流式 JSON 修复** | `client/_stream_tools.py` | `_repair_json()` 三层策略: 补全括号→截断到尾键值→保留首键值 |
| **max_tokens 默认 8192** | `protocols/` | 三个协议统一默认 8192 (原 4096/1000)，防止 API 默认值过小截断 |
| **submit_decision_card 失败重试** | `client/_tools.py`, `_stream_tools.py` | 参数缺失时反馈 LLM 具体缺失字段, LLM 自行修复重试 |
| **卡片提交后终止迭代** | `client/_tools.py`, `_stream_tools.py` | `card_submitted` 标志, 成功后 break 外层循环, 避免空调用浪费 token |
| **卡片 contextvar 修复** | `proactive/agent.py` | ProactiveAgent 对齐 ChatCore 模式: init→LLM→get→clear |
| **卡片拦截 skip execute** | `client/_tools.py`, `_stream_tools.py` | submit_decision_card 不进入正常 tool execute, 避免空参数 crash |

## 🆕 多 Agent 协作 v2 (2026-06-28)

| 能力 | 位置 | 说明 |
|------|------|------|
| **CollaborationPattern (6 种)** | `ember-agent/patterns.py` | research/debate/review/compare/pipeline/critique_refine |
| **YAML 自定义模式** | `config.yaml → collaboration_patterns:` | 不改代码扩展协作模式 |
| **YAML 自定义角色** | `config.yaml → roles:` | 不改代码定义新 AgentRole |
| **CollaborationEngine** | `llm_chat/skills/task_delegator/engine.py` | DAG 执行 + 循环 + 失败恢复 |
| **Agent 间通信** | `blackboard_tools.py` | post_finding/query_findings 共享发现 |
| **SharedBlackboard** | `ember-agent/agent/blackboard.py` | Pattern 级共享工作空间 |
| **共享 LLMClient** | `task_delegator/tools.py` | 子 agent 复用父 HTTP 连接池 |
| **取消传导** | `task_delegator/tools.py` | 父 cancel → 子 agent 中止 |
| **依赖声明** | spawn_subagent `depends_on` 参数 | `{agent_id.result}` 模板注入 |
| **GUI 子 Agent 面板** | `frontends/subagent_panel.py` | 实时树 + 详情弹窗 + 取消 |
| **LLM 易用性** | tool schema + SOUL 模板 | 模式指南 + 示例 |
| **结构化输出** | engine.py merge result | JSON summary (agents, findings, errors) |
| **Decision Card 修复** | `chat_core_graph.py` | init_card_context 正确初始化 |

### 使用方式

```python
# 模式 1: 预定义 pattern (LLM 一键)
spawn_subagent(pattern="research", task="调研三家AI公司")

# 模式 2: 手动编排 (LLM 自由控制)
spawn_subagent(role="planner", task="拆解任务", result_var="plan", wait=true)
spawn_subagent(role="executor", task="执行 {plan.result}", depends_on=[上一步ID])

# YAML 扩展
roles:
  researcher:
    system_prompt: "..."
    default_tools: ["web_search"]

collaboration_patterns:
  code_audit:
    stages:
      - id: auditor, role: executor
      - id: reviewer, role: critic, depends_on: [auditor]
    aggregator_role: synthesizer
```

## 🆕 新增能力 (本轮 35 项修复)

| 能力 | 位置 | 说明 |
|------|------|------|
| **意图识别** | `intent/` | 三层路由, 问候直接回复, 模型自动选择 |
| **快捷指令** | ChatCore | /new /clear /help /search /file /code /style |
| **风格预设** | memory/templates.py | 6 种一键切换 (default/academic/casual/concise/coach/architect) |
| **容器化沙箱** | skills/shell_exec/sandbox.py | Docker/bwrap/subprocess 三层, 心跳自毁 |
| **Webhook 触发器** | scheduler/webhook.py | 事件驱动, 零依赖 HTTP, secret 校验 |
| **中期记忆去重** | memory/manager.py | LLM 主题聚类, 摘要≥7条自动触发 |
| **健康检查增强** | health.py | llm/disk/mcp 3 项新增 |
| **FTS5 中文分词** | storage/_conversation.py | jieba 可选依赖 |
| **API Key 安全** | utils/secure_storage.py | keyring 三层 fallback |
| **记忆模板重写** | memory/templates.py | short/mid/long/soul 结构化 |
| **SOUL 重写** | memory/templates.py | 安全护栏 + 工具策略 (MCP 优先) |
| **HTTP 退避** | client/_base.py | min(2^n, 60) + 10% jitter |
| **MCP 后台连接** | app.py | 不阻塞 UI |
| **飞书重连+去重** | frontends/feishu/server.py | while loop + 指数退避 |

## 安全模型

| 层 | 机制 |
|----|------|
| **API Key** | keyring → 环境变量 → 明文, 三层 fallback |
| **Shell 执行** | Docker/bwrap (只读FS+无网络+禁止提权) → 白名单兜底 |
| **HTTP** | 指数退避重试 + jitter |
| **输入** | Pydantic v2 + shlex.split |
| **飞书** | 签名验证 + 加密 + 事件去重 |
| **内存** | 敏感信息脱敏 (正则 + LLM 辅助) |
| **Webhook** | X-Webhook-Secret 校验 |

## 约定

### 打包与依赖
- Python >= 3.9, Poetry
- 入口点: `vermilion-bird = "llm_chat.cli:main"`
- 可选依赖: keyring (API Key), jieba (中文分词), Docker (沙箱)

### 代码风格
- black: `line-length=100`, `target-version=py39`
- 类型注解广泛使用 (Optional, List, Dict, TYPE_CHECKING)
- Pydantic v2 BaseModel 配置模型
- 中文 docstrings, 部分 Google 风格

### 单例模式
- `Storage` — SQLite 存储 (`__new__`)
- `ToolRegistry` — 工具注册表 (`__new__`)
- `SchedulerService._instances` — 调度器全局注册表

### 安全
- `calculator`: SafeCalculator (ast.NodeVisitor), 无 eval()
- `shell_exec`: 沙箱优先 (Docker/bwrap) → 白名单兜底
- 定时任务: ChatCore 完整管道 (非裸 client.chat)

## 常用命令

```bash
# 安装与运行
poetry install
poetry run vermilion-bird                  # CLI
poetry run vermilion-bird chat --gui       # GUI
poetry run vermilion-bird feishu           # 飞书

# API Key 安全存储
vermilion-bird keyring set openai default
vermilion-bird keyring list

# 定时/事件任务
vermilion-bird schedule create --name "Code Review" \
  --task-type WEBHOOK --webhook-secret "secret" \
  --message "审查最新代码改动"
vermilion-bird schedule list
vermilion-bird schedule info <task-id>

# 记忆管理
vermilion-bird memory status
vermilion-bird memory soul

# 技能管理
vermilion-bird skills list

# 测试
poetry run pytest
poetry run black . && poetry run flake8
```

## 注意事项

- 记忆文件: `~/.vermilion-bird/memory/` (short/mid/long/soul.md)
- 会话数据: `.vb/vermilion_bird.db` (SQLite WAL + FTS5)
- 沙箱心跳: `work/.sandbox_heartbeat` (gitignore)
- 飞书: 需要 `lark-oapi`, 使用 `LogLevel` 枚举
- Python 3.14: 需要 `pkg_resources.py` shim (APScheduler 兼容)
- keyring: macOS Keychain / Linux Secret Service / Windows Credential Manager

## 子目录文档

- [protocols/](src/llm_chat/protocols/AGENTS.md) - 协议适配器
- [mcp/](src/llm_chat/mcp/AGENTS.md) - MCP 工具集成
- [frontends/](src/llm_chat/frontends/AGENTS.md) - CLI/GUI/飞书前端
- [memory/](src/llm_chat/memory/AGENTS.md) - 记忆系统
- [scheduler/](src/llm_chat/scheduler/AGENTS.md) - 定时任务调度系统
- [intent/](src/llm_chat/intent/) - 意图识别
