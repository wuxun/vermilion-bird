# Vermilion Bird 产品与架构实施路线图

**状态**：执行中  
**起始版本**：v0.2.1  
**目标定位**：面向技术型知识工作者的、本地优先、可审计、可恢复的 AI 工作执行台。

产品定位、首批用户、差异化、阶段门槛和停止项以
[产品战略 2026](product-strategy-2026.md) 为上位决策。本文负责记录可验收的实现状态；
当愿景文档与本文冲突时，以产品战略和本文的较新决策为准。

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

当前战略约束：先完成“验收后的 Artifact → Workflow → 重复运行”飞轮，再扩展主动性和
平台生态。产品指标默认仅在本地持久化，任何远程遥测必须显式 opt-in。

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

- [x] GUI、CLI 支持显式创建任务
- [x] Scheduler、Webhook、Proactive 通过 WorkItemService 创建任务
- [x] Subagent 和 Tool 子 Run 自动继承 WorkItem
- [x] 对话模式与任务模式保持清晰区分

#### Phase 3：GUI 任务中心

- [x] 任务列表与状态筛选
- [x] 任务详情：概览、执行和产物
- [x] 任务详情：结构化计划
- [x] 任务详情：内嵌审批
- [x] 取消和重试
- [x] 从持久化检查点恢复
- [ ] 主动暂停（需执行器协作式暂停）
- [x] 将执行与审批中心保留为高级审计入口
- [x] 增加 Qt 关键路径自动化测试

#### Phase 4：首次使用（暂缓）

- [ ] 模型连接向导与连接测试
- [ ] 默认工作目录和授权等级
- [ ] 三个安全的示例任务
- [ ] API Key 默认写入系统 Keychain
- [ ] 新用户十分钟内完成首个有效任务

> 2026-07-28 决策：当前阶段暂缓首次使用改造，优先消除执行控制、数据迁移和质量评测
> 风险。首次使用在核心执行闭环达到发布门槛后恢复。

#### Phase 5：执行与发布可靠性

- [x] 协作式取消：请求、执行器确认、子 Run 级联、终态收敛
- [x] Chat 任务协作式暂停：安全点 checkpoint、确认暂停、恢复
- [ ] 为其他可恢复 Workflow handler 扩展协作式暂停
- [x] 正式数据库 schema version 与迁移日志
- [x] 升级前 WAL 一致备份与失败恢复
- [ ] 一键诊断包（迁移失败 sidecar 已完成）
- [ ] GUI E2E
- [x] 进程崩溃故障注入：提交后崩溃、控制请求恢复、副作用禁止重放
- [x] 版本化结构化计划：步骤依赖、显式批准、旧版本审计保留
- [x] 资源级授权执行：目录、域名、消息目标、期限与撤销
- [ ] macOS Developer ID 签名、公证和自动更新
- [ ] Windows/Linux 构建验证

实施顺序：

1. 协作式取消和暂停；
2. schema version、升级备份与失败恢复；
3. 故障注入与核心场景 Eval；
4. 结构化计划和资源级授权；
5. Artifact 反馈、导出和 WorkflowDefinition；
6. Application Service、状态投影和 Ember 边界收敛。

当前进度：

- [x] WorkItem、Workflow、ResourceGrant 形成独立 Application Service
- [x] WorkItem 状态统一从 Run 事实投影
- [x] Ember 依赖方向加入可执行架构边界测试
- [x] LangGraph 保持在应用运行时，不进入 Ember 公共 API
- [x] Codex 式统一工作线程、渐进目标模式与任务时间线
- [x] 状态主操作、统一创建表单和终态任务 follow-up
- [x] 任务内计划确认、审批与交付验收渐进展示
- [x] TaskWorkspace 只读投影层与统一待处理范围
- [x] 单列任务流、全文筛选和全局待处理导航提示
- [x] 自动化系列聚合：同一 Scheduler/Webhook/Proactive 定义复用一个 WorkItem
- [x] 注意力治理：必须处理、新结果和无需反馈分级
- [x] 旧自动化记录按来源折叠，导航待办不再包含普通自动化结果
- [x] Codex-like Shell V2：单侧栏、深色任务画布、卡片式 Composer
- [x] 对话、任务、执行中心和决策卡片统一设计令牌
- [x] 工具执行默认折叠，低频能力改为渐进式入口
- [x] 当前对话可原地升级为 WorkItem，并复用历史、Run 和 Artifact
- [x] 任务中心降级为跨对话工作概览，消除两套内容入口

### v0.4：任务复用与自动化

- [x] Artifact 原子导出、反馈历史与采纳率指标
- [x] 从成功任务生成 WorkflowDefinition
- [x] Workflow 不可变版本与变更摘要
- [x] 输入参数、产物定义、预算、审批和失败策略模型
- [x] CLI 固定版本执行并记录版本来源
- [ ] GUI、Scheduler 选择并运行同一 Workflow 版本
- [x] 资源级权限：目录、域名、消息目标和授权期限
- [x] 自动化结果验收策略：required/optional/none
- [x] 自动化任务编辑器可配置结果处理方式

进入下一阶段的门槛：核心任务成功率不低于 85%，成功任务能够稳定产出 Artifact。

### v0.4.1：可用结果闭环

- [ ] `ContextResource`：文件/目录来源、快照、hash、敏感等级和外发边界
- [ ] Composer 文件拖放、附件预览、上下文移除
- [ ] Artifact 不可变版本和派生关系
- [ ] Artifact 内嵌预览、版本 Diff、反馈和导出
- [ ] 原 WorkItem 内修订并产生可追溯的新 Artifact 版本
- [x] 隐私友好的本地 Product Event Store（无 Prompt/正文/路径，默认不上传）
- [ ] 从持久化事实计算完成率、采用率、Workflow 转化率和重复成功率

验收条件：用户可以在一个连续流程中完成“加入资料 → 执行 → 验收/修改结果 → 导出 →
保存 Workflow”，且每个步骤都能回溯到同一 WorkItem。

### v0.5：质量评测与记忆治理

- [x] 建立版本化核心场景 Eval 数据集与确定性评分基线
- [ ] 评估完成率、工具成功率、延迟、成本和产物采纳率（完成率、延迟、采纳率已接入）
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
