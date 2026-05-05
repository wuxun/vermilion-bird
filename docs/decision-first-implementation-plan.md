# Decision-First Implementation Plan & 追踪文档

> 版本:v1.1 · 日期:2026-05-05
> 状态:**Phase 1 打磨完成 ✅**
> 关联文档:[decision-first-product-vision.md](./decision-first-product-vision.md) |
[decision-first-design.md](./decision-first-design.md)

---

## 总览

Decision-First AI 交互范式 Phase 1 已实现。核心成果:

- **卡片提交**:LLM 通过 `submit_decision_card` tool call 提交结构化卡片,不再依赖文本正则解析
- **并行 Agent**:LLM 自主通过 `spawn_subagent(wait=true)` 并行启动子 Agent,无需硬编码管道
- **GUI 卡片**:`DecisionCardWidget` 渲染,延迟追加确保卡片在 AI 文本之后
- **飞书卡片**:文本命令识别(A/选A),共享 action 执行器
- **决策日志**:SQLite 持久化,含 `execution_result` 追溯
- **重新选择**:卡片决策后可换方案,无需等待重新生成
- **子 Agent 面板**:`SubAgentPanel` 实时显示并行子 Agent 的状态、调用链、耗时

## Phase 1 打磨成果

---

## 一、设计决策(D1-D4)- 全部定稿

| # | 决策 | 结论 | 实现 |
|---|------|------|------|
| D1 | 卡片渲染位置 | PyQt6 原生 QFrame,混入聊天流 | `DecisionCardWidget` (card_panel.py) |
| D2 | Agent 编排 | System prompt 驱动,LLM 自主拆分维度 + spawn_subagent | `_DECISION_CARD_PROMPT` (chat_core.py:33) |
| D3 | 卡片 JSON Schema | Pydantic 模型 + `action` 字段 | `DecisionCard` + `DecisionOption.action` (schema.py) |
| D4 | 卡片推送时机 | 立即推送 (CardSignals) + 定时推送 (ProactiveAgent) | 不变 |

---

## 二、实际改造范围

### 新增文件 (3)

| 文件 | 职责 |
|------|------|
| `decision/submit_tool.py` | `SubmitDecisionCardTool` - tool call 提交卡片,thread-local 传递到 ChatCore |
| `decision/action_executor.py` | `execute_card_action()` - GUI 和飞书共用的 action 执行逻辑 |
| `docs/decision-first-implementation-plan.md` | 本文档 |

### 修改文件 (7)

| 文件 | 改动 |
|------|------|
| `chat_core.py` | `_DECISION_CARD_PROMPT` 增强(并行 Agent 模式 + tool call 提交);`send_message` + `send_message_stream` 都加 `get_pending_card()` 提取 + fallback `_try_extract_card`;`send_message_stream` 加 `on_card` 参数 |
| `decision/schema.py` | `DecisionOption` 加 `action: Optional[Dict]` 字段 |
| `decision/log.py` | `decision_log` 表加 `execution_result` + `executed_at`;新增 `update_execution_result()` |
| `storage/_core.py` | 同步 `decision_log` 建表语句;新增 `_migrate_decision_log_columns()` 灰度迁移 |
| `client/_base.py` | `_setup_skills()` 在 `clear()` 后注册 `SubmitDecisionCardTool`(避免被 wipe) |
| `frontends/gui.py` | `display_card` 延迟追加(流式场景)vs 立即渲染(ProactiveAgent);`_start_streaming()` 公共方法;`_continue_chat_from_card()` 卡片选择后继续对话;`_update_context_status()` 跳过 card 消息 |
| `frontends/feishu/adapter.py` | `_pending_cards` 绑定 + `_try_handle_card_decision()` 文本命令检测;`_send_card_text_to_chat` 加操作提示 |

### 不改的模块

- `protocols/` - 协议层不涉及卡片逻辑
- `mcp/` - MCP 工具正常可用
- `context/` - 上下文管理沿用现有机制
- `skills/` - 技能系统不变(task_delegator 的 spawn_subagent 直接复用)
- `intent/` - 意图层不做能力扩展,卡片由 system prompt 驱动

---

## 三、实际架构:System Prompt 驱动的并行 Agent

```
用户: "审查这段代码" / "评估这三个方案"
    │
    ▼
ChatCore._build_system_context()
    │
    ├─ _DECISION_CARD_PROMPT 注入:
    │   "遇到多维度分析 → 拆分维度 → 并行 spawn_subagent(wait=true) → submit_decision_card"
    │
    ▼
LLM 自主决策:
    │
    ├─ 代码审查 → spawn(安全) ∥ spawn(性能) ∥ spawn(代码质量)
    ├─ 方案评估 → spawn(可行性) ∥ spawn(成本) ∥ spawn(风险)
    └─ 用户指定 → "只看安全" → spawn(安全) only
    │
    ▼
ToolExecutor.execute_tools_parallel() → 并行执行
    │
    ▼
LLM 汇总 → submit_decision_card(title=..., options=[...])
    │
    ├─ SubmitDecisionCardTool.execute() → thread-local
    │
    ▼
ChatCore.get_pending_card()
    ├─ 优先路径 (tool) → on_card(card)
    └─ Fallback (_try_extract_card) → 向后兼容
    │
    ▼
GUI: CardSignals → DecisionCardWidget 渲染
飞书: 结构化文本 + "回复 A/B/C 选择方案"
```

**关键设计**:不新增 AgentOrchestrator。LLM 通过 system prompt 学习并行分析模式,利用现有 `SpawnSubagentTool` 实现。不同场景零代码改动。

---

## 四、卡片提交流程对比

| | 旧方案(文本嵌入) | 新方案(tool call) |
|---|---|---|
| LLM 输出 | 文本中嵌入 ` ```decision-card` JSON 块 | 调用 `submit_decision_card(title=..., options=[...])` |
| 提取方式 | `_try_extract_card()` 正则解析 | `get_pending_card()` thread-local |
| 格式保证 | ❌ LLM 可能漏掉围栏标记 | ✅ function calling 参数校验 |
| 文本展示 | 需要剥离 JSON 块 | 卡片不污染文本回复 |
| 兼容性 | - | 仍保留 fallback |

---

## 五、多端决策交互

### GUI

```
用户消息
  ↓
AI 文本回复(分析总结)
  ↓
DecisionCardWidget(选项按钮)
  ├─ 选A → action 分发:
  │   ├─ 有 action.execute_skill → 执行 → 结果追加到当前会话
  │   └─ 无 action → _continue_chat_from_card → 新一轮对话
  ├─ 选B → 同上
  └─ 了解更多 → QMessageBox 弹窗
```

卡片渲染策略:
- **流式场景**:缓存到 `_pending_card`,等 `_on_stream_finished` 追加到 AI 文本之后
- **ProactiveAgent**:无活跃流,立即渲染

### 飞书

```
飞书用户收到卡片文本:
  🗳 代码审查结果
  3 个选项
  ✅ A. 立即修复高危漏洞(推荐) (95%)
     B. 完整重构 (85%)
     C. 仅修复安全漏洞 (70%)
  来源: 安全审查子Agent, ...
  💡 回复 A/B/C 选择方案
  ↓
用户回复: "A" / "选A" / "选 A"
  ↓
FeishuAdapter._try_handle_card_decision()
  ├─ 正则: ^(?:选\s*|选项\s*)?([A-Z])(?![A-Z])
  ├─ 清除 _pending_cards
  ├─ 记录决策日志
  └─ execute_card_action() → 返回执行结果文本
```

---

## 六、卡片状态管理

### DecisionCardWidget 状态

| 状态 | 触发 | UI 表现 |
|------|------|---------|
| 活跃 | 卡片插入聊天流 | 按钮可点击,推荐项高亮 |
| 已决策 | 用户点击选项 | 按钮全部禁用,选中项绿色边框 |
| 已忽略 | 用户点击"稍后" | 按钮禁用,卡片灰色 |

### 会话卡片 vs ProactiveAgent 卡片

| 来源 | `conversation_id` | 点击选项行为 |
|------|-------------------|-------------|
| 对话中生成 | 有值 | `_continue_chat_from_card` → 在当前会话继续 |
| ProactiveAgent 推送 | 无 | `_create_conversation_from_card` → 新建会话 |

---

## 七、文件索引

| 模块 | 文件 | 核心符号 |
|------|------|---------|
| 卡片提交 | `decision/submit_tool.py` | `SubmitDecisionCardTool`, `get_pending_card()` |
| Action 执行 | `decision/action_executor.py` | `execute_card_action()` |
| 数据模型 | `decision/schema.py` | `DecisionCard`, `DecisionOption`, `CardType`, `CardStatus` |
| 卡片渲染 | `decision/card_panel.py` | `DecisionCardWidget`, `CardSignals` |
| 决策日志 | `decision/log.py` | `DecisionLogStore` |
| System Prompt | `chat_core.py:33` | `_DECISION_CARD_PROMPT` |
| GUI 集成 | `frontends/gui.py` | `display_card()`, `_start_streaming()`, `_continue_chat_from_card()` |
| 飞书集成 | `frontends/feishu/adapter.py` | `_try_handle_card_decision()`, `_send_card_text_to_chat()` |
| 工具注册 | `client/_base.py:120` | `_setup_skills()` 注册 `SubmitDecisionCardTool` |
| 存储迁移 | `storage/_core.py` | `_migrate_decision_log_columns()` |

---

## 八、测试场景

```
场景 1: 代码审查 - 完整链路
  输入: "审查以下代码:```python ...```"
  预期: 3 个 spawn_subagent 并行 + submit_decision_card → 卡片渲染 → 点击选项继续对话

场景 2: 方案评估 - 泛化验证
  输入: "评估 FastAPI / Django / Litestar,从性能、生态、学习成本三个维度"
  预期: 同样走并行 Agent + 决策卡片模式

场景 3: 用户指定维度
  输入: "只从安全角度审查这段代码"
  预期: 只 spawn 安全 Agent,不自行添加其他维度

场景 4: 飞书卡片选择
  输入: 收到卡片文本后回复 "A" 或 "选A"
  预期: 识别为卡片选择,执行 action,返回结果
```

---

## 九、变更记录

| 日期 | 版本 | 变更内容 | 作者 |
|------|------|---------|------|
| 2026-05-05 | v0.1 | 初稿:设计决策、影响分析、用例 mockup、状态机、任务清单、风险 | AI |
| 2026-05-05 | v0.2 | D1-D4 定稿;替换为 Gap 清单;明确意图层不做能力扩展 | AI |
| 2026-05-05 | v1.0 | Phase 1 完成：实际架构、工具链、多端交互、文件索引、测试场景 | AI |
| 2026-05-05 | v1.1 | 打磨：卡片换方案、ProactiveAgent 立即 LLM 响应、消息上下文增强、并行执行超时修复 | AI |
