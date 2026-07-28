# 任务计划与资源授权

## 版本化计划

可通过重复的 `--step` 快速创建简单计划：

```bash
vermilion-bird task plan create <work-item-id> \
  --summary "先分析、再复核、最后交付" \
  --step "分析代码" \
  --step "复核风险" \
  --step "生成报告"
```

复杂计划建议使用 YAML：

```yaml
steps:
  - id: audit
    title: 分析代码
    description: 定位架构边界和最高优先级风险
    required_capabilities: [read]
  - id: report
    title: 生成报告
    depends_on: [audit]
    expected_artifact_kind: report
```

```bash
vermilion-bird task plan create <work-item-id> \
  --summary "架构审计计划" \
  --steps-file plan.yaml
vermilion-bird task plan show <work-item-id>
vermilion-bird task plan approve <work-item-id> <plan-id>
vermilion-bird task plan history <work-item-id>
```

新修订不会修改旧版本。只有最新修订能被批准，只有批准版本会成为任务执行上下文。
GUI 任务中心的“计划”页可以查看步骤并批准当前草稿。

## 资源级授权

目录授权示例：

```bash
vermilion-bird task grant add <work-item-id> \
  --capability workspace_write \
  --resource-type directory \
  --resource /workspace/project/reports \
  --scope work_item \
  --expires-hours 8 \
  --reason "允许当前任务更新报告"
```

一次性消息授权示例：

```bash
vermilion-bird task grant add <work-item-id> \
  --capability external_message \
  --resource-type message_target \
  --resource team@example.com \
  --scope once
```

```bash
vermilion-bird task grant list <work-item-id>
vermilion-bird task grant list <work-item-id> --all
vermilion-bird task grant revoke <grant-id>
```

授权不是通配的“永久允许”。能力和资源类型必须匹配，目录只能覆盖其自身与子路径，
域名只能覆盖同域及子域，消息目标要求精确匹配。参数含糊、超出边界、授权过期或涉及
进程/密钥能力时，动作仍进入审批中心。
