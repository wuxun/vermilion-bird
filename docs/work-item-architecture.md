# WorkItem 与 Artifact 架构

## 目标

`Run` 是可靠执行的技术事实，但不是用户理解一件工作的最佳抽象。`WorkItem` 将用户目标、
多次执行尝试、审批、副作用和最终产物聚合为一件可理解、可恢复、可复用的“任务”。

## 模型关系

```text
WorkItem
  ├── root_run_id ──────► 首次主 Run
  ├── latest_run_id ────► 当前主 Run
  ├── Run.work_item_id ─► 所有执行与子执行
  └── Artifact
        ├── work_item_id
        └── run_id（可选，精确追溯到生产该产物的执行）
```

- `WorkItem` 保存产品语义、当前状态投影和用户目标；
- `Run` 保存执行状态、事件、租约、checkpoint、重试和恢复；
- `ActionProposal`、`EffectRecord` 通过 `run_id` 间接归属 WorkItem；
- `Artifact` 是交付结果的事实来源，聊天文本只作为一种展示。

## 状态一致性

WorkItem 状态由 `latest_run_id` 对应的主 Run 投影：

| Run | WorkItem |
|---|---|
| pending | ready |
| running | running |
| waiting_approval | waiting_approval |
| paused | paused |
| completed | completed |
| failed | failed |
| cancelled | cancelled |

子 Run 的结束不会直接把整个任务标记为失败；主工作流可以处理子步骤失败。`WorkItemService`
订阅 RunEvent，只允许当前主 Run 更新任务状态。

SQLite 无法在一次事务内覆盖内存 RunManager 的状态变化，因此服务采用“持久化关联 +
幂等启动修复”关闭崩溃窗口：

1. Run 创建时先持久化 `work_item_id`；
2. WorkItem 随后更新 `root_run_id/latest_run_id`；
3. 如果进程在两步之间退出，启动时按 `Run.work_item_id` 找回主 Run 并修复投影。

这与 EffectOutbox 的处理原则一致：状态更新允许短暂不完整，但必须能够根据已落盘事实
确定性收敛。

## 幂等语义

- WorkItem 的 `idempotency_key` 防止同一外部触发创建两个用户任务；
- Run 的 `idempotency_key` 防止同一任务步骤重复执行；
- WorkItemService 不允许把已属于其他 WorkItem 的幂等 Run 重新挂载；
- Artifact 必须关联存在的 WorkItem；若填写 `run_id`，该 Run 必须属于同一 WorkItem。

## 模块边界

| 模块 | 职责 |
|---|---|
| `llm_chat.work.models` | WorkItem、Artifact 领域模型 |
| `llm_chat.work.service` | 应用用例、状态投影、启动修复 |
| `llm_chat.storage._work` | SQLite Repository 适配器 |
| `llm_chat.runtime` | Run 生命周期，不依赖 WorkItemService |
| `llm_chat.frontends` | 只调用 App/Application Service，不直接写 Repository |

Run Runtime 只增加通用的 `work_item_id` 归属字段。子 Run 在未显式指定时继承父 Run 的
WorkItem，从而避免 Tool、Subagent 和 Graph 节点产生孤立执行记录。

## 后续迁移

1. CLI 新增 `task start/list/show/cancel/retry/artifacts`；
2. Scheduler、Webhook、Proactive 显式创建 WorkItem；
3. GUI 新增任务中心，WorkItem 作为主视图，Run 时间线作为高级信息；
4. Artifact 扩展打开、校验、导出和“保存为 Workflow”能力。
