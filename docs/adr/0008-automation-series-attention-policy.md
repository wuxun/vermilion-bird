# ADR 0008：自动化任务流与注意力策略

- 状态：Accepted
- 日期：2026-07-29

## 背景

Scheduler、Webhook 和 Proactive 每次触发都创建独立 WorkItem，导致周期任务长期刷屏。
同时，所有未反馈 Artifact 都被视为“待你处理”，普通自动化结果会持续扩大导航待办，
最终使提醒失去可信度。

## 决策

- WorkItem 增加可选 `series_key`。同一自动化定义使用稳定的
  `scheduler:{task_id}`，后续执行复用同一 WorkItem，并产生新的 Run 和 Artifact。
- `series_key` 使用部分唯一索引；普通一次性任务保持为空。
- WorkItem 增加 `artifact_review_policy`：
  - `required`：未反馈结果进入“待你处理”；
  - `optional`：结果进入“新结果”，不计入导航待办；
  - `none`：不产生注意力项，仅保留结果事实。
- Artifact 可通过 `metadata.review_policy` 覆盖任务级策略。
- 失败、计划确认和动作审批始终属于必须处理，不受 Artifact 策略影响。
- schema v8 为旧自动化记录设置 `optional`，并按 `scheduled_task_id` 选择最新记录作为
  系列主记录。历史 WorkItem 不删除，由任务查询投影折叠，高级审计入口仍可访问。

## 结果

周期执行不再持续增加一级任务数量；自动化结果与真正阻塞用户的事项拥有不同的信息层级。
任务导航数字恢复为可信的行动队列指标，同时保留完整 Run、Artifact 和旧 WorkItem 审计
事实。后续可在此基础上增加已读、稍后处理、批量确认和工作流级默认策略。
