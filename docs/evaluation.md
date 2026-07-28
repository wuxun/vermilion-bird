# 核心任务质量评测

评测对象是用户可感知的 `WorkItem`，而不是单次模型回复。评分读取持久化的任务、
Run、Artifact、审批和副作用事实，默认不会调用模型，也不会产生外部操作。

## 内置场景

`src/llm_chat/evaluation/core_scenarios.yaml` 是版本化的核心场景集，目前覆盖：

- 调研并形成报告；
- 本地工作区分析；
- 周期信息摘要。

每个场景声明期望终态、最低 Artifact 数量、可接受的 Artifact 类型、审批要求和最长
执行时间。场景应描述稳定的用户目标，避免绑定某个模型或 Prompt 的具体措辞。

## 使用

```bash
# 查看版本化场景
vermilion-bird eval list

# 对已有任务做确定性评分；不调用模型
vermilion-bird eval score research_report <work-item-id>

# 真实执行并评分；会调用当前模型和工具，可能产生费用
vermilion-bird eval run research_report

# 机器可读输出
vermilion-bird eval score research_report <work-item-id> --json-output
```

退出码为 `0` 表示通过，`1` 表示至少一项验收条件未通过。因此 `eval score` 可直接作为
CI 的回归门禁；实时 `eval run` 应放在显式启用、具备凭据和预算的测试环境中。

## 当前质量门禁

一个任务必须同时满足以下条件才算通过：

1. WorkItem 达到场景声明的终态；
2. Artifact 数量和类型满足交付要求；
3. 要求审批的场景存在已决策的审批记录；
4. 没有处于 `uncertain` 的外部副作用；
5. 在配置了时限时，主 Run 已结束且耗时不超过上限。

聚合报告给出完成率、Artifact 达标率、审批合规率、未知副作用数量和平均耗时。后续
增加成本和用户采纳反馈时，必须保持已有字段兼容，场景版本变更需在 YAML 中提升版本。

## 故障注入

`tests/fault_injection/` 独立覆盖以下崩溃窗口：

- WorkItem 或 Artifact 已提交，但调用方尚未收到成功响应；
- 取消或暂停请求已经持久化，但执行器尚未确认；
- 外部副作用可能已执行，但完成结果尚未持久化。

这些用例验证重试幂等、重启状态收敛，以及不确定副作用绝不自动重放。
