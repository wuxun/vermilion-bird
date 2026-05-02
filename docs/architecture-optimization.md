# Vermilion Bird 架构优化分析

**分析时间**: 2026-05-02
**Commit**: 164afc6
**Branch**: main

---

## 目录

1. [架构现状总结](#1-架构现状总结)
2. [架构问题与优化](#2-架构问题与优化)
3. [功能缺口与优先级](#3-功能缺口与优先级)
4. [实施路线图](#4-实施路线图)

---

## 1. 架构现状总结

### 1.1 当前架构层次

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

### 1.2 亮点（值得保留和加强）

| 系统 | 亮点 |
|------|------|
| **三层记忆系统** | short/mid/long/soul + token 预算控制，超越大多开源 agent 项目 |
| **三级上下文压缩** | micro/auto/manual 分级压缩 + 完整转录本自动保存 |
| **Skill 插件化** | BaseSkill 抽象简洁，10 个内置 skill 覆盖核心场景 |
| **Pydantic 配置体系** | 严格校验 + 多来源合并 (YAML/env/CLI) |
| **统一异常层次** | VermilionBirdError → 13 子类，精确错误处理 |
| **ServiceManager** | 通用服务生命周期管理 |

---

## 2. 架构问题与优化

### 2.1 App 类承担过多职责（God Class 倾向）

**当前问题**：`app.py` 的 `App.__init__` 同时处理：配置初始化、LLM 客户端创建、会话管理、前端接线、MCP 管理器、调度器初始化、健康检查、工具执行委托。随功能增加，App 将持续膨胀，难以测试和维护。

**建议方案**：引入 Builder 模式或依赖注入容器，让 App 纯粹做编排：

```python
class AppBuilder:
    """应用构建器 —— 负责所有组件的创建和装配"""

    def __init__(self, config: Config):
        self.config = config

    def build(self) -> App:
        storage = Storage()
        client = LLMClient(self.config)
        memory_mgr = self._build_memory(client, storage)
        conv_mgr = self._build_conversations(client, storage, memory_mgr)
        scheduler = self._build_scheduler(storage) if self.config.scheduler.enabled else None
        mcp_mgr = self._build_mcp()
        skill_mgr = self._build_skills(client)

        return App(
            config=self.config,
            client=client,
            storage=storage,
            memory_manager=memory_mgr,
            conversation_manager=conv_mgr,
            scheduler=scheduler,
            mcp_manager=mcp_mgr,
            skill_manager=skill_mgr,
        )

    def _build_memory(self, client, storage) -> MemoryManager: ...
    def _build_conversations(self, client, storage, memory) -> ConversationManager: ...
    def _build_scheduler(self, storage) -> SchedulerService: ...
    def _build_mcp(self) -> MCPManager: ...
    def _build_skills(self, client) -> SkillManager: ...
```

**影响范围**：`app.py`、`cli.py`、测试文件
**工作量**：约 3-4 小时

---

### 2.2 Conversation.send_message() 方法链过长

**当前问题**：单个方法承担：记忆注入 → 上下文压缩 → LLM 调用 → 响应存储 → 记忆提取。各阶段耦合在一起，难以单独测试、替换或扩展。

**建议方案**：分离为 Pipeline 模式，每个阶段独立可插拔：

```python
from abc import ABC, abstractmethod

class PipelineStage(ABC):
    """管道阶段基类"""

    @abstractmethod
    async def process(self, ctx: PipelineContext) -> PipelineContext:
        ...

class PipelineContext:
    """管道上下文 —— 在各阶段间传递"""
    def __init__(self):
        self.conversation_id: str = ""
        self.user_message: str = ""
        self.history: List[Dict] = []
        self.system_context: Optional[str] = None
        self.compressed_messages: List[ContextMessage] = []
        self.response: Optional[str] = None
        self.metadata: Dict[str, Any] = {}


class MemoryInjectionStage(PipelineStage):
    """阶段1: 记忆注入"""
    def __init__(self, memory_manager: MemoryManager):
        self.memory_manager = memory_manager

    async def process(self, ctx: PipelineContext) -> PipelineContext:
        ctx.system_context = self.memory_manager.build_system_prompt()
        return ctx


class ContextCompressionStage(PipelineStage):
    """阶段2: 上下文压缩"""
    def __init__(self, context_manager: ContextManager):
        self.context_manager = context_manager

    async def process(self, ctx: PipelineContext) -> PipelineContext:
        # 组装消息
        messages = [ContextMessage(role="system", content=ctx.system_context or "")]
        for h in ctx.history:
            messages.append(ContextMessage(**h))
        messages.append(ContextMessage(role="user", content=ctx.user_message))

        result = self.context_manager.process_context(ctx.conversation_id, messages)
        ctx.compressed_messages = result.messages
        return ctx


class LLMCallStage(PipelineStage):
    """阶段3: LLM 调用"""
    def __init__(self, client: LLMClient):
        self.client = client

    async def process(self, ctx: PipelineContext) -> PipelineContext:
        # 分离系统提示和对话
        system = next((m.content for m in ctx.compressed_messages if m.role == "system"), None)
        history = [
            {"role": m.role, "content": m.content}
            for m in ctx.compressed_messages if m.role != "system"
        ]
        user_msg = history[-1]["content"] if history else ctx.user_message
        history = history[:-1]

        ctx.response = self.client.chat(user_msg, history, system_context=system)
        return ctx


class MemoryExtractionStage(PipelineStage):
    """阶段4: 异步记忆提取"""
    def __init__(self, memory_manager: MemoryManager):
        self.memory_manager = memory_manager

    async def process(self, ctx: PipelineContext) -> PipelineContext:
        messages = [
            {"role": "user", "content": ctx.user_message},
            {"role": "assistant", "content": ctx.response},
        ]
        self.memory_manager.schedule_extraction(messages)
        self.memory_manager.process_pending_extractions()
        return ctx


class MessagePipeline:
    """消息处理管道"""

    def __init__(self, stages: List[PipelineStage]):
        self.stages = stages

    async def process(self, conversation_id: str, message: str,
                      history: List[Dict]) -> str:
        ctx = PipelineContext()
        ctx.conversation_id = conversation_id
        ctx.user_message = message
        ctx.history = history

        for stage in self.stages:
            ctx = await stage.process(ctx)

        return ctx.response
```

**优势**：
- 每个阶段可独立单元测试
- 可选阶段（如跳过记忆注入、跳过压缩）
- 容易插入新的中间阶段（如安全审查、内容过滤）
- 便于性能监控（每个阶段的耗时）

**影响范围**：`conversation.py`（新增 pipeline 模块）
**工作量**：约 4-5 小时

---

### 2.3 子 Agent 执行是同步阻塞的 ⚠️ 最关键问题

**当前问题**：`SpawnSubagentTool._execute_task()` 中父 agent **同步等待**子 agent 完成，导致：

1. LLM 调用子 agent 时整个工具调用链被阻塞
2. 无法并行创建多个子 agent 处理独立子任务
3. 超时控制形同虚设（仅在 `App._execute_tool` 的 `future.result(timeout=60)` 生效）
4. 用户体验差——需要等待子任务全部完成才能看到响应

**建议方案**：改为真正的异步/线程池模式

```python
class SpawnSubagentTool(BaseTool):
    """创建子agent并分配任务的工具（异步版）"""

    def __init__(self, registry, parent_context, config,
                 executor: Optional[ThreadPoolExecutor] = None):
        self.registry = registry
        self.parent_context = parent_context
        self.config = config
        self.executor = executor or ThreadPoolExecutor(max_workers=4)

    def execute(self, **kwargs) -> str:
        # ... 参数提取和验证（同前）

        # 创建子agent上下文
        context = AgentContext(
            agent_id=agent_id,
            parent_id=self.parent_context.agent_id if self.parent_context else None,
            depth=(self.parent_context.depth + 1) if self.parent_context else 0,
            allowed_tools=set(filtered_tools),
            conversation_id=f"conv_{uuid.uuid4()}",
            created_at=datetime.utcnow(),
            status="spawned",
            work_dir=work_dir,
        )
        self.registry.spawn(agent_id, context)

        # ✅ 异步提交执行，立即返回 agent_id
        future = self.executor.submit(
            self._execute_task, agent_id, task, filtered_tools, timeout, context, model_config
        )
        self.registry.set_future(agent_id, future)

        logger.info(f"异步创建子agent {agent_id}, 任务: {task[:50]}...")

        return json.dumps({
            "agent_id": agent_id,
            "status": "spawned",
            "message": (
                f"子agent已创建，任务在后台执行中。"
                f"使用 get_subagent_status({agent_id}) 查询进度和结果。"
                f"也可以使用 cancel_subagent({agent_id}) 取消任务。"
            )
        }, ensure_ascii=False, indent=2)
```

**对应的 SubAgentRegistry 增强**：

```python
class SubAgentRegistry:
    def __init__(self):
        self._agents: Dict[str, AgentContext] = {}
        self._futures: Dict[str, Future] = {}  # ✅ 新增
        self._lock = threading.Lock()

    def set_future(self, agent_id: str, future: Future):
        with self._lock:
            self._futures[agent_id] = future
            # 添加完成回调
            future.add_done_callback(lambda f: self._on_complete(agent_id, f))

    def _on_complete(self, agent_id: str, future: Future):
        """子agent完成回调"""
        with self._lock:
            if agent_id in self._agents:
                if future.exception():
                    self._agents[agent_id].status = "failed"
                    self._agents[agent_id].result = str(future.exception())
                else:
                    self._agents[agent_id].status = "completed"
                    self._agents[agent_id].result = future.result()

    def list_all(self) -> List[Dict[str, Any]]:
        """列出所有子agent及其状态"""
        with self._lock:
            return [
                {
                    "agent_id": ctx.agent_id,
                    "parent_id": ctx.parent_id,
                    "status": ctx.status,
                    "created_at": ctx.created_at.isoformat(),
                    "result": ctx.result,
                }
                for ctx in self._agents.values()
            ]
```

**调用模式变化**：

```
旧模式（同步）：
  父 agent → spawn_subagent(task_A) → 等待... → 拿到结果 → spawn_subagent(task_B) → 等待... → 汇总

新模式（异步）：
  父 agent → spawn_subagent(task_A) → 立即返回 agent_id_A
           → spawn_subagent(task_B) → 立即返回 agent_id_B
           → spawn_subagent(task_C) → 立即返回 agent_id_C
           → 轮询 get_subagent_status(A, B, C) → 汇总全部结果
```

**影响范围**：`skills/task_delegator/tools.py`、`skills/task_delegator/registry.py`
**工作量**：约 5-6 小时

---

### 2.4 缺少 Agent 工作流编排层

**当前问题**：只能 spawn 单个子 agent，不能：
- **并行创建**多个子 agent 处理独立子任务
- **串行管道**：agent A 输出 → agent B 输入
- **条件分支**：根据子 agent 结果决定下一步
- **错误恢复**：子 agent 失败时的降级策略

**建议方案**：增加 `AgentWorkflow` 抽象层

```python
from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Callable, Any


class WorkflowNodeType(Enum):
    AGENT = "agent"        # 子agent任务
    PARALLEL = "parallel"  # 并行执行多个子节点
    SEQUENCE = "sequence"  # 串行执行多个子节点
    CONDITION = "condition"  # 条件分支
    MERGE = "merge"        # 合并多个分支结果


@dataclass
class WorkflowNode:
    """工作流节点"""
    node_id: str
    node_type: WorkflowNodeType
    # AGENT 类型参数
    task_template: Optional[str] = None       # 任务模板（支持 {parent_result} 变量）
    allowed_tools: List[str] = field(default_factory=list)
    model_config: Optional[Dict[str, Any]] = None
    timeout: int = 60
    # SEQUENCE/PARALLEL 类型参数
    children: List["WorkflowNode"] = field(default_factory=list)
    # CONDITION 类型参数
    condition: Optional[Callable[[Dict], bool]] = None  # 分支条件
    true_branch: Optional["WorkflowNode"] = None
    false_branch: Optional["WorkflowNode"] = None
    # 通用
    on_error: str = "fail"  # fail / skip / retry


@dataclass
class WorkflowResult:
    """工作流执行结果"""
    workflow_id: str
    status: str  # running / completed / failed
    node_results: Dict[str, Any]  # node_id → result
    execution_time: float
    error: Optional[str] = None


class AgentWorkflow:
    """Agent 工作流 —— 描述子agent的拓扑和执行顺序"""

    def __init__(self, workflow_id: str, name: str):
        self.workflow_id = workflow_id
        self.name = name
        self.root: Optional[WorkflowNode] = None

    @classmethod
    def simple(cls, name: str, task: str, tools: List[str]) -> "AgentWorkflow":
        """创建单agent简单工作流"""
        wf = cls(str(uuid.uuid4()), name)
        wf.root = WorkflowNode(
            node_id="root",
            node_type=WorkflowNodeType.AGENT,
            task_template=task,
            allowed_tools=tools,
        )
        return wf

    @classmethod
    def parallel(cls, name: str, tasks: List[Dict]) -> "AgentWorkflow":
        """创建并行工作流"""
        wf = cls(str(uuid.uuid4()), name)
        children = [
            WorkflowNode(
                node_id=f"agent_{i}",
                node_type=WorkflowNodeType.AGENT,
                task_template=t["task"],
                allowed_tools=t.get("tools", []),
            )
            for i, t in enumerate(tasks)
        ]
        wf.root = WorkflowNode(
            node_id="parallel_root",
            node_type=WorkflowNodeType.PARALLEL,
            children=children,
        )
        return wf

    @classmethod
    def pipeline(cls, name: str, stages: List[Dict]) -> "AgentWorkflow":
        """创建串行管道工作流 —— 前一个agent的输出作为后一个的输入"""
        wf = cls(str(uuid.uuid4()), name)
        children = []
        for i, stage in enumerate(stages):
            task = stage["task"]
            if i > 0 and "{parent_result}" not in task:
                task = f"基于前面的结果，{task}"
                task += "\n\n前置阶段输出:\n{parent_result}"
            children.append(WorkflowNode(
                node_id=f"stage_{i}",
                node_type=WorkflowNodeType.AGENT,
                task_template=task,
                allowed_tools=stage.get("tools", []),
                model_config=stage.get("model_config"),
            ))
        wf.root = WorkflowNode(
            node_id="pipeline_root",
            node_type=WorkflowNodeType.SEQUENCE,
            children=children,
        )
        return wf


class WorkflowExecutor:
    """工作流执行器 —— 负责执行AgentWorkflow"""

    def __init__(self, subagent_registry: SubAgentRegistry,
                 thread_pool: ThreadPoolExecutor):
        self.registry = subagent_registry
        self.pool = thread_pool
        self._running: Dict[str, WorkflowResult] = {}

    def execute(self, workflow: AgentWorkflow) -> str:
        """提交工作流执行，返回workflow_id"""
        result = WorkflowResult(
            workflow_id=workflow.workflow_id,
            status="running",
            node_results={},
            execution_time=0,
        )
        self._running[workflow.workflow_id] = result
        self.pool.submit(self._execute_node, workflow.root, workflow, result)
        return workflow.workflow_id

    def _execute_node(self, node: WorkflowNode, workflow: AgentWorkflow,
                      result: WorkflowResult, parent_result: Dict = None):
        """递归执行工作流节点"""
        if node.node_type == WorkflowNodeType.PARALLEL:
            # 并行执行所有子节点
            futures = []
            for child in node.children:
                f = self.pool.submit(self._execute_node, child, workflow, result, parent_result)
                futures.append((child.node_id, f))
            for node_id, f in futures:
                try:
                    result.node_results[node_id] = f.result(timeout=node.timeout * len(node.children))
                except Exception as e:
                    result.node_results[node_id] = {"status": "failed", "error": str(e)}
        elif node.node_type == WorkflowNodeType.SEQUENCE:
            # 串行执行子节点，前一个的输出传给下一个
            prev_result = parent_result
            for child in node.children:
                prev_result = self._execute_node(child, workflow, result, prev_result)
        elif node.node_type == WorkflowNodeType.AGENT:
            # 执行单个agent任务
            task = node.task_template
            if parent_result and "{parent_result}" in task:
                task = task.replace("{parent_result}", json.dumps(parent_result))
            agent_result = self._spawn_and_wait(task, node, workflow.workflow_id)
            result.node_results[node.node_id] = agent_result
            return agent_result

    def _spawn_and_wait(self, task, node, workflow_id):
        """创建子agent并等待结果"""
        # ... 调用 SpawnSubagentTool 的 execute 异步方法
        pass

    def get_result(self, workflow_id: str) -> Optional[WorkflowResult]:
        return self._running.get(workflow_id)

    def cancel(self, workflow_id: str) -> bool:
        """取消工作流"""
        if workflow_id in self._running:
            self._running[workflow_id].status = "cancelled"
            return True
        return False
```

**LLM 可见的工具接口**：

```python
class ExecuteWorkflowTool(BaseTool):
    """执行预定义的工作流模板"""

    @property
    def name(self) -> str:
        return "execute_workflow"

    @property
    def description(self) -> str:
        return (
            "执行一个agent工作流。支持三种模式：\n"
            "1. 'simple': 单个子agent执行单一任务\n"
            "2. 'parallel': 并行执行多个子agent处理独立子任务\n"
            "3. 'pipeline': 串行执行多个子agent，前一个的输出传给下一个\n"
            "工作流在后台异步执行，用 get_workflow_status 查询进度。"
        )

    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "工作流名称"},
                "mode": {
                    "type": "string",
                    "enum": ["simple", "parallel", "pipeline"],
                    "description": "工作流模式",
                },
                "tasks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "task": {"type": "string", "description": "任务描述"},
                            "tools": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["task"],
                    },
                    "description": "任务列表",
                },
            },
            "required": ["name", "mode", "tasks"],
        }
```

**影响范围**：新增 `skills/task_delegator/workflow.py`、`skills/task_delegator/orchestrator.py`
**工作量**：约 8-10 小时

---

### 2.5 缺少可观测性层

**当前问题**：仅有基础 `logging`，缺少：
- 结构化日志（便于机器分析和可视化）
- Token 消耗追踪（每次 LLM 调用的 token 数）
- 工具调用延迟统计
- 子 agent 执行的全链路追踪
- 调用次数 / 成功率 / 错误率统计

**建议方案**：引入轻量级可观测性装饰器

```python
import time
import functools
from dataclasses import dataclass, field
from typing import List, Dict, Optional


@dataclass
class Span:
    """一次操作的追踪记录"""
    operation: str
    start_time: float
    end_time: Optional[float] = None
    status: str = "running"  # running / success / error
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    @property
    def duration_ms(self) -> float:
        if self.end_time:
            return (self.end_time - self.start_time) * 1000
        return 0


class Observability:
    """轻量级可观测性收集器"""

    def __init__(self):
        self.spans: List[Span] = []
        self._counters: Dict[str, int] = {}
        self._gauges: Dict[str, float] = {}

    def start_span(self, operation: str, **metadata) -> Span:
        span = Span(operation=operation, start_time=time.time(), metadata=metadata)
        self.spans.append(span)
        return span

    def end_span(self, span: Span, error: Optional[str] = None):
        span.end_time = time.time()
        span.status = "error" if error else "success"
        span.error = error

    def increment(self, metric: str, value: int = 1):
        self._counters[metric] = self._counters.get(metric, 0) + value

    def set_gauge(self, metric: str, value: float):
        self._gauges[metric] = value

    def get_summary(self) -> Dict[str, Any]:
        return {
            "total_spans": len(self.spans),
            "active_spans": sum(1 for s in self.spans if s.status == "running"),
            "success_spans": sum(1 for s in self.spans if s.status == "success"),
            "error_spans": sum(1 for s in self.spans if s.status == "error"),
            "avg_duration_ms": sum(s.duration_ms for s in self.spans if s.end_time) /
                               max(1, sum(1 for s in self.spans if s.end_time)),
            "counters": self._counters.copy(),
            "gauges": self._gauges.copy(),
        }


# 全局观测实例
_observability = Observability()


def observe(operation: str):
    """可观测性装饰器 —— 自动追踪函数调用的耗时和状态"""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            span = _observability.start_span(operation, args=str(args)[:200], kwargs=str(kwargs)[:200])
            try:
                result = func(*args, **kwargs)
                _observability.end_span(span)
                _observability.increment(f"{operation}.success")
                return result
            except Exception as e:
                _observability.end_span(span, error=str(e))
                _observability.increment(f"{operation}.error")
                raise
        return wrapper
    return decorator


def get_observability() -> Observability:
    return _observability
```

**使用示例**：

```python
@observe("chat_with_tools")
def chat_with_tools(self, message, tools, history):
    ...

@observe("spawn_subagent")
def execute(self, **kwargs):
    ...
```

**影响范围**：新增 `utils/observability.py`，关键方法加 `@observe` 装饰器
**工作量**：约 3-4 小时

---

### 2.6 记忆系统与 LLM 客户端紧耦合

**当前问题**：`MemoryManager` 直接依赖 `LLMClient` 做摘要提取，`ConversationManager` 依赖 `MemoryManager`，三个组件存在相互引用。测试困难，无法替换摘要策略。

**建议方案**：引入摘要器抽象

```python
from typing import Protocol, List, Dict


class Summarizer(Protocol):
    """摘要器接口 —— 从消息列表生成摘要"""

    def summarize(self, messages: List[Dict[str, str]],
                  max_length: int = 500) -> str:
        ...

    def extract_facts(self, content: str) -> List[str]:
        ...


class LLMSummarizer:
    """基于 LLM 的摘要器"""

    def __init__(self, client: "LLMClient"):
        self.client = client

    def summarize(self, messages, max_length=500) -> str:
        prompt = f"请用不超过{max_length}字总结以下对话：\n"
        for msg in messages:
            prompt += f"{msg['role']}: {msg['content']}\n"
        return self.client.chat(prompt)

    def extract_facts(self, content) -> List[str]:
        prompt = f"从以下内容提取关键事实：\n{content}"
        response = self.client.chat(prompt)
        return [line.strip("- ") for line in response.split("\n") if line.strip()]


class RuleSummarizer:
    """基于规则的降级摘要器（不依赖 LLM）"""

    def summarize(self, messages, max_length=500) -> str:
        # 简单截取前几条消息
        parts = []
        for msg in messages[:5]:
            text = msg["content"][:100]
            parts.append(f"- {msg['role']}: {text}")
        return "\n".join(parts)

    def extract_facts(self, content) -> List[str]:
        return []
```

**影响范围**：`memory/manager.py`、`memory/extractor.py`
**工作量**：约 2-3 小时

---

### 2.7 其他小优化

| 问题 | 建议 |
|------|------|
| **硬编码的 User-Agent/配置路径** | 提取到 config 或常量模块 |
| **单例模式滥用** | `Storage` 和 `ToolRegistry` 使用 `__new__` 单例，测试时需要 mock 重置。改用显式注入 |
| **文件操作无原子性** | `MemoryStorage` 的文件读写没有锁或原子写入（先写 tmp 再 rename），并发场景有风险 |
| **异常处理粒度不均** | 部分 `try/except Exception` 过于宽泛，应捕获具体异常类型 |
| **CLI 命令组分散** | `memory`/`skills`/`schedule` 命令组都在 `cli.py` 一个文件（~450 行），应拆分为独立模块 |

---

## 3. 功能缺口与优先级

### P0（基础设施，需尽快实施）

| 功能 | 说明 | 关联优化 |
|------|------|----------|
| **子 Agent 异步执行** | spawn 后立即返回，轮询获取结果 | §2.3 |
| **并行子 Agent** | 同时 spawn 多个子 agent，汇总结果 | §2.3 |
| **Agent 工作流** | DAG 编排多个子 agent 的串行/并行/条件执行 | §2.4 |

### P1（短期内重要，显著提升能力）

| 功能 | 说明 |
|------|------|
| **RAG / 本地知识库** | 索引本地文档（PDF/Markdown/代码仓库），基于向量检索增强生成 |
| **Agent 自优化** | 根据历史任务成功率，自动调整 system prompt / 工具选择 / 模型参数 |
| **对话分叉** | 在对话任意点 fork 出新分支，探索不同回答方向 |
| **Token & 成本追踪仪表盘** | GUI 实时显示每次对话和子 agent 的 token 消耗与费用估算 |
| **Agent 间通信** | 子 agent 之间可直接传递消息和结果（同级通信，不只是父子） |

### P2（中期规划，丰富生态）

| 功能 | 说明 |
|------|------|
| **Web UI** | FastAPI + WebSocket + 前端（React/Vue），替代 PyQt6，支持远程访问 |
| **后台持久 Agent** | 常驻后台 agent，监听事件（邮件/日历/webhook）主动触发 |
| **Agent 模板市场** | 保存和分享 agent 配置、skill 组合、workflow 模板 |
| **多用户隔离** | 用户身份认证、独立记忆空间、权限控制 |
| **模型智能路由** | 根据任务复杂度自动选择模型（简单任务用便宜模型） |

### P3（长期愿景）

| 功能 | 说明 |
|------|------|
| **Agent 协作网络** | 多个 vermilion-bird 实例之间互相发现和委托任务 |
| **代码执行沙箱** | Docker 容器隔离执行不受信任的代码 |
| **自主学习** | Agent 在空闲时主动探索知识、优化自身配置 |
| **多模态** | 图片理解/生成（GPT-4V / DALL-E / Stable Diffusion） |
| **语音交互** | STT/TTS 集成（Whisper + Edge-TTS） |

---

## 4. 实施路线图

### 阶段 1：异步子 Agent + 工作流（1-2 周）

```
目标：子 Agent 从同步阻塞改为异步并行，支持简单工作流

1. SubAgentRegistry 增加 Future 追踪（§2.3）
2. SpawnSubagentTool 改为异步执行（§2.3）
3. 实现 AgentWorkflow + WorkflowExecutor（§2.4）
4. 添加 execute_workflow 工具供 LLM 调用
5. 测试：2 个并行 web_search → 1 个汇总 writer
```

### 阶段 2：架构清理 + 可观测性（1 周）

```
目标：降低耦合，增加诊断能力

1. App 拆分为 AppBuilder（§2.1）
2. Conversation 引入 MessagePipeline（§2.2）
3. 引入 Observability 模块（§2.5）
4. 关键节点添加 @observe 装饰器
5. 添加 /health 端点输出详细诊断数据
```

### 阶段 3：RAG + 本地知识库（1-2 周）

```
目标：Agent 能检索用户本地文档

1. 集成向量数据库（ChromaDB / LanceDB）
2. 文档摄取 Pipeline（PDF / Markdown / 代码文件）
3. 新增 document_indexer skill
4. 记忆系统与 RAG 融合（记忆 搜索 → 知识库搜索）
```

### 阶段 4：自优化 + 仪表盘（1 周）

```
目标：Agent 越用越聪明

1. 收集任务成功率、工具偏好数据
2. 实现 prompt 自动优化（基于成功/失败案例）
3. GUI 添加 Token 用量和成本图表
```

### 阶段 5：Web UI + 共享生态（2-3 周）

```
目标：从单机走向网络

1. FastAPI + WebSocket 后端
2. 前端 SPA（流式响应、对话管理、仪表盘）
3. Agent 模板导入/导出/分享
```

---

## 附录：文件变更清单

| 阶段 | 文件 | 操作 |
|------|------|------|
| 1 | `skills/task_delegator/registry.py` | 修改：增加 Future 追踪 |
| 1 | `skills/task_delegator/tools.py` | 修改：SpawnSubagentTool 异步化 |
| 1 | `skills/task_delegator/workflow.py` | **新增**：AgentWorkflow + WorkflowExecutor |
| 1 | `skills/task_delegator/orchestrator.py` | **新增**：WorkflowOrchestrator + 工具定义 |
| 2 | `app.py` → `app.py` + `app_builder.py` | 拆分：App 精简 + AppBuilder |
| 2 | `conversation.py` → `pipeline/` | 新增：PipelineStage 各实现 |
| 2 | `utils/observability.py` | **新增**：Observability + @observe |
| 3 | `skills/document_indexer/` | **新增**：文档索引 skill |
| 3 | `rag/` | **新增**：RAG 检索模块 |
| 4 | `memory/optimizer.py` | **新增**：自优化逻辑 |
| 4 | `frontends/gui.py` | 修改：Token 仪表盘 |
| 5 | `frontends/web/` | **新增**：Web UI 前后端 |
