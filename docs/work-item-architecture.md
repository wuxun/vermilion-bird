# WorkItem 与 Artifact 架构

## 目标

`Run` 是可靠执行的技术事实，但不是用户理解一件工作的最佳抽象。`WorkItem` 将用户目标、
多次执行尝试、审批、副作用和最终产物聚合为一件可理解、可恢复、可复用的“任务”。

## 模型关系

```text
WorkItem
  ├── root_run_id ──────► 首次主 Run
  ├── latest_run_id ────► 当前主 Run
  ├── series_key ───────► 可重复来源的稳定任务流
  ├── artifact_review_policy ─► required / optional / none
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

WorkItem 状态以 `latest_run_id` 对应的主 Run 为基线，并聚合会阻塞用户目标完成的子 Run：

| Run | WorkItem |
|---|---|
| pending | ready |
| running | running |
| cancel_requested | cancelling |
| pause_requested | pausing |
| waiting_approval | waiting_approval |
| paused | paused |
| completed | completed |
| failed | failed |
| cancelled | cancelled |

子 Run 的结束不会直接把整个任务标记为失败；主工作流可以处理子步骤失败。但待审批、
控制请求或仍在运行的阻塞型子 Run 会临时覆盖任务投影，避免出现“主 Run 已完成但外部
动作仍待审批”的错误产品状态。`WorkItemService` 订阅所有关联 RunEvent 并确定性重算
聚合状态。

SQLite 无法在一次事务内覆盖内存 RunManager 的状态变化，因此服务采用“持久化关联 +
幂等启动修复”关闭崩溃窗口：

1. Run 创建时先持久化 `work_item_id`；
2. WorkItem 随后更新 `root_run_id/latest_run_id`；
3. 如果进程在两步之间退出，启动时按 `Run.work_item_id` 找回主 Run 并修复投影。

这与 EffectOutbox 的处理原则一致：状态更新允许短暂不完整，但必须能够根据已落盘事实
确定性收敛。

## 幂等语义

- WorkItem 的 `idempotency_key` 防止同一外部触发创建两个用户任务；
- WorkItem 的 `series_key` 让同一 Scheduler、Webhook 或 Proactive 定义复用一个任务流；
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

已完成：

1. CLI 新增 `task start/list/show/cancel/retry/artifacts`；
2. Scheduler、Webhook、Proactive 显式创建并按 `series_key` 复用 WorkItem；
3. GUI 新增任务中心，WorkItem 作为主视图，Run 时间线作为高级信息；
4. 文本结果以幂等 Artifact 固化，文件和链接 Artifact 可从 GUI 打开。

下一步：

1. 完成 Workflow 库、版本选择和参数化运行界面；
2. 增加 Artifact 内嵌预览、版本对比和自动化结果已读状态；
3. 将协作式暂停扩展到非 Chat Workflow；
4. 为首次启动提供模型连接与安全示例任务。

任务中心已内嵌待审批动作，可查看风险、能力、影响和参数，并直接批准或拒绝。
已有 checkpoint 的暂停主 Run 可从 GUI 或 `task resume` 恢复。Chat 主任务支持
`running → pause_requested → paused` 的协作式暂停；其他 handler 只有在实现安全点和
checkpoint 后才会开放暂停，避免只修改数据库状态而后台线程仍继续执行。
