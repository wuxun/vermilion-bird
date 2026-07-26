# ADR-0001：应用层采用 LangGraph，保留 Ember 轻量内核

- **状态**：Accepted
- **日期**：2026-07-26

## 背景

项目原有 ember-core StateGraph、ember-agent WorkflowExecutor、产品级 Run 和审批状态机。
继续扩展自研图引擎的持久化、中断恢复、并发检查点和生态适配，会产生较高的长期维护成本；
但把存储、权限、GUI、会话、调度和 Agent 领域模型整体迁入 LangChain/LangGraph，又会把产品
边界绑定到框架类型。

## 决策

采用分层混合方案：

1. `llm_chat.runtime.GraphRuntime` 是应用层稳定端口。
2. `LangGraphRuntime` 是当前生产适配器，使用 SQLite checkpointer，禁用 pickle fallback。
3. 主 ChatCore 编排使用 LangGraph StateGraph。
4. 可恢复的工具审批使用 LangGraph `interrupt` / `Command(resume=...)`。
5. 产品级 `Run`、`ActionProposal`、CapabilityPolicy、SQLite 业务表和 GUI 继续由项目维护。
6. ember-core StateGraph 保持零 LangGraph/LLM 依赖，供独立包和确定性轻量场景使用。
7. ember-agent 的领域协作模型不直接暴露 LangGraph 类型；后续可通过 GraphRuntime 增加适配。
8. LangChain 不作为核心依赖抽象，仅允许在模型、工具或文档适配边界按需使用。
9. ChatGraph 的持久化 state 只包含 JSON 可序列化业务数据；客户端、存储、策略、回调和
   cancel event 通过 LangGraph runtime context 显式注入，不使用线程局部变量。
10. `RunHandlerRegistry` / `RunDispatcher` 是 GUI、CLI 和 Scheduler 的统一控制入口。

## 状态所有权

| 状态 | 唯一事实来源 |
|---|---|
| Run 身份、父子关系、attempt、租约、审计事件 | 产品 SQLite `runs` / `run_events` |
| 授权决定、动作状态、结果与错误 | 产品 SQLite `action_proposals` |
| 图节点 state、pending node、interrupt payload | LangGraph SQLite checkpoint |
| 外层恢复点 | Run 中的 `{graph_name, thread_id, checkpoint_id}` 指针 |

不得把 LangGraph 完整 state 再复制进 Run checkpoint。

## 副作用规则

- 产生副作用前必须先落 ActionProposal，并停在 durable interrupt。
- 批准只改变授权状态；工具执行发生在恢复后的图节点。
- 已完成 proposal 的正常重入直接返回已保存结果。
- 对处于 `executing` 时进程崩溃的动作，不承诺 exactly-once；因外部系统结果不确定，
  自动重试和直接重放均被禁止，必须重新发起并生成新的授权记录。
- 能支持幂等键的外部工具应使用 proposal ID 作为幂等键。
- 项目内会话消息使用 `run_id + role` 唯一执行键，覆盖 checkpoint 边界上的
  at-least-once 节点重入。

## 后果

收益：

- 获得成熟的 durable execution、checkpoint history 和 human-in-the-loop 语义。
- GUI/CLI/Chat 指令共用一条审批恢复链路。
- Chat、通用 Graph、审批和定时任务使用同一 Run 控制分发协议。
- 框架被限制在适配器和应用编排层，领域模型仍可替换、测试和独立演化。

代价：

- 根应用最低 Python 版本为 3.10；ember-core/ember-agent 仍可保持 Python 3.9。
- 打包需显式收集 LangGraph 子模块。
- 迁移期 ember-core StateGraph 与 LangGraph 会同时存在，但二者职责不同，不能形成同一用例的
  双生产路径。
