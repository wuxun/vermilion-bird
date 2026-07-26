# Vermilion Bird 架构收敛计划

**状态**：本轮收敛完成（2026-07-26）
**目标**：将现有能力收敛为“触发 → 理解 → 决策 → 授权 → 执行 → 学习”的本地优先决策与行动助手。

## 0. 本轮交付结果

| 方向 | 已落地 |
|---|---|
| 可靠性 | 修复上下文压缩、Graph 工具循环、SQLite 外键/FTS、Webhook 输入、模型 fallback 和配置 round-trip |
| Run Runtime | Chat、Tool、Workflow、Scheduler、Webhook、Proactive 统一创建父子 Run 并记录有序事件 |
| 可恢复执行 | Run attempt、恢复策略、幂等键、租约和检查点指针持久化；LangGraph + SQLite 承担应用图检查点 |
| 授权 | CapabilityPolicy + ActionProposal 状态机；副作用工具默认停在 durable interrupt，批准后才恢复执行 |
| Context Hub | memory、knowledge、历史、指令和技能上下文统一为 ContextItem，集中去重、排序和预算裁剪 |
| Agent/Workflow | Ghost/Role 收敛到 AgentProfile，Pattern 收敛到 WorkflowSpec，并保留兼容视图 |
| 模块边界 | GUI、飞书、浏览器、安全存储、中文检索和语义知识改为可选 extras；可选适配器延迟导入 |
| 运行可靠性 | Scheduler 恢复持久化任务、统一业务库路径、支持 interval；飞书生命周期、限流和会话映射补齐 |

Run 与 ActionProposal 已由 SQLite 持久化，GUI 执行中心支持审批、恢复、重试和重放。
产品级 Run 是身份、审计、租约和恢复策略的事实来源；LangGraph checkpoint 是节点状态的
事实来源，外层 Run 只保存 checkpoint 指针，不复制完整图状态。

## 1. 产品与架构原则

1. **对话是入口，不是边界**：GUI、CLI、飞书、Webhook 和定时任务都通过应用用例提交一次运行。
2. **每次工作都是 Run**：对话、工具、工作流、定时任务和主动任务共享状态、事件、预算、取消和审计模型。
3. **副作用先授权**：文件写入、Shell、外部消息、长期记忆修改和高成本工作流统一生成 ActionProposal。
4. **Agent 是实现细节**：Ghost、Role 和 Pattern 分别收敛为 AgentProfile、Profile 片段和 WorkflowSpec 模板。
5. **上下文统一治理**：记忆、知识、摘要和指令最终统一为带来源、范围、置信度、敏感级别和生命周期的 ContextItem。
6. **应用依赖抽象，基础设施实现抽象**：协议、SQLite、MCP、PyQt、飞书、APScheduler 都位于适配器边界。
7. **不以“文件已存在”作为完成标准**：每项迁移必须有唯一生产入口、回归测试和可观察的验收条件。

## 2. 目标分层

```text
Interfaces
  GUI / CLI / Feishu / HTTP
        │
Application Use Cases
  SendMessage / StartRun / HandleTrigger / ApproveAction / CancelRun
        │
Domain
  Run / ActionProposal / ContextItem / AgentProfile / WorkflowSpec
        │
Runtime Ports
  ModelPort / CapabilityPort / ContextPort / EventStore / RunRepository / GraphRuntime
        │
Infrastructure Adapters
  OpenAI/Anthropic/Gemini / MCP/Skills / SQLite/Files / LangGraph / APScheduler / PyQt/Feishu
```

依赖只允许从上向下指向抽象；基础设施通过组合根注入，领域层不得访问全局单例、线程局部变量或 UI 回调。

## 3. 核心领域模型

### Run

统一描述一次实际执行：

- `id`, `parent_run_id`, `type`, `status`
- 输入、结果、错误和产物
- 模型策略、能力策略
- token、成本、时间和工具调用预算
- 取消令牌
- 有序事件流

### ActionProposal

统一描述需要用户授权的副作用：

- 动作、理由、工具和权限
- 预期影响、风险、成本
- 是否可撤销
- `pending / approved / rejected / executing / completed / failed`
- 执行结果和审计记录

现有 DecisionCard 在迁移期作为 ActionProposal 的“多方案决策视图”，不再承担工具传输、GUI 展示和持久化三套不同语义。

### ContextItem

统一描述可检索上下文：

- `kind`: user_fact / preference / domain_fact / instruction / summary
- `scope`: user / conversation / project / domain
- 来源、置信度、敏感级别、创建时间和过期时间
- 关键词、embedding 和版本

短中长期记忆、领域知识和会话摘要保留为策略或投影视图，不再分别维护检索、去重和生命周期框架。

### AgentProfile 与 WorkflowSpec

- `AgentProfile`：指令、模型策略、上下文策略、能力策略和输出约束。
- `WorkflowSpec`：节点、依赖、聚合方式和预算。
- Ghost 是可编辑的 AgentProfile；Role 是 Profile 片段；Pattern 是 WorkflowSpec 模板。

## 4. 分阶段迁移

### Phase 0：可靠性基线

**结果：已完成。**

- 修复上下文压缩、工具循环、SQLite FTS/外键、Webhook 和模型 fallback。
- 将工具“白名单”改为真正的能力交集。
- 所有修复必须增加回归测试。
- 建立可通过的核心测试集；把真实网络测试改为显式 integration marker。

**验收条件**

- 上下文超阈值时能稳定压缩且不会静默降级。
- 工具循环在预算内终止，禁用工具时不暴露任何工具。
- FTS 插入、更新、删除同步；级联删除无孤儿数据。
- Webhook payload 能进入实际执行输入。
- 子 Agent 不会获得未声明能力。

### Phase 1：统一 Run Runtime

**结果：持久化单机运行时与 LangGraph 适配器已完成。**

- 新增独立、无单例的 RunRepository、RunEventBus 和 CancellationToken。
- 首先迁移 ChatCoreGraph，再迁移子 Agent，最后迁移 Scheduler/Webhook/Proactive。
- Graph 只负责节点编排；Run Runtime 负责生命周期、预算、取消和事件。
- UI 由 RunEvent 驱动，不再依赖模块级 thread-local 和散落回调。
- 主对话编排使用 LangGraph；工具审批使用 SQLite checkpointer 和 interrupt/resume。
- ChatGraph state 已完全可序列化，运行时依赖通过 context 注入；失败后可跨进程从
  SQLite checkpoint 重试。
- RunHandlerRegistry/Dispatcher 已统一 Chat、通用 Graph、审批和 Scheduler 的
  resume/retry/replay 路由，GUI 直接读取 handler 能力。
- SchedulerService 已收敛到 TaskExecutor，不再维护第二套 Run/重试/通知生命周期。
- 会话消息写入具有稳定执行幂等键，节点重入不会重复落库。
- ember-core 的轻量 StateGraph 继续服务零依赖基础包，不作为桌面应用的第二套生产运行时。

**验收条件**

- 所有生产入口都产生可查询的 Run。
- 任意 Run 可取消、可设置预算并能展示失败节点。
- 中断的工具审批在关闭应用后仍可从同一 checkpoint 恢复。
- 同一幂等键不会创建两次逻辑 Run，多进程租约不会重复认领执行。
- 父子 Run 关系能够覆盖多 Agent 工作流。

### Phase 2：统一授权

**结果：已完成。**

- 引入 ActionProposal 和 CapabilityPolicy。
- 能力按 `read / workspace_write / process / network / external_message / secrets` 分类。
- 文件写入、Shell、外发消息、长期记忆写入和自动任务创建默认要求策略允许或用户审批。
- DecisionCard 迁移为 ActionProposal 的决策视图。

**验收条件**

- 每个副作用都能追溯到策略判断或用户批准。
- 拒绝、修改和批准走相同状态机。

### Phase 3：Context Hub

**结果：统一读取与注入链路已完成。**

- 引入 ContextItem 与统一检索接口。
- 逐步迁移 memory、knowledge 和 context cache。
- 增加来源、纠正、遗忘、敏感数据和导出能力。
- Markdown 文件保留为可读投影视图。

### Phase 4：模块化交付

**结果：已完成。**

- 将 GUI、飞书、语义 embedding、浏览器和开发者 Shell 设为可选 extras/adapters。
- 稳定 Ember API 后再独立发布；此前保持 monorepo 原子版本。
- 延后 Agent 市场、跨实例网络和自主学习。

## 5. 架构守护规则

后续 CI 应自动检查：

- 应用层只有一个发送消息生产入口。
- Scheduler、Webhook、Proactive 不得直接实现 LLM/工具循环。
- Core/Domain 不得新增进程级可变单例。
- `llm_chat` 的生产图不得重新依赖 ember-core StateGraph；必须经过 GraphRuntime 端口。
- Run checkpoint 只保存图指针，不得复制 LangGraph 的完整 state。
- 每个线程池、客户端和后台服务都有显式生命周期。
- 每个包可独立安装、导入和运行测试。
- 配置 YAML round-trip 不丢字段。
- 单元测试默认不访问真实网络、不写用户主目录。
