# Ember 架构设计 — 三层拆分方案

**设计日期**: 2026-06-28
**状态**: Phase 3 完成 ✅

## 实施记录

### Phase 1: 提取纯基础设施 → ember-core ✅
- `tools/` (BaseTool, ToolRegistry, ToolExecutor) — 零改动迁移
- `storage/` (SQLiteStore) — 新建通用存储，不含业务表
- `mcp/` (MCPClient, MCPManager, types) — 零改动迁移
- vermilion-bird 全部 40+ 处 import 通过 re-export 兼容

### Phase 2: 提取 Agent 系统 → ember-agent ✅
- `consensus/card.py` — schema.py 零改动
- `consensus/submit.py` — 补全 JSON Schema (confidence/risk/expected_effect)
- `consensus/store.py` — SQLiteStore 依赖注入
- `agent/context.py`, `agent/registry.py` — 零改动 + 重命名
- `workflow/` — 零改动 + executor_fn 注入

### Phase 3: 新能力 + 应用层改造 ✅
- ember-core/graph/ — StateGraph, CompiledGraph, Checkpointer, ChannelReducer
- ember-core/pipeline/ — PipelineStage, PipelineRunner
- ember-core/memory/ — MemoryStorage 原子文件读写
- ember-agent/agent/ — AgentRole (4 预设) + SharedBlackboard
- ember-agent/consensus/ — CardAggregator (vote/weighted/synthesize)
- ember-agent/peer/ — PeerReviewTool + PeerDialogue
- ember-agent/patterns.py — MultiAgentPattern (4 种拓扑)
- vermilion-bird: SpawnSubagentTool 接入 AgentRole, WorkflowExecutor 改用新接口

将 vermilion-bird 拆分为三层架构，提取通用基础设施为独立可复用包：

```
┌──────────────────────────────────────┐
│         vermilion-bird               │  🟠 桌面应用
│   GUI / CLI / 飞书 / 定时任务 / 意图  │
├──────────────────────────────────────┤
│          ember-agent                 │  🟡 Agent 协作层
│   AgentRegistry / Workflow / 共识     │     依赖 ember-core
├──────────────────────────────────────┤
│          ember-core                  │  🔵 零 LLM 感知的基础设施
│   Tool / Storage / MCP / Graph        │     唯一外部依赖: Pydantic v2
└──────────────────────────────────────┘
```

### 命名说明

- **ember** = 余烬，火熄灭后仍然炽热的炭核。与朱雀（Vermilion Bird，南方火之守护神）主题呼应——"鸟是应用，余烬是框架"。
- **ember-core**: 纯基础设施，不感知 LLM 存在。pip install ember-core 即可使用工具注册、持久化、MCP、状态图等能力。
- **ember-agent**: 基于 ember-core 构建的 Agent 协作层，提供角色定义、工作流执行、决策卡片共识、Agent 互相审查等高级能力。

---

## 设计原则

### 1. ember-core 铁律

```
ember-core 的每一行代码都不允许 import LLM、Model、Chat、Token
唯一外部依赖: Pydantic v2
不"知道" LLM 的存在
```

### 2. 边界清晰

| 组件 | 归属 | 理由 |
|------|------|------|
| `tools/` (BaseTool, ToolRegistry, ToolExecutor) | **core** | 纯工具注册/执行，与 LLM 无关 |
| `storage/` (BaseStore, SQLiteStore) | **core** | 持久化抽象 |
| `mcp/` (MCPClient, MCPManager) | **core** | MCP 协议集成 |
| `graph/` (StateGraph, Checkpointer) | **core** | 🆕 通用状态图引擎 |
| `pipeline/` (PipelineStage, PipelineRunner) | **core** | 管道执行器（图的退化子集） |
| `memory/` (MemoryStorage 不含 LLM) | **core** | 文件原子写入 (Phase 2) |
| `agent/` (AgentContext, AgentRegistry, AgentRole, SharedBlackboard) | **agent** | Agent 生命周期管理 |
| `workflow/` (WorkflowNode, WorkflowExecutor, WorkflowDSL) | **agent** | 工作流编排 |
| `consensus/` (DecisionCard, CardAggregator, SubmitCardTool) | **agent** | Agent 共识协议 |
| `peer/` (PeerReviewTool, PeerDialogue) | **agent** | 🆕 Agent 互相审查 |

---

## ember-core 详细设计

### 目录结构

```
packages/ember-core/
├── pyproject.toml
└── src/ember_core/
    ├── __init__.py           # 公共 API 导出
    ├── tools/
    │   ├── __init__.py
    │   ├── base.py           # BaseTool 抽象基类
    │   ├── registry.py       # ToolRegistry (单例)
    │   └── executor.py       # ToolExecutor (并行 + 重试 + 超时)
    ├── storage/
    │   ├── __init__.py
    │   ├── base.py           # BaseStore 抽象
    │   └── sqlite.py         # SQLiteStore (WAL, 线程安全)
    ├── mcp/
    │   ├── __init__.py
    │   ├── types.py          # MCPServerConfig, MCPServerStatus
    │   ├── client.py         # MCPClient (stdio/SSE)
    │   └── manager.py        # MCPManager
    ├── graph/                # 🆕 通用状态图引擎
    │   ├── __init__.py
    │   ├── state.py          # StateGraph, CompiledGraph, StateUpdate
    │   ├── nodes.py          # NodeSpec
    │   ├── edges.py          # EdgeSpec, ConditionalEdge
    │   ├── reducer.py        # ChannelReducer (replace/append/merge)
    │   └── checkpoint.py     # Checkpointer, SQLiteCheckpointer, MemoryCheckpointer
    ├── pipeline/             # PipelineRunner = 图的退化子集
    │   ├── __init__.py
    │   ├── stage.py          # PipelineStage
    │   └── runner.py         # PipelineRunner
    └── memory/
        ├── __init__.py
        └── storage.py        # MemoryStorage (文件原子写入, 不含LLM逻辑)
```

### graph/ 核心 API

状态图是 ember-core 的核心新增。设计目标：与 LangGraph 语义兼容但零外部依赖。

```python
from ember_core.graph import StateGraph, NodeSpec, EdgeSpec, ConditionalEdge
from ember_core.graph import Checkpointer, SQLiteCheckpointer
from ember_core.graph import AppendReducer, MergeReducer

# 用户用 Pydantic 定义状态
class MyState(BaseModel):
    messages: list[dict] = Field(default_factory=list)
    tool_results: dict = Field(default_factory=dict)
    should_loop: bool = False

# 构建图
graph = StateGraph(MyState)
graph.add_node("process", my_process_fn)
graph.add_node("execute_tool", my_tool_fn)

# 条件边：根据状态动态路由
graph.add_conditional_edge("process",
    router=lambda s: "execute_tool" if s.should_loop else "__finish__",
    routes={"execute_tool": "execute_tool", "__finish__": "__finish__"})

graph.add_conditional_edge("execute_tool",
    router=lambda s: "process" if s.tool_loop_count < 10 else "__finish__",
    routes={"process": "process", "__finish__": "__finish__"})

graph.add_edge("execute_tool", "process")  # 无条件边
graph.set_entry_point("process")

# 编译执行
compiled = graph.compile(
    checkpointer=SQLiteCheckpointer(store),
    interrupt_before=["execute_tool"]  # 可选中断点
)

# invoke / stream / resume
result = compiled.invoke(MyState())
for update in compiled.stream(MyState()):
    print(f"Node: {update.node_name}, Step: {update.step}")
compiled.resume(thread_id="abc", user_input={"approved": True})
```

### 关键类定义

| 类 | 职责 |
|----|------|
| `StateGraph[StateT]` | 类型安全的状态图构建器 |
| `CompiledGraph[StateT]` | 编译后可执行图，支持 invoke/stream/resume |
| `NodeSpec[StateT]` | 节点定义：纯函数 (State → State)，可选 interrupt |
| `EdgeSpec` | 无条件边：from_node → to_node |
| `ConditionalEdge` | 条件边：router(State) → next_node |
| `Checkpointer` (ABC) | 抽象检查点：save/load/delete |
| `SQLiteCheckpointer` | SQLite 实现，复用 SQLiteStore |
| `MemoryCheckpointer` | 内存实现，用于测试 |
| `ChannelReducer` | 状态字段合并策略：replace / append / merge |
| `AppendReducer` | 用于 messages 列表追加 |
| `MergeReducer` | 深度合并 dict |
| `StateUpdate[StateT]` | stream() 产出的事件：node_name, state, step |

---

## ember-agent 详细设计

### 目录结构

```
packages/ember-agent/
├── pyproject.toml
└── src/ember_agent/
    ├── __init__.py
    ├── agent/
    │   ├── __init__.py
    │   ├── context.py        # AgentContext
    │   ├── registry.py       # AgentRegistry (SubAgentRegistry → 重命名)
    │   ├── role.py           # 🆕 AgentRole (角色定义 + 预设)
    │   └── blackboard.py     # 🆕 SharedBlackboard
    ├── workflow/
    │   ├── __init__.py
    │   ├── nodes.py          # WorkflowNode, WorkflowNodeType (AGENT/PARALLEL/SEQUENCE/CONDITION)
    │   ├── executor.py       # WorkflowExecutor
    │   └── dsl.py            # WorkflowDSL (JSON→DAG解析)
    ├── consensus/
    │   ├── __init__.py
    │   ├── card.py           # DecisionCard, DecisionOption
    │   ├── submit.py         # SubmitCardTool (contextvar通道)
    │   ├── aggregator.py     # 🆕 CardAggregator (vote/weighted_score/synthesize)
    │   └── store.py          # DecisionLogStore
    └── peer/
        ├── __init__.py
        ├── review.py         # 🆕 PeerReviewTool
        └── dialogue.py       # 🆕 PeerDialogue (Agent间多轮对话)
```

### AgentRole — Agent 人设

```python
from ember_agent.agent import AgentRole

# 使用预设
planner = AgentRole.PRESETS["planner"]
critic = AgentRole.PRESETS["critic"]

# 自定义
researcher = AgentRole(
    name="代码研究员",
    system_prompt="你是代码分析专家，擅长发现架构模式...",
    default_tools=["file_reader", "grep", "web_search"],
    output_schema=ResearchReport,
)

# 通过 SpawnSubagentTool 使用
spawn_tool.execute(
    agent_id="researcher-1",
    role=researcher,          # 替代手动写 system_prompt
    task="分析 src/llm_chat 的架构",
)
```

### SharedBlackboard — Agent 共享工作空间

```python
from ember_agent.agent import SharedBlackboard, BlackboardEntry

bb = SharedBlackboard()

# Agent A 发现一个事实
bb.post(BlackboardEntry(
    agent_id="explorer-1",
    key="auth_module_location",
    value="src/llm_chat/auth/oauth.py",
    confidence=0.95,
    entry_type="fact"
))

# Agent B 查询
results = bb.query("认证模块在哪里")

# 快照作为上下文注入
context = bb.snapshot()  # → list[BlackboardEntry]
```

### CardAggregator — 多 Agent 共识

```python
from ember_agent.consensus import CardAggregator

# 投票模式
final_card = CardAggregator.vote([card_a, card_b, card_c])

# 加权模式（confidence × agent权重）
final_card = CardAggregator.weighted_score(
    cards=[card_a, card_b],
    weights={"agent-a": 1.0, "agent-b": 0.7}
)

# 综合模式（让一个综合Agent看所有卡片）
final_card = CardAggregator.synthesize(
    cards=[card_a, card_b, card_c],
    synthesizer=synthesizer_agent_node
)
```

### 预置协作模式

```python
from ember_agent import MultiAgentPattern

# 管理者分派 → Workers并行 → 管理者汇总
graph = MultiAgentPattern.manager_worker(
    manager=AgentRole.PRESETS["planner"],
    workers=[AgentRole.PRESETS["executor"]] * 3,
    state_schema=MyState,
)

# 辩论 → 裁判裁决
graph = MultiAgentPattern.debate(
    pro=AgentRole(name="正方", ...),
    con=AgentRole(name="反方", ...),
    judge=AgentRole.PRESETS["critic"],
    state_schema=MyState,
    rounds=3,
)

# 创作 → 批评 → 修改循环
graph = MultiAgentPattern.critique_refine(
    creator=AgentRole(name="创作者", ...),
    critics=[AgentRole.PRESETS["critic"]] * 2,
    state_schema=MyState,
    max_rounds=3,
)
```

---

## 依赖关系

```
pydantic (唯一外部依赖)
    │
    ▼
ember-core           pip install ember-core
    │
    ▼
ember-agent          pip install ember-agent
    │
    ▼
vermilion-bird       pip install vermilion-bird  (含 PyQt6, APScheduler, tiktoken...)
```

---

## 迁移路径

### Phase 1: 提取纯基础设施 → ember-core

| 步骤 | 内容 | 验证 |
|------|------|------|
| 1a | Poetry workspace + ember-core 包骨架 | `poetry install` 成功 |
| 1b | 移动 `tools/` → ember-core | 现有测试通过 |
| 1c | 移动 `storage/` → ember-core | 现有测试通过 |
| 1d | 移动 `mcp/` → ember-core | 现有测试通过 |
| 1e | vermilion-bird 适配 ember-core import | `poetry run pytest` 通过 |

### Phase 2: 提取 Agent 系统 → ember-agent

| 步骤 | 内容 | 验证 |
|------|------|------|
| 2a | ember-agent 包骨架 | `poetry install` 成功 |
| 2b | 移动 `task_delegator/` → ember-agent/agent/ | 现有测试通过 |
| 2c | 移动 `decision/` → ember-agent/consensus/ | 现有测试通过 |
| 2d | vermilion-bird 适配 ember-agent import | 全量测试通过 |

### Phase 3: 新能力（基于 ember 框架）

| 步骤 | 内容 |
|------|------|
| 3a | ember-core: 实现 `graph/` (StateGraph + Checkpointer) |
| 3b | ember-agent: 实现 `AgentRole` + `SharedBlackboard` |
| 3c | ember-agent: 实现 `CardAggregator` |
| 3d | ember-agent: 实现 `PeerReviewTool` + `PeerDialogue` |
| 3e | ember-agent: 实现 `MultiAgentPattern` 预设 |
| 3f | vermilion-bird: ChatCore 管道从 PipelineRunner 迁移到 StateGraph |

---

## 与现有代码的关系

### 现有模块 → 新归属

| 现有位置 | 新位置 | 说明 |
|---------|--------|------|
| `src/llm_chat/tools/` | `ember_core/tools/` | 直接移动，零改动 |
| `src/llm_chat/storage/` | `ember_core/storage/` | 抽象基类 + SQLite实现 |
| `src/llm_chat/mcp/` | `ember_core/mcp/` | MCP协议集成 |
| `src/llm_chat/skills/task_delegator/registry.py` | `ember_agent/agent/registry.py` | 重命名为 AgentRegistry |
| `src/llm_chat/skills/task_delegator/context.py` | `ember_agent/agent/context.py` | AgentContext |
| `src/llm_chat/skills/task_delegator/workflow.py` | `ember_agent/workflow/` | WorkflowExecutor |
| `src/llm_chat/decision/schema.py` | `ember_agent/consensus/card.py` | DecisionCard |
| `src/llm_chat/decision/submit_tool.py` | `ember_agent/consensus/submit.py` | SubmitCardTool |
| `src/llm_chat/decision/log.py` | `ember_agent/consensus/store.py` | DecisionLogStore |
| `src/llm_chat/memory/storage.py` | `ember_core/memory/storage.py` | MemoryStorage 文件写入部分 |

### 留在 vermilion-bird 的组件 (不适合提取)

| 组件 | 原因 |
|------|------|
| `storage/` (7 张业务表) | conversations/tasks/feishu 表与业务绑定 |
| `memory/manager.py`, `extractor.py` | 含 LLM 调用逻辑 |
| `task_delegator/tools.py` | SpawnSubagentTool 依赖 LLMClient |
| `task_delegator/workflow_tools.py` | ExecuteWorkflowTool 依赖 Skills 系统 |
| `decision/card_panel.py` | PyQt6 GUI 渲染 |
| `client/`, `protocols/`, `frontends/` | LLM 调用 + UI，纯应用层 |

---

## 最终目标 API

```python
# ember-core 用户
from ember_core.tools import BaseTool, ToolRegistry, ToolExecutor
from ember_core.storage import SQLiteStore
from ember_core.mcp import MCPManager
from ember_core.graph import StateGraph, SQLiteCheckpointer, AppendReducer
from ember_core.pipeline import PipelineStage, PipelineRunner

# ember-agent 用户
from ember_agent.agent import AgentRole, AgentContext, AgentRegistry, SharedBlackboard
from ember_agent.workflow import WorkflowNode, WorkflowExecutor
from ember_agent.consensus import DecisionCard, SubmitCardTool, CardAggregator
from ember_agent.peer import PeerReviewTool, PeerDialogue
from ember_agent import MultiAgentPattern  # manager_worker, debate, pipeline, critique_refine

# vermilion-bird 用户 (不变)
from llm_chat.cli import main
vermilion-bird chat --gui
```
