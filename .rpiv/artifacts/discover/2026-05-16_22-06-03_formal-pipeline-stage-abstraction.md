---
date: 2026-05-16T22:06:03+0800
author: wuxun
commit: 6d75917
branch: main
repository: vermilion-bird
topic: "正式 PipelineStage 抽象"
tags: [intent, frd, pipeline, chat-core, architecture]
status: complete
last_updated: 2026-05-16T22:06:03+0800
last_updated_by: wuxun
---

# FRD: 正式 PipelineStage 抽象

## Summary

将 ChatCore 当前的方法级管道拆解（`_prepare_pipeline` / `_finalize_pipeline` + 内联阶段）升级为正式的 `PipelineStage` ABC 抽象。10 个独立的异步 Stage 类通过 `PipelineRunner` 顺序执行，`PipelineContext` dataclass 承载全管道状态。ChatCore 提供 `insert_stage()` / `remove_stage()` API 供外部扩展，新增阶段无需修改 ChatCore 主流程。

## Problem & Intent

**核心动机：可扩展性。** 当前管道各阶段耦合在 ChatCore 的方法链中（`_prepare_pipeline` 粗粒度打包 5 个阶段，LLM 调用和卡片提取内联在 `send_message` 中），插入新的中间阶段（如安全审查、内容过滤、隐私提示、决策链记录）需要直接修改 ChatCore 主流程。需要一个正式的 PipelineStage 抽象，让新增阶段只需实现接口并插入列表，不改任何现有代码。

## Goals

- 10 个独立 PipelineStage 类，每个对应管道的一个逻辑阶段
- PipelineRunner 按顺序执行阶段，支持短路终止
- PipelineStage 提供 setup/process/teardown 生命周期钩子
- ChatCore 暴露 `insert_stage(after, name)` / `remove_stage(name)` 扩展 API
- 同步和流式路径共享同一套阶段列表，通过 PipelineContext 中的回调字段区分
- PipelineRunner 对每个阶段自动包裹 @observe 装饰器，提供阶段级指标
- 整个管道改为异步 (async/await)，为未来并行 I/O 留空间

## Non-Goals

- 不引入 YAML 配置节点来定义管道阶段——阶段列表硬编码在 ChatCore，扩展通过代码 API
- 不改变 ChatCore 公开 API 签名（`send_message` / `send_message_stream` 变为 async，但参数列表不变）
- 不引入新依赖（仅 Python 标准库 asyncio + dataclasses）
- 不涉及 WorkflowNode/AgentWorkflow——那是 task_delegator 域的编排，与消息管道不同

## Functional Requirements

1. **PipelineStage ABC**：定义 `name` 属性、`setup(ctx)` / `process(ctx)` / `teardown(ctx)` 三个异步方法，其中 `process` 为抽象方法，`setup`/`teardown` 默认为空。接口文件位于 `src/llm_chat/pipeline/stage.py`。

2. **PipelineContext dataclass**：承载管道全程状态，包含 `conversation_id`, `user_message`, `routing_decision`, `system_context`, `history`, `model_params`, `compressed_history`, `compressed_message`, `llm_response`, `decision_card`, `token_count`, `should_short_circuit`, `short_circuit_response`, 4 个流式回调字段。文件位于 `src/llm_chat/pipeline/context.py`。

3. **PipelineRunner**：接收 `List[PipelineStage]`，`async run(ctx)` 依次执行每个阶段的 setup → process → teardown，每阶段检查 `ctx.should_short_circuit` 决定是否终止。对每个阶段自动包裹 @observe 装饰器。文件位于 `src/llm_chat/pipeline/runner.py`。

4. **10 个具体 Stage 类**（文件位于 `src/llm_chat/pipeline/stages/`）：

   | # | Stage 类 | 职责 | 对应现有逻辑 |
   |---|---------|------|-------------|
   | 0 | `IntentStage` | 意图分类 → RoutingDecision | `chat_core.py:174` |
   | 0a | `ShortcutStage` | /help /clear /style 等快捷指令，设置短路 | `chat_core.py:342-386` |
   | 1 | `PersistUserStage` | 持久化用户消息 | `chat_core.py:398` |
   | 2 | `SystemContextStage` | 构建系统上下文（决策卡/socratic/记忆/FTS5/技能/风格） | `chat_core.py:427-477` |
   | 3 | `HistoryStage` | 获取对话历史 | `chat_core.py:405-406` |
   | 4 | `ModelRouteStage` | 意图 → 模型映射 | `chat_core.py:409-422` |
   | 5 | `CompressStage` | 上下文压缩 + 超限重压缩 | `chat_core.py:499-554` |
   | 6 | `LLMCallStage` | LLM 调用（含工具循环），setup/teardown 管理 card context | `chat_core.py:194-200` |
   | 7 | `CardExtractStage` | 决策卡片提取 → on_card 回调 | `chat_core.py:617-626` |
   | 8 | `PersistAssistantStage` | 持久化助手回复 | `chat_core.py:387` |
   | 9 | `MemoryExtractStage` | 异步记忆提取 | `chat_core.py:628-638` |
   | 10 | `TokenRecordStage` | Token 计数 + observability | `chat_core.py:643-670` |

5. **ChatCore 适配**：`__init__` 构建默认 10 阶段列表并创建 `PipelineRunner`。`send_message()` / `send_message_stream()` 改为 `async def`，内部改为 `await self._runner.run(ctx)`。提供 `insert_stage(after: str, stage: PipelineStage)` 和 `remove_stage(name: str)` 方法。

6. **调用方异步适配**：4 个调用方在 `await chat_core.send_message()` / `send_message_stream()` 层面适配（`app.py:476`, `gui.py:1053`, `feishu/adapter.py:449`, `scheduler/scheduler.py:516`）。GUI 的 PyQt6 事件循环通过 `asyncio.ensure_future()` 或 `qasync` 桥接。

## Non-Functional Requirements

- **Performance**：异步化不应引入可测量的延迟回归。每个阶段的 @observe 装饰器开销应可忽略（<1ms per stage）。
- **Security**：不改变现有安全模型。Stage 间传递的 PipelineContext 不跨线程/进程，无序列化风险。
- **UX / Accessibility**：用户感知行为不变——CLI/GUI/飞书的对话体验零差异。流式 token 推送延迟无增加。
- **Reliability**：任一阶段 `process()` 抛出异常时，PipelineRunner 记录异常阶段名称和错误信息，不再继续后续阶段。`teardown()` 异常不影响管道终止。

## Constraints & Assumptions

- **API 签名不变**：`send_message`/`send_message_stream` 改为 async，但参数列表完全不变。调用方只需在调用处加 `await`。
- **不引入新依赖**：async 用 Python 标准库 asyncio，PipelineStage ABC 用 abc + dataclasses，无 aiohttp/httpx 等新依赖。
- **不新增 YAML 配置**：管道阶段列表硬编码在 ChatCore，add_stage/remove_stage 是代码级 API，不引入 pipeline 配置节点。
- **现有测试保持通过**：`poetry run pytest` 零失败。`test_feishu_adapter` 等异步相关测试适配 but 测试逻辑不变。
- **ChatCore 是唯一管道使用者**：PipelineStage 抽象仅为 ChatCore 设计，不被其他模块直接复用。

## Acceptance Criteria

- [ ] **插入新阶段验证**：编写 DemoStage，通过 `insert_stage()` 插入到 Stage 5 之后，验证该阶段的 `process()` 被正确调用，且现有管道不退化。
- [ ] **CLI 对话正常**：`poetry run vermilion-bird` 启动 CLI，发送"你好"，能正常收到 LLM 回复。确认异步管道端到端工作。
- [ ] **现有测试全部通过**：`poetry run pytest` 零失败。所有适配异步后的测试绿色。
- [ ] **Per-stage 指标可见**：`get_observability().get_summary()` 的 `by_operation` 字段包含各阶段名（如 `pipeline.intent_stage`, `pipeline.llm_call_stage` 等），展示每阶段调用次数和平均耗时。

## Recommended Approach

在 `src/llm_chat/pipeline/` 下新增模块（`stage.py`, `context.py`, `runner.py`），在 `pipeline/stages/` 下实现 10 个 Stage 类。ChatCore 的 `send_message` / `send_message_stream` 改为 `async def`，内部委托给 `PipelineRunner.run(ctx)`。4 个调用方在调用点加 `await`。复用现有 `decision/submit_tool.py` 的 card context 逻辑作为 `LLMCallStage` 的 setup/teardown。

## Decisions

### PipelineStage ABC 设计：生命周期钩子
**Question**: PipelineStage ABC 是否沿用项目既有的 ABC 模式（如 BaseTool）—— 属性 + 抽象方法，同步 process(ctx) → ctx，外加 setup/teardown 钩子？
**Recommended**: 是，同步 + 生命周期钩子
**Chosen**: 带 setup/process/teardown 生命周期钩子；改为异步 process
**Rationale**: `chat_core.py:194-200` 已有 init_card_context/clear_card_context 的 try/finally 包裹作为生命周期先例。异步为未来并行 I/O 留空间。

### 异步 process
**Question**: process() 改为异步还是保持同步？
**Recommended**: 保持同步（避免强制所有调用方适配）
**Chosen**: 改为异步
**Rationale**: 为后续扩展留空间（并行 MCP 工具调用、多子 agent 状态查询等）。

### 阶段粒度：10 个全拆
**Question**: 10 个逻辑阶段全拆成独立 PipelineStage，还是某些合并？
**Recommended**: 10 个全拆——最大化可插拔
**Chosen**: 10 个全拆
**Rationale**: 每个阶段一个类，新增阶段只需实现 PipelineStage 并插入列表。Stage 0 的 RoutingDecision 可能让后续阶段 skip（短路）。

### PipelineContext 设计
**Question**: PipelineContext 承载什么？大而全的 dataclass 还是分层的子 context？
**Recommended**: 大而全的 dataclass——简单直接，类型明确
**Chosen**: 大而全的 PipelineContext dataclass，包含流式回调字段
**Rationale**: 单一 dataclass 承载全管道状态，各阶段按需读写。流式回调（on_chunk 等）作为 Optional 字段放在 PipelineContext 中，仅 LLMCallStage 使用。

### 短路机制
**Question**: 管道短路（/help、问候等直接返回）如何实现？
**Recommended**: PipelineContext flag + PipelineRunner 检查
**Chosen**: `ctx.should_short_circuit` flag + Runner 在每阶段后检查
**Rationale**: 统一接口——process() 始终返回 PipelineContext，语义清晰。Stage 0a 设置 flag 后 Runner 跳过剩余阶段。

### 阶段配置方式
**Question**: 10 个 PipelineStage 的列表和顺序如何配置？
**Recommended**: ChatCore.__init__ 硬编码列表 + insert_stage/remove_stage 方法
**Chosen**: 硬编码列表 + insert/remove 方法
**Rationale**: 简单、可见、调试友好。不引入 YAML 配置复杂度。新增阶段只需 App 装配时调 insert_stage。

### 重构范围
**Question**: 以下哪些属于本次重构的范围？
**Recommended**: —（multi-select，无推荐）
**Chosen**: 全部在范围内——核心抽象层 + 10 个 Stage 实现 + insert API + ChatCore 异步化 + 4 调用方适配 + Per-stage @observe 指标
**Rationale**: 一次性完成完整的管道抽象化，避免遗留半成品。

### 约束
**Question**: 以下哪些是硬约束或明确不做的事？
**Recommended**: —（multi-select，无推荐）
**Chosen**: 不改公开 API 签名 + 不引入新依赖 + 不新增 YAML 配置 + 测试保持通过
**Rationale**: 最小化破坏性变更，保持向后兼容。

### 验收标准
**Question**: 什么情况下认为重构"完成"？
**Recommended**: —（multi-select，无推荐）
**Chosen**: 插入新阶段验证 + CLI 对话正常 + 现有测试全部通过 + Per-stage 指标可见
**Rationale**: 覆盖核心目标（可扩展性）、端到端可用性、回归测试、可观测性四个维度。

## Open Questions

（无——访谈中无显式推迟项）

## References

- `src/llm_chat/chat_core.py` — 当前管道实现（`_prepare_pipeline`, `_finalize_pipeline`, inline stages）
- `docs/architecture-optimization.md` — 原始架构优化文档，含 PipelineStage ABC 提案草稿
- `src/llm_chat/tools/base.py` — 项目既有的 ABC 模式参考
- `src/llm_chat/skills/task_delegator/workflow.py` — 既有的 WorkflowNode 管道模式（不同域，不混用）
- `src/llm_chat/app.py:476` — CLI 调用方
- `src/llm_chat/frontends/gui.py:1053` — GUI 调用方
- `src/llm_chat/frontends/feishu/adapter.py:449` — 飞书调用方
- `src/llm_chat/scheduler/scheduler.py:516` — Scheduler 调用方
