# Decision-First 交互范式 — 实施计划

> 基于 `docs/decision-first-product-vision.md` 的架构评估与分步实施计划
> 分支：`feat/decision-first` · 更新：2026-05-05

---

## 一、方向确认

**方向正确。** Vermilion Bird 现有架构已具备基础能力：

| 已有能力 | 对应 L0/L2 | 直接可用 |
|----------|-----------|---------|
| ProactiveAgent + Scheduler | L0 后台安静运行 | ⚠️ 需改为产出卡片 |
| 快捷指令 (`/new`, `/style`, `/remember` 等) | L0 触发入口 | ✅ |
| ChatCore + ToolExecutor + MCP | L2 对话兜底 | ✅ |
| MemoryManager (四层记忆) | L0 上下文积累 | ✅ |
| task_delegator (WorkflowExecutor) | Agent 编排雏形 | Phase 2 |
| PushService (Feishu/GUI) | 卡片推送通道 | ⚠️ 需扩展格式 |

**核心差距**：缺少 L1 决策卡片的完整链路（数据模型 → 生成引擎 → UI 渲染 → 持久化）。

---

## 二、架构变化

### 新增模块

```
src/llm_chat/decision/           # Decision-First 核心
├── __init__.py
├── schema.py                    # 卡片 Pydantic 模型 + JSON Schema
├── engine.py                    # Decision Engine (选项生成 + 置信度)
├── lifecycle.py                 # 卡片生命周期管理
├── log.py                       # 决策日志持久化
└── card_panel.py                # GUI 卡片组件
```

### 修改范围

| 文件 | 改动 |
|------|------|
| `frontends/gui.py` | 新增卡片渲染到聊天流 |
| `proactive/agent.py` | 输出从文本改为决策卡片 |
| `chat_core.py` | 快捷指令可产出卡片 |
| `storage/_core.py` | 新增 decision_log 表 |

### 架构集成

```
ProactiveAgent / Scheduler / 快捷指令
          │
          ▼
   Decision Engine (decision/engine.py)
          │
          ▼
   DecisionCard (decision/schema.py)
          │
          ├──→ card_panel.py → GUI 渲染 (QFrame 卡片)
          │
          ├──→ PushService → 飞书纯文本推送 (Phase 2 改互动卡片)
          │
          └──→ decision/log.py → SQLite 决策日志
```

---

## 三、分步实施计划

### Phase 1 范围

只覆盖"决策卡"核心链路：模型 → 生成 → 渲染 → 归档。不做 Agent Orchestrator / 专业 Agent 池 / 飞书互动卡片。

### Step 1: 卡片数据模型 ✅ 当前步骤

**文件**: `decision/__init__.py`, `decision/schema.py`

定义完整卡片类型系统：

- `CardType` 枚举：decision / approval / status / alert / suggestion
- `DecisionOption`：选项（label / expected_effect / risk / confidence）
- `DecisionCard`：完整卡片（id / title / context / options / recommendation / sources / status）
- `CardStatus`：pending / decided / dismissed / archived

**验证**: Python import 通过，可创建有效卡片实例

---

### Step 2: Decision Engine

**文件**: `decision/engine.py`

接收 LLM 输出 → 结构化卡片：

- `generate_card(task_context, llm_response) → DecisionCard`
- 置信度：LLM prompt 自估（0-100），无需 logprobs
- 推荐策略：选置信度最高且风险可接受的选项
- 输入方式：既支持 LLM 原始响应解析，也支持显式结构化调用

**验证**: 单元测试：给定模拟 LLM 输出，产出有效 DecisionCard

---

### Step 3: GUI 卡片渲染组件

**文件**: `decision/card_panel.py` + 修改 `frontends/gui.py`

核心 UI 组件：

- `DecisionCardWidget(QFrame)` — 单张卡片
  - 标题 + 背景摘要
  - 选项对比表格（QTableWidget）
  - 按钮行："选 A" / "选 B" / "了解更多"
  - 推荐标记 + 置信度进度条
- `add_card(card)` — 卡片混入聊天消息流
- `CardSignal` — 跨线程信号（后台任务 → GUI 主线程）

**验证**: GUI 中显示一张带按钮的决策卡片，点击按钮可记录决策

---

### Step 4: 决策日志持久化

**文件**: `decision/log.py` + 修改 `storage/_core.py`

SQLite 扩展：

- `decision_log` 表（conversation_id, card_id, card_type, title, decision, selected_option, created_at）
- `DecisionLogStore` API
- 建表迁移（`Storage._migrate()`）

**验证**: 做出决策后，日志写入 SQLite 可查询

---

### Step 5: ProactiveAgent 输出改为决策卡

**文件**: 修改 `proactive/agent.py`

- `_generate_opener()` → `_generate_card()`
- 改为产出 DecisionCard，含 2-3 个讨论方向选项
- 不再生产纯文本开场白，只推送决策卡
- 飞书端保持纯文本摘要

**验证**: 定时任务触发后，GUI 显示 1 张决策卡片而非文本消息

---

### Step 6: 快捷指令卡片化

**文件**: 修改 `chat_core.py`

部分快捷指令输出同时发送决策卡片：

- `/search` → 搜索建议卡片（选项：打开链接 / 继续追问 / 保存）
- `/code` → 代码片段决策（选项：复制 / 保存为文件 / 审查）

**验证**: 输入 `/search Python 异步`，聊天流中出现卡片

---

### Step 7: ProactiveAgent 上下文增强

**文件**: 修改 `proactive/agent.py`

- 生成卡片前触发 1-2 个子任务
  - Web 搜索（已有）
  - Memory 摘要（已有）
- 卡片基于预分析结果生成（而非单一 LLM 调用）

**验证**: 每日卡片内容比 Step 5 更丰富、更个性化

---

## 四、代码改动汇总

| Step | 新增文件 | 修改文件 | 行数 |
|------|---------|---------|------|
| 1 | `decision/__init__.py`, `decision/schema.py` | — | ~80 |
| 2 | `decision/engine.py` | — | ~120 |
| 3 | `decision/card_panel.py` | `frontends/gui.py` | ~350 |
| 4 | `decision/log.py` | `storage/_core.py` | ~100 |
| 5 | — | `proactive/agent.py` | ~100 |
| 6 | — | `chat_core.py` | ~50 |
| 7 | — | `proactive/agent.py` | ~80 |
| **总计** | **~650** | **~330** | **~880** |

---

## 五、关键设计决策

### D1: 卡片混入聊天流 (A 方案)

选 A。卡片作为特殊消息类型插入 QTextBrowser 的聊天流中，不新增独立面板。

```
[用户消息]
[AI 回复 — 文本]
[ 🤔 代码审查结果 — 决策卡片 ]  ← 新
   ┌── 选项 A: 合并（推荐） ──┐
   │  └ 风险: 低 · 置信度 92% │
   ├── 选项 B: 修改后合并 ─────┤
   │  └ 风险: 中 · 置信度 78% │
   ├── 选项 C: 驳回 ──────────┤
   │  └ 风险: 低 · 置信度 65% │
   └──────────────────────────┘
[下一轮回复]
```

### D2: 置信度用 LLM 自估 (A 方案)

Prompt 末行加：`请为每个选项给出 0-100 的置信度分数。` 简单有效，无需 logprobs。

### D3: 飞书端 Phase 2 再升级

Phase 1 飞书保持纯文本推送。标题格式：`💡 [卡片标题]\n选项：A. xxx (推荐) / B. xxx`

### D4: 首批卡片类型

Phase 1 只做两种：**方案决策**（`decision`）和**建议推送**（`suggestion`）。审批/告警/状态通报后续再加。

---

## 六、不做的范围（Phase 1 边界外）

- Agent Orchestrator（DAG 动态拆解 — Phase 2）
- 专业 Agent 池（搜索/分析/代码 Agent — Phase 2）
- 飞书互动卡片（Phase 2）
- 批量卡片处理（"全部批准" — Phase 2）
- 浮动窗口 / 独立 Web 应用（未来）
- L0 文件系统/日历监听（技术难度大，暂不考虑）
