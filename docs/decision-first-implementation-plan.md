# Decision-First Implementation Plan & 追踪文档

> 版本：v0.2 · 日期：2026-05-05  
> 状态：**Phase 1 执行中 — 代码审查卡片端到端**  
> 关联文档：[decision-first-product-vision.md](./decision-first-product-vision.md)

---

## 总览

本文档是 Decision-First AI 交互范式的**可执行计划**和**追踪记录**。
产品愿景文档定义了"做什么"，本文档定义"怎么做、谁做、何时做、做到什么程度"。

---

## 一、设计决策追踪（D1-D4）— 已全部定稿

### D1: 卡片渲染位置 → ✅ 已决策

**结论**：PyQt6 原生 QFrame 渲染，混入聊天流。`DecisionCardWidget` 已实现。

### D2: Agent 编排 → ✅ 已决策

**结论**：Phase 1 单 LLM 直出卡片 + 审查管道并行 LLM 调用。Phase 2 再上 AgentOrchestrator DAG。

### D3: 卡片 JSON Schema → ✅ 已决策

**结论**：`decision/schema.py` 已定义完整 Pydantic 模型。**唯一缺口**：`DecisionOption` 缺 `action` 字段（G5）。

### D4: 卡片推送时机 → ✅ 已决策

**结论**：立即推送 (`CardSignals`) + 定时推送 (`ProactiveAgent`)。Phase 3 再加汇总推送。

---

### D2: Agent 编排 → ✅ 已决策

**结论**：Phase 1 单 LLM 直出卡片 + 审查管道并行 LLM 调用。Phase 2 再上 AgentOrchestrator DAG。

---

### D3: 卡片 JSON Schema → ✅ 已决策

**结论**：`decision/schema.py` 已定义完整 Pydantic 模型。**唯一缺口**：`DecisionOption` 缺 `action` 字段（G5）。

---

### D4: 卡片推送时机 → ✅ 已决策

**结论**：立即推送 (`CardSignals`) + 定时推送 (`ProactiveAgent`)。Phase 3 再加汇总推送。

---

## 二、Vermilion Bird 改造影响分析

### 受影响模块清单

| 模块 | 文件 | 改动类型 | 改动说明 | 复杂度 |
|------|------|---------|---------|--------|
| **ChatCore** | `src/llm_chat/chat_core.py` | **修改** | `send_message()` 增加卡片模式分支；新增 `send_decision_card()` 方法 | 🔴 高 |
| **IntentClassifier** | `src/llm_chat/intent/classifier.py` | **修改** | 新增 `Decision` 意图类型；L1 模式匹配增加"审查/分析/优化"等触发词 | 🟡 中 |
| **Intent Types** | `src/llm_chat/intent/types.py` | **修改** | 新增 `Intent.DECISION`；`RoutingDecision` 增加 `agent_workflow` 字段 | 🟢 低 |
| **AgentOrchestrator** | `src/llm_chat/agent/` | **新增** | 任务拆解 + DAG 调度 + Agent 通信 + 断点续传 | 🔴 高 |
| **DecisionEngine** | `src/llm_chat/decision/` | **新增** | 选项生成 + 置信度计算 + 卡片序列化 + 卡片状态机 + 决策日志 | 🔴 高 |
| **Storage** | `src/llm_chat/storage/_core.py` | **修改** | 新增 `decision_log` 表 + `pending_cards` 表 | 🟡 中 |
| **SpawnSubagentTool** | `src/llm_chat/skills/task_delegator/` | **修改** | 支持 Agent 间上下文传递；支持子任务依赖关系 | 🟡 中 |
| **TaskExecutor** | `src/llm_chat/scheduler/task_executor.py` | **修改** | 支持 DAG 工作流调度；支持断点续传 | 🟡 中 |
| **GUI Frontend** | `src/llm_chat/frontends/gui.py` | **修改** | 新增卡片渲染组件；WebSocket 客户端 | 🔴 高 |
| **Web UI** | **新项目** | **新增** | 决策卡片 Web 渲染器（React/Vue + WebSocket） | 🔴 高 |
| **MemoryManager** | `src/llm_chat/memory/manager.py` | **修改** | 决策结果写入 mid-term memory | 🟢 低 |
| **Conversation** | `src/llm_chat/conversation.py` | **修改** | 会话中区分文本消息和卡片消息 | 🟡 中 |
| **Config** | `src/llm_chat/config.py` | **修改** | 新增 `decision` + `agent` + `card_renderer` 配置节点 | 🟢 低 |

### 不改的模块

以下模块在 Phase 1 **保持不变**：
- `protocols/` — 协议层不涉及卡片逻辑
- `mcp/` — MCP 工具照常可用，只是结果输入给 DecisionEngine
- `frontends/feishu/` — 飞书集成不纳入 Phase 1
- `context/` — 上下文管理沿用现有机制
- `skills/` (除 task_delegator) — 技能系统照常工作

### 架构演进图

```
Phase 1 前 (当前 Vermilion Bird):
  用户输入 → IntentClassifier → ChatCore.send_message()
    → LLM 调用 → 工具执行 → 文本输出

Phase 1 后 (卡片模式):
  用户输入 → IntentClassifier
    ├─ [普通对话] → ChatCore.send_message() → 文本输出 (保持不变)
    └─ [决策任务] → AgentOrchestrator
                      ├─ 任务拆解 → 多 Agent 并行
                      ├─ 结果汇总 → DecisionEngine
                      │   ├─ 选项生成 + 置信度
                      │   └─ 卡片序列化
                      └─ WebSocket → CardRenderer → 用户决策
                                        │
                                        ▼
                              用户选择 → ActionExecutor
                                ├─ execute_skill
                                ├─ reject/revision
                                └─ 结果 → 决策日志
```

---

## 三、MVP 用例定义

### 用例 1: 代码审查卡片

**触发方式**：用户在 IDE 中选中代码，通过 Vermilion Bird 快捷指令触发"审查代码"

**数据流**：
```
用户选中代码 + "审查这段代码"
    → IntentClassifier → DECISION intent
    → AgentOrchestrator 拆解为 3 个子任务:
        ├─ Agent 1: 安全分析 (SQL注入/XSS/硬编码密钥)
        ├─ Agent 2: 性能分析 (复杂度/内存/IO)
        └─ Agent 3: 最佳实践 (命名/设计模式/可读性)
    → 3 Agent 并行执行，各自调用 tool:
        ├─ file_reader (读取完整文件上下文)
        ├─ shell_exec (运行 linter/SAST)
        └─ web_search (查询 CVE 相关信息)

    → DecisionEngine 汇总:
        ├─ 安全: 2 HIGH, 1 MEDIUM
        ├─ 性能: 0 issue
        └─ 最佳实践: 3 WARNING
        ├─ 生成 3 个选项 + 置信度
        └─ 序列化为决策卡片
```

**预期卡片**：
```
┌───────────────────────────────────────────────┐
│  🔍 代码审查完成                               │
│  文件: api/payment.py · 影响范围: 89 行        │
│                                                │
│  摘要: 发现 2 个安全问题、3 个代码风格问题      │
│  无性能瓶颈                                    │
│  ───────────────────────────────────────────── │
│                                                │
│  选项 A: 自动修复全部（推荐 ✅）                │
│    ├ 操作: 修改 1 个文件，5 处改动              │
│    ├ 预期: 消除 2 HIGH 安全问题，代码评级 +2    │
│    ├ 风险: 低 — 改动为局部变量重命名 + 加参数校验│
│    └ 置信度: 92%                               │
│                                                │
│  选项 B: 只修复安全问题                         │
│    ├ 操作: 修改 1 个文件，2 处改动              │
│    ├ 预期: 消除 2 HIGH 安全问题                 │
│    ├ 风险: 低                                   │
│    └ 风格问题留待后续处理                       │
│                                                │
│  选项 C: 只查看报告，我自己改                   │
│                                                │
│  问题详情 (点击展开 ▼):                         │
│    🔴 [HIGH] L42: 未验证的 user_id 直接传入 SQL │
│    🔴 [HIGH] L67: API key 硬编码                │
│    🟡 [WARN] L23: 变量名 `x` 不够语义化         │
│    🟡 [WARN] L45: 函数超过 50 行，建议拆分      │
│    🟡 [WARN] L78: 缺少类型注解                  │
│                                                │
│  引用: api/payment.py · pylint report · bandit  │
│                                                │
│  [选A并执行] [选B] [选C] [详细报告(进入L2)]      │
└───────────────────────────────────────────────┘
```

**成功标准**：
- 从触发到卡片呈现 < 15 秒
- 卡片选项可执行（选 A 后 5 个文件改动全部 apply）
- 决策日志正确记录

---

### 用例 2: 计划拆解卡片（Phase 2 候选）

**触发方式**：用户输入模糊目标如"给项目加用户认证模块"

**Agent 工作流**：
```
AgentOrchestrator:
  ├─ Agent 1: 代码库分析 (当前架构、依赖、入口点)
  ├─ Agent 2: 方案调研 (搜索最佳实践、库对比)
  └─ 汇总 → DecisionEngine:
       ├─ 选项 A: JWT + OAuth2 (推荐)
       ├─ 选项 B: Session + Cookie
       └─ 选项 C: 第三方 Auth0/Firebase Auth
```

> 注：此用例 Phase 1 不实现，仅作为 Phase 2 方向参考。

---

## 四、卡片状态机

```
                    ┌──────────┐
                    │  pending  │  卡片生成，等待用户决策
                    └────┬─────┘
                         │
              ┌──────────┼──────────┐
              ▼          ▼          ▼
         ┌────────┐ ┌────────┐ ┌─────────┐
         │decided │ │snoozed │ │expired  │
         └───┬────┘ └───┬────┘ └────┬────┘
             │          │           │
             │    (超时唤醒)       │
             │          │           │
             │          ▼           │
             │     ┌────────┐      │
             │     │pending │◄─────┘
             │     └────────┘
             ▼
        ┌──────────┐
        │ executing│  正在执行用户选择的 action
        └────┬─────┘
             │
        ┌────┴────┐
        ▼         ▼
   ┌─────────┐ ┌─────────┐
   │completed│ │ failed  │
   └────┬────┘ └────┬────┘
        │           │
        │     (用户选择重试)
        │           │
        │           ▼
        │      ┌──────────┐
        │      │ revision │  用户驳回，需要重新生成
        │      └────┬─────┘
        │           │
        │           ▼
        │      ┌──────────┐
        │      │ pending  │  重新生成卡片
        │      └──────────┘
        │
        ▼
   ┌──────────┐
   │ archived │  最终归档
   └──────────┘
```

**状态说明**：

| 状态 | 含义 | 可执行操作 |
|------|------|-----------|
| `pending` | 卡片生成，等待用户决策 | decide / snooze / dismiss |
| `decided` | 用户已选择，等待执行 | 自动进入 executing |
| `executing` | 正在执行 action | - |
| `completed` | 执行成功 | 自动归档 |
| `failed` | 执行失败 | retry / revision / dismiss |
| `revision` | 用户驳回，要求修改 | 重新生成卡片 |
| `snoozed` | 用户暂缓 | 超时后回到 pending |
| `expired` | 超时未处理 | 自动归档 |
| `archived` | 最终状态，进入决策日志 | 可查询不可修改 |

---

## 五、未覆盖的关键问题（待讨论）

### Q1: 多轮决策的对话组织

当一个决策卡片进入 `revision` 状态后，AI 重新生成的卡片是：
- **方案 A**：新建一张卡片，原卡片归档
- **方案 B**：在原卡片上原地修改，保留修改历史

**建议**：方案 A + 卡片之间用 `parent_card_id` 建立引用链。

---

### Q2: 卡片推送可靠性

WebSocket 断连时，pending 卡片不应丢失：

| 机制 | 实现方式 |
|------|---------|
| **服务端持久化** | `pending_cards` 表存储，WebSocket 重连后重新推送 |
| **至少一次语义** | 卡片 ID 去重，客户端确认后服务端标记 delivered |
| **重试策略** | 未确认卡片每 30s 重推一次，最多 5 次 |
| **降级方案** | 若 WebSocket 长时间不可用，fallback 为 HTTP 轮询 |

---

### Q3: L0 安静模式的 Phase 1 边界

Phase 1 **不做**用户桌面监控。L0 的范围限定在：

- ✅ Vermilion Bird 自己的会话历史（现有能力）
- ✅ 项目记忆文件（`~/.vermilion-bird/memory/`）
- ✅ MCP 工具的数据源（如已连接的 Jira/GitHub）
- ❌ 用户屏幕内容
- ❌ 浏览器历史
- ❌ 本地文件系统（除非用户主动打开）

---

### Q4: 决策日志与记忆系统的关系

```
决策卡片完成 (archived)
    │
    ▼
决策日志表 (decision_log)      ← 结构化查询
    │
    ▼
MemoryManager 定期汇总          ← 利用现有 LLM 聚类去重
    │
    ▼
mid-term memory                 ← 同现有记忆一起注入 system prompt
```

决策日志作为 mid-term memory 的**特殊子类型**，用现有去重 + 聚类能力做决策模式分析和复盘。

---

## 六、代码审查卡片 — 端到端 Gap 清单

### 架构原则

**意图层不做能力扩展**。意图分类器只管路由（模型选型/工具预加载/跳过LLM），不管"产什么卡片"。卡片生成能力通过 System Prompt 注入，LLM 自行判断何时产卡片。

`_DECISION_CARD_PROMPT` 已存在，对所有意图生效。

### Gap 清单（按实现顺序）

| # | Gap | 文件 | 复杂度 | 状态 |
|---|-----|------|--------|------|
| G0 | System prompt 卡片指令 | `chat_core.py` `_DECISION_CARD_PROMPT` | - | ✅ |
| G5 | `DecisionOption.action` 字段 | `decision/schema.py` | 🟢 低 | ✅ |
| G3 | `_handle_review()` 审查管道 | `chat_core.py` (新增方法) | 🔴 高 | ✅ |
| G1' | `/review` 快捷指令映射到 CODE | `intent/classifier.py` | 🟢 低 | ✅ |
| G2 | `send_message()` 加 REVIEW 分支 | `chat_core.py` | 🟡 中 | ✅ |
| G4 | `_handle_card_decided()` action 分发 | `frontends/gui.py` | 🟡 中 | ✅ |
| G6 | 决策日志 `execution_result` | `decision/log.py` | 🟢 低 | ✅ |

### 实现顺序

```
G5 (schema action字段)
  → G3 (审查管道核心)
    → G1' + G2 (触发入口)
      → G4 (action分发)
        → G6 (日志补全)
```

---

## 七、风险登记

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|---------|
| Agent 输出质量不足以生成有用卡片 | 高 | 中 | 先用 LLM 直接生成卡片 mock 测试质量，再决定是否上 Agent |
| WebSocket 推送延迟导致卡片体验差 | 中 | 低 | 用 SSE 作为备选方案 |
| 卡片渲染原型开发比预期慢 | 中 | 低 | 降低 Phase 1 UI 标准：先做命令行卡片（Rich/TUI） |
| Vermilion Bird 改造量超预期 | 高 | 中 | 做最小侵入：先在 ChatCore 上加一个分支，不动主干 |
| 用户不接受卡片交互 | 高 | 中 | 第 2 周内部测试是关键门禁——测试不过就迭代，不进入第 3 周 |

---

## 八、变更记录

| 日期 | 版本 | 变更内容 | 作者 |
|------|------|---------|------|
| 2026-05-05 | v0.2 | D1-D4 全部定稿（方案已存在）；Phase 1 任务清单替换为代码审查卡片 Gap 清单；明确意图层不做能力扩展 | AI (via Claude) |

---

> **下一步**：请逐项确认以上内容，特别是 D1-D4 设计决策和 Phase 1 任务清单。确认后进入第 1 周执行。
