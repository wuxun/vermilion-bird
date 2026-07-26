# Vermilion Bird 产品与架构实施路线图

**状态**：执行中  
**起始版本**：v0.2.1  
**目标定位**：面向技术型知识工作者的、本地优先、可审计、可恢复的 AI 工作执行台。

## 1. 产品主线

Vermilion Bird 不再以“支持多少模型、工具和 Agent 模式”衡量进展，而以用户是否完成并
采纳了实际工作为核心。所有新能力必须服务于以下闭环：

```text
提出任务
  → AI 理解并给出计划
  → 用户确认权限和边界
  → 持久化执行
  → 交付可使用的结果或文件
  → 用户评价、修正
  → 保存为模板、自动任务或个人经验
```

北极星指标：

> 每位周活跃用户，每周成功完成并实际采纳的任务数。

首批核心场景：

1. 调研并形成报告；
2. 在明确授权下处理本地文件或代码；
3. 创建周期性的报告与信息摘要。

## 2. 领域模型

产品层不直接把底层 `Run` 暴露为主要对象：

| 模型 | 产品语义 | 事实来源 |
|---|---|---|
| `WorkItem` | 用户想完成的一件事，GUI 中称“任务” | WorkItem Repository |
| `Run` | 一次具体执行尝试、恢复或重放 | Run Runtime |
| `Artifact` | 报告、文件、代码、链接或外发消息等交付物 | Artifact Repository |
| `WorkflowDefinition` | 可重复执行的任务定义 | Workflow Repository |
| `ActionProposal` | 需要用户授权的外部动作 | Action Repository |
| `EffectRecord` | 外部副作用是否实际发生 | Effect Outbox |

代码采用 `WorkItem`，避免和 `scheduler.models.Task` 混淆。一个 WorkItem 可以关联多个
Run；Run 保留审计、租约、checkpoint、恢复与幂等语义。Artifact 不得只存在聊天文本中，
必须能独立查询、打开、校验和导出。

## 3. 版本路线

### v0.3：可信任务执行台

#### Phase 1：WorkItem 与 Artifact 基础

- [x] 新增 WorkItem、Artifact 模型及 Repository 端口
- [x] 新增 SQLite 表、索引和旧库增量迁移
- [x] Run 增加 `work_item_id`，子 Run 自动继承任务归属
- [x] 新增 WorkItemService，集中维护任务生命周期
- [x] 增加迁移、幂等、重启恢复与产物关联测试

验收条件：

- 一个任务可包含多次 Run；
- 失败恢复不会创建重复任务；
- Run、审批、副作用和产物能追溯到同一个任务；
- 旧数据库无损升级。

#### Phase 2：迁移生产入口

- [ ] GUI、CLI 支持显式创建任务
- [ ] Scheduler、Webhook、Proactive 通过 StartWorkItem 用例创建任务
- [ ] Subagent 和 Tool 子 Run 自动继承 WorkItem
- [ ] 对话模式与任务模式保持清晰区分

#### Phase 3：GUI 任务中心

- [ ] 任务列表与状态筛选
- [ ] 任务详情：概览、计划、审批、产物、时间线
- [ ] 暂停、取消、恢复、重试
- [ ] 将执行与审批中心保留为高级审计入口
- [ ] 增加 Qt 关键路径自动化测试

#### Phase 4：首次使用

- [ ] 模型连接向导与连接测试
- [ ] 默认工作目录和授权等级
- [ ] 三个安全的示例任务
- [ ] API Key 默认写入系统 Keychain
- [ ] 新用户十分钟内完成首个有效任务

#### Phase 5：发布可靠性

- [ ] 正式数据库 schema version 与迁移日志
- [ ] 升级前备份、失败回滚、诊断包
- [ ] GUI E2E 与进程崩溃故障注入
- [ ] macOS Developer ID 签名、公证和自动更新
- [ ] Windows/Linux 构建验证

### v0.4：任务复用与自动化

- [ ] 从成功任务生成 WorkflowDefinition
- [ ] Workflow 不可变版本与变更摘要
- [ ] 输入参数、产物定义、预算、审批和失败策略
- [ ] GUI、CLI、Scheduler 运行同一 Workflow 版本
- [ ] 资源级权限：目录、域名、消息目标和授权期限

进入下一阶段的门槛：核心任务成功率不低于 85%，成功任务能够稳定产出 Artifact。

### v0.5：质量评测与记忆治理

- [ ] 建立真实场景 Eval 数据集与基线
- [ ] 评估完成率、工具成功率、延迟、成本和产物采纳率
- [ ] Prompt、模型路由和 Context 策略变更进入 CI 回归
- [ ] 记忆来源、作用域、置信度、过期、纠正、删除和导出
- [ ] 模型推测不得直接晋升为长期事实

### v0.6：可控主动性

- [ ] 从重复任务和用户复用行为发现模式
- [ ] 只建议创建自动化，不默认自动创建
- [ ] 提醒频率、安静时段、冷却时间和全局关闭
- [ ] 建议原因、来源和边界可解释

进入条件：工作流复用率超过 20%，记忆治理稳定，主动建议可完整撤销。

### v1.0：平台化

- [ ] 稳定 Ember 公共 API 与语义化版本
- [ ] 插件 manifest、兼容性和能力声明
- [ ] 第三方 Tool、ContextProvider、Frontend SDK
- [ ] 正式跨平台发行
- [ ] 产品验证后再评估团队协作、云同步和插件市场

## 4. 架构守护规则

1. LangGraph 负责节点执行、interrupt 和 checkpoint。
2. Run Runtime 负责审计、租约、恢复、取消和幂等。
3. WorkItem 是产品聚合，Run 是执行尝试，Artifact 是结果事实来源。
4. GUI 不直接访问 Repository，所有状态改变通过 Application Service。
5. 子 Run 必须继承父 Run 的 WorkItem，除非显式创建新的用户任务。
6. 数据库变更必须有旧库升级测试。
7. 新功能必须有产品验收指标或 Eval。
8. 不确定副作用永不自动重放。
9. 不整体迁移到 LangChain；LangGraph 保持基础设施适配器边界。
10. 不以新增模型、Agent 数量或工具调用次数作为产品进展指标。

## 5. 暂缓项

在核心任务成功率、复用率和记忆治理达到门槛前，暂缓：

- 新增更多模型供应商；
- 新增多 Agent 协作模式；
- 完全自主执行和动态 Soul；
- Agent/插件市场；
- 云端团队协作；
- 自建向量数据库；
- 整体切换 LangChain；
- 大规模重写 PyQt 前端。

## 6. v0.3 提交与验收顺序

1. `docs: define product architecture roadmap`
2. `feat: add work item and artifact domain models`
3. `feat: persist work items and artifacts`
4. `feat: bind runs to work items`
5. `feat: add work item application service`
6. `feat: expose task lifecycle through cli`
7. `feat: add task center gui`
8. `test: cover work item recovery and migrations`
9. `build: package and verify task center`

每个阶段都必须保持全量测试通过、数据库向前兼容，并产生一个可以独立验收的提交。
