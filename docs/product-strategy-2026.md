# Vermilion Bird 产品战略 2026

**状态**：已批准，进入实施  
**更新时间**：2026-07-31  
**事实路线图**：[产品与架构实施路线图](product-architecture-roadmap.md)

## 1. 战略结论

Vermilion Bird 不以“更全的聊天客户端”或“更多 Agent 模式”为目标。项目要成为：

> 面向技术型知识工作者的、本地优先、可审计、可恢复，并能把一次成功协作沉淀为长期
> 自动化的个人 AI 工作运行台。

核心产品承诺是：

> 把一次满意的 AI 协作，转化为一个可验证、可重复、可定时运行、始终由用户掌控的工作流。

GUI 是用户监督和验收工作的驾驶舱；Ember 是在产品边界稳定后才对外开放的执行底座。
项目当前采取“应用验证框架”的顺序，不采取“先发布通用框架、再寻找场景”的顺序。

## 2. 首批用户与切入场景

首批目标用户是需要处理本地或私有资料，并周期性产出研究报告、技术判断、项目简报和
信息摘要的技术型知识工作者，包括技术负责人、独立开发者、技术咨询顾问、研究和产品
分析人员。

只优先验证三个黄金场景：

1. 基于网页和本地资料生成可引用、可修订的研究报告；
2. 审查本地项目并交付结构化分析或修改结果；
3. 周期性生成项目简报、技术情报或运营摘要。

项目不以模型、MCP、Skill、Agent 或工具数量作为用户价值。通用能力只有在提升上述场景
的完成率、结果采用率或复用率时才进入主路线。

## 3. 产品飞轮

```text
一次对话
  → 设置明确目标
  → 确认计划和资源边界
  → 持久化执行
  → 交付 Artifact
  → 用户接受或要求修改
  → 成功任务保存为 Workflow
  → Workflow 重复或定时运行
  → 结果反馈进入 Eval
  → 经过验证的偏好和经验进入记忆
  → 下一次执行更稳定
```

长期数据资产不是聊天数量，而是经过用户验收的工作事实：成功计划、有效资料、批准权限、
被采用的 Artifact、稳定运行的 Workflow 和用户明确纠正。模型推测不得直接成为长期事实。

## 4. 差异化支柱

### 4.1 数据主权

- 默认本地保存任务、记忆、运行记录和交付物；
- 外发给模型或连接器的数据范围可见、可控；
- 模型和供应商可替换，不绑定用户身份与工作历史；
- 产品指标默认只在本地聚合，未经用户明确同意不得上传。

### 4.2 可信执行

- Run 支持审计、恢复、取消、暂停、租约和幂等；
- 副作用必须有策略判断或用户授权；
- 不确定副作用不得自动重放；
- 用户看到的是目标和结果，底层 Run 仅作为按需展开的证据。

### 4.3 结果复用

- Artifact 是独立、可版本化、可查看和可导出的结果，不是聊天尾部文本；
- 只有成功且经过验收的任务才能成为 Workflow；
- GUI、CLI、Scheduler 和 Webhook 运行同一个不可变 Workflow 版本；
- 自动化先建议、后确认，不因识别到重复行为就擅自创建。

### 4.4 可迁移平台

- Application Service 和稳定事件协议先于进程拆分；
- GUI、CLI、飞书和未来远程客户端共享同一应用用例；
- LangGraph 是执行适配器，不进入领域模型；
- Ember 公共 API 只在产品边界经过真实使用验证后稳定。

## 5. 目标架构

```text
Interfaces
  GUI / CLI / Feishu / Webhook / future local API
        │
Product Control Plane
  WorkItem / Workflow / Artifact / Grant / Approval / Eval / Feedback
        │
Execution Plane
  Run Runtime / Graph Adapter / Tool Runtime / Effect Outbox
        │
Context and Evidence Plane
  ContextResource / Memory Claim / Provenance / Sensitivity / Retention
        │
Infrastructure
  SQLite / Files / Models / MCP / Scheduler / OS Sandbox
```

短期保持单进程组合根，先以端口、Application Service 和事件 schema 隔离变化。只有在远程
控制、多客户端或后台常驻需求被验证后，才把执行平面拆为本地 Agent Host。

## 6. 阶段路线

### Stage A：身份、指标与验证（1–2 周）

- 收敛 README、包元数据、版本和发布信息；
- 新增隐私友好的本地 Product Event Store；
- 记录任务完成、Artifact 查看/反馈/导出、Workflow 创建/复用；
- 扩展真实 Eval，不只检查终态和 Artifact 数量；
- 组织 5–10 名目标用户的封闭试用。

### Stage B：可用结果闭环（3–6 周）

- Composer 文件和目录拖放；
- `ContextResource` 快照、hash、权限和外发边界；
- Artifact 内嵌预览、不可变版本、Diff、反馈和导出；
- 原 WorkItem 内继续修订并生成新版本。

### Stage C：Workflow 复用闭环（7–10 周）

- GUI Workflow Library、版本差异和参数表单；
- 从已接受 Artifact 的任务生成 Workflow；
- GUI、CLI、Scheduler 运行同一固定版本；
- 展示每次运行的输入、权限、预算、失败和结果。

### Stage D：可信度与发布能力（11–14 周）

- Prompt、模型路由和 Context 策略进入 Eval 回归；
- 记忆来源、作用域、置信度、过期、纠正、删除和导出；
- 一键诊断包和 GUI 黄金路径 E2E；
- macOS 签名、公证和更新；
- 成本、工具成功率和恢复成功率持久化。

### Stage E：可控主动性（3–6 个月）

- 从重复成功任务发现模式；
- 只建议创建自动化；
- 提供建议原因、冷却期、安静时段和全局关闭；
- 高风险主动行为始终回到审批。

### Stage F：平台化（6–12 个月）

- 稳定本地 Agent Host 和事件 API；
- 稳定 Ember 公共 API 与 SDK；
- 插件 manifest 和第三方适配器；
- Windows/Linux 正式发行；
- 仅在产品验证后评估团队协作和云同步。

## 7. 阶段门槛

| 指标 | 进入平台化前目标 |
|---|---:|
| 核心任务成功率 | ≥ 85% |
| Artifact 采用率 | ≥ 60% |
| 成功任务转 Workflow 比例 | ≥ 20% |
| 重复 Workflow 成功率 | ≥ 90% |
| 未经人工确认自动重放的不确定副作用 | 0 |

指标必须由持久化产品事实计算。没有 Artifact 反馈时必须标记为“未知”，不得按拒绝或采用
处理。所有远程遥测均为显式 opt-in；本地指标面板不依赖远程服务。

## 8. 明确停止项

在上述门槛达成前，不投入：

- 更多模型供应商和多 Agent 模式；
- 整体迁移 LangChain；
- 动态 Soul 和自动人格演化；
- 插件市场和 Agent 广场；
- 团队云同步；
- 自建向量数据库；
- 大规模重写 PyQt；
- 逐像素复制其他产品界面。

## 9. 当前实施切片

第一条完整验收路径是：

```text
拖入资料 → 描述目标 → 确认计划与权限 → 后台执行
→ 查看并修改报告 → 接受并导出 → 保存为 Workflow
→ 定时再次运行 → 对比两次结果
```

提交顺序：

1. `docs: define trusted workflow product strategy`
2. `feat: persist privacy-safe product events`
3. `feat: add context resource domain model`
4. `feat: support composer file and folder attachments`
5. `feat: add versioned artifact workspace`
6. `feat: add artifact preview diff and feedback`
7. `feat: add workflow library and parameter forms`
8. `feat: run exact workflow versions from gui and scheduler`
9. `test: cover end-to-end accepted-task reuse flow`
10. `build: add diagnostics and signed beta release groundwork`

