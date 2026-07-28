# ADR 0006：不可变 WorkflowDefinition 版本

- 状态：Accepted
- 日期：2026-07-28

## 决策

- 只有已完成且至少产生一个 Artifact 的 WorkItem 可生成 WorkflowDefinition。
- 如果来源 Artifact 已被评价，至少一个 Artifact 必须处于 `accepted`。
- WorkflowDefinition 是稳定身份；WorkflowVersion 是不可变执行快照。
- 修订通过新增版本完成，必须填写变更摘要，旧版本始终可查询和运行。
- 版本保存目标模板、参数、计划步骤、预期 Artifact、资源需求、预算、审批和失败策略。
- 从任务复制的是资源“需求”，不是资源“授权”；每次运行仍需独立授权或审批。
- 运行必须固定具体版本，并把版本 ID 写入新 WorkItem 元数据。
- 模板参数必须显式声明，缺失和未知输入均拒绝执行。

## 结果

成功任务可以被安全复用，同时保留执行时采用的精确版本。当前 GUI 和 Scheduler 的版本
选择入口仍待补齐，但它们应调用同一个 WorkflowService，不复制渲染或权限逻辑。
