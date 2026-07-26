# 持久化 Run 与 GUI 执行/审批中心

## 目标

所有聊天、工具、工作流、定时任务、Webhook 和主动任务都使用统一的 `Run` 生命周期。
运行历史与高风险动作审批写入 SQLite，因此应用重启后仍然可审计，不会因为进程退出
丢失待审批事项。

## 数据模型

SQLite 新增四张表：

| 表 | 用途 |
|---|---|
| `runs` | Run 类型、状态、输入、输出、错误、父子关系和时间 |
| `run_events` | 每个 Run 内严格递增的事件时间线 |
| `action_proposals` | 工具、参数、能力、风险、影响和审批结果 |
| `effect_outbox` | 副作用执行意图、幂等键、结果与不确定状态 |

`RunManager` 和 `ActionProposalManager` 只依赖最小 Repository 协议，应用层将现有
`Storage` 注入其中。未注入 Repository 时仍可作为纯内存组件使用，便于独立复用和测试。

## 重启语义

- 已完成、失败或取消的 Run 原样恢复。
- `RecoveryPolicy.RESUME` 且已有 checkpoint 的 Chat/Graph Run 会恢复为 `paused`，
  可从原 LangGraph 节点继续；没有恢复点的中断 Run 会安全失败。
- `RecoveryPolicy.RETRY` 的定时任务会恢复为可重试状态，不会静默重复执行。
- 启动阶段由 `RunRecoveryCoordinator` 自动恢复安全的 Chat/Graph checkpoint，并重试
  标记为可重试的 Scheduler/Subagent Run；审批动作不会被自动恢复。
- 运行中的 Chat/Graph 由 `RunLeaseHeartbeat` 续租，避免长调用的租约过期后被其他
  worker 重复认领。
- `pending` 动作审批保持待审批，可以在新进程中继续批准或拒绝。
- 副作用执行前先写入 `effect_outbox`；崩溃时处于 `executing` 的记录会转为
  `uncertain`，等待人工对账，不会自动重放。
- 已完成副作用再次使用相同 effect key 时直接复用持久化结果。
- 相同审批只能从 `pending` 原子地进入执行状态，并发点击不会重复执行。
- Chat 用户消息和助手消息使用 `run_id + role` 幂等键，节点重入不会重复写入会话。
- Chat checkpoint 带显式 `schema_version`；旧版无版本状态按当前初始版本读取，
  高于当前程序支持范围的状态会拒绝执行。

## 执行分发

`RunDispatcher` 根据 `run.metadata.run_handler` 将恢复、重试和重放交给唯一 handler：

| handler | 用途 | 支持操作 |
|---|---|---|
| `chat` | 主 ChatGraph + SQLite checkpoint | 恢复、重试、重放 |
| `graph` | 通用 LangGraph 工作流 | 恢复、重试、重放 |
| `action` | 高风险工具审批图 | 仅恢复审批，不允许重试/重放副作用 |
| `scheduled` | Scheduler/Webhook/Proactive 外层任务 | 重试、重放 |
| `subagent` | 子 Agent 后台任务 | 重试、重放 |

GUI 不再猜测 Run 类型，而是调用应用层 `can_resume_run()`、`can_retry_run()` 和
`can_replay_run()` 获取 handler 的实际能力。

## GUI 使用

点击主窗口顶栏的 `🧭`，或按 `Ctrl+Shift+R` 打开中心。顶栏会显示当前待审批数量。

“运行记录”页支持：

- 按 Run 类型和状态筛选最近记录；
- 查看输入、输出、错误、元数据和耗时；
- 查看按序号排列的完整事件时间线；
- 查看父 Run、会话和 Run ID，便于串联聊天、工作流与工具子任务。
- 查看恢复 handler、恢复动作、checkpoint 版本、租约持有者、到期时间和最后心跳。

“审批”页支持：

- 查看工具名称、风险、所需能力、原因、影响和完整参数；
- 明确确认后在后台线程执行，避免阻塞 GUI；
- 拒绝动作并记录到来源 Run；
- 实时响应运行期事件，并以定时刷新作为断线兜底。

## 安全边界

GUI 不直接绕过策略执行工具。批准操作统一调用应用层 `approve_action()`，再由
`DurableActionCoordinator` 校验状态和会话归属、恢复审批图，再使用共享
`ToolRegistry` 执行。审批记录和执行 Run 会分别持久化，形成完整审计链。
实际副作用还会经过 `EffectOutbox`，将“已批准”与“已经产生外部效果”拆成两个可对账状态。
