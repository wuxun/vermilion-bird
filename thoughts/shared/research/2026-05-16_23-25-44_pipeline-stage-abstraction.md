---
date: 2026-05-16T23:25:44+0800
author: wuxun
commit: 6d75917
branch: main
repository: vermilion-bird
topic: "PipelineStage 抽象 — 代码库可行性研究"
tags: [research, codebase, pipeline, chat-core, architecture]
status: complete
last_updated: 2026-05-16T23:25:44+0800
last_updated_by: wuxun
---

# Research: PipelineStage 抽象 — 代码库可行性研究

## Research Question

将 ChatCore 当前的方法级管道拆解升级为正式的 `PipelineStage` ABC 异步抽象：10 个独立 Stage 类通过 `PipelineRunner` 顺序执行，`PipelineContext` dataclass 承载全管道状态。需要验证：抽象契约与现有模式兼容性、上下文状态完整性、短路机制正确性、异步化对 4 个调用方的影响、阶段间依赖关系、以及历史先例教训。

## Summary

**可行。** 10 个阶段均可从现有代码精确提取，无架构障碍。三个关键设计决策在研究中浮现并确认：(1) PipelineContext 必须区分 `user_message`(原始) 和 `effective_message`(意图覆盖后)；(2) `teardown()` 必须像 `finally` 一样始终执行，Stage 8-10 副作用逻辑应放入 teardown；(3) 跨请求可变状态 (`_current_style`, `_prompt_skills_context`) 用 `MutableStrHolder` 包装注入。`@observe` 装饰器需要新增 `asyncio.iscoroutinefunction` 分支。4 个调用方均可通过 `asyncio.run()` 做最小化桥接。历史先例警告：双轨管道是 #1 bug 来源，必须原子替换，不留 fallback。

## Detailed Findings

### PipelineStage ABC 契约与 BaseTool 的对比

当前 `BaseTool` (`tools/base.py:6-18`) 定义 `name`(抽象属性)、`description`(抽象属性)、`get_parameters_schema()`(抽象方法)、`execute(**kwargs) -> str`(同步抽象方法)。PipelineStage 与之不同：只需 `name` 和 `process(ctx) -> PipelineContext`(异步)，另有可选的 `setup(ctx)`/`teardown(ctx)`(异步，默认 no-op)。`setup`/`teardown` 的先例是 `decision/submit_tool.py:37-55` 的 `init_card_context()`/`clear_card_context()` 配对——LLMCallStage 将吸收此模式。

**`@observe` 异步适配**：当前 `observability.py:195-221` 的装饰器仅处理同步函数。需要在 decorator 内加 `asyncio.iscoroutinefunction(func)` 分支，产出 `async def async_wrapper`，将 `result = func(*args, **kwargs)` 改为 `result = await func(*args, **kwargs)`。`Observability.start_span()`/`end_span()` 本身可保持同步——`threading.Lock` 临界区 <1µs，在 asyncio 上下文中可忽略。

### PipelineContext 状态清单

当前散落状态通过两个通路传递：`_prepare_pipeline()` 返回 4-tuple `(system_context, processed_history, processed_message, params)`，`send_message()` 持有局部变量 `decision`、`effective_message`、`conv`、`response`。PipelineContext 需承载以下字段：

**直接字段**：`conversation_id: str`、`user_message: str`(原始输入)、`effective_message: str`(覆盖后)、`system_context: Optional[str]`、`processed_history: List[Dict]`、`processed_message: str`、`params: Dict`、`response: str`、`cancel_event: Optional[threading.Event]`、`status: str`、`error: Optional[str]`

**嵌入现有类型**：`routing_decision: Optional[RoutingDecision]`(`intent/types.py:27-53`)、`pending_card: Optional[DecisionCard]`(`decision/schema.py:58-135`)、`compression_result: Optional[CompressionResult]`(`context/types.py:33-38`)

**流式回调**(Optional，仅 LLMCallStage 使用)：`on_chunk`、`on_tool_start`、`on_tool_end`、`on_context_update`、`on_card`

**扩展槽**：`metadata: Dict[str, Any]`——跨阶段通信的键值袋，无需修改 PipelineContext schema。

### PipelineContext 双消息字段（关键设计决策）

`chat_core.py:398` 持久化 `original_message`（如 `"/search python typing"`），但 `chat_core.py:449` 用 `effective_message`（如 `"python typing"`）做 FTS5 搜索。PipelineContext 必须有两个字段：`user_message`(IntentStage 不修改) 和 `effective_message`(IntentStage 设置为 `decision.override_message or ctx.user_message`)。ShortcutStage 用 `user_message` 持久化，SystemContextStage 用 `effective_message` 搜索。

### Teardown 始终执行语义（关键设计决策）

当前 `chat_core.py:194-200` 用 `try/finally` 保证 `clear_card_context()` 始终清理。PipelineRunner 必须采用相同模式：每个 stage 的 `process()` 包装在 `try/finally` 中，`teardown()` 在 finally 块中执行。Stage 8-10（PersistAssistant、MemoryExtract、TokenRecord）应将副作用逻辑放入 `teardown()` 中，保证即使 LLM 调用异常也能记录 token 和提取记忆。

### 跨请求可变状态：MutableStrHolder（关键设计决策）

ChatCore 有两个跨请求可变实例状态：`_prompt_skills_context`(App 初始化时设置一次) 和 `_current_style`(用户 `/style` 时修改)。两者不能被放入 per-request 的 PipelineContext。创建薄的 `MutableStrHolder`(get/set) 包装，构造时注入给 ShortcutStage(写 style)和 SystemContextStage(读两者)。ChatCore `__init__` 持有引用，供外部设置。

### 短路机制

`IntentClassifier.classify()`(`intent/classifier.py:210`) 产出 `RoutingDecision`，其中 `skip_llm=True` + `direct_response`(如 `/help`)或 `override_message`(如 `__style__:academic`)。`_handle_shortcut()`(`chat_core.py:302-388`) 处理 5 种短路类型，每种都调用 `conv.add_user_message(original_message)` + `conv.add_assistant_message(response)`。

ShortcutStage 需要 `ConversationManager` 通过构造函数注入，在 `process()` 中调用 `self._conversation_manager.get_conversation(ctx.conversation_id)` 获取 `conv`。ShortcutStage 必须使用 `ctx.user_message`(原始)做 `add_user_message()`，而非 `ctx.effective_message`。

### 系统上下文构建：依赖注入策略

`_build_system_context()`(`chat_core.py:451-505`) 拼接 6 部分。依赖分 3 类：

**A. Request-scoped → 从 PipelineContext 读**：`intent`(来自 `ctx.routing_decision.intent`)、`effective_message`(来自 `ctx.effective_message`)

**B. Stable constants → 模块级 import**：`_DECISION_CARD_PROMPT`、`_SOCRATIC_PROMPT`、`_SOCRATIC_INTENTS`、`SOUL_STYLE_PRESETS`

**C. Mutable app state → MutableStrHolder 注入**：`_prompt_skills_context`、`_current_style`

`ConversationManager` 通过构造函数注入——`SystemContextStage` 用它调用 `get_conversation(id)._memory_manager.build_system_prompt()` 和 `search_messages()`。

### 压缩管道与模型路由

`_compress_context()`(`chat_core.py:572-645`) → `ContextManager.process_context()`(`context/manager.py:60-130`)。重压缩回退(`chat_core.py:609-617`)应在 CompressStage 内部处理，但需发出 `was_recompressed=True` 信号给下游日志。

ModelRouteStage 产出 `final_model_name` → CompressStage 将其传入 `get_context_limit(model_name)`(`chat_core.py:607`)做 token 上限校验。这要求 ModelRouteStage 必须在 CompressStage 之前执行——严格顺序依赖。

### LLM 调用阶段：Card Context 生命周期

LLMCallStage 映射 try/finally 模式：`setup()` → `init_card_context()`(`submit_tool.py:37-47`，创建 ContextVar 隔离的 request_id)，`process()` → `_call_llm()`/`_call_llm_stream()`，`teardown()` → `get_pending_card()` → `on_card` 回调 → `clear_card_context()`。流式中断（`_cancel_event`）时 teardown 仍执行——`submit_card()` 是原子写，不存在半成品卡片。

### 阶段严格依赖关系

| 严格链 | 阶段 | 原因 |
|--------|------|------|
| 0→0a | Intent→Shortcut | ShortcutStage 需 `RoutingDecision.skip_llm` 和 `direct_response` |
| 1→3 | PersistUser→History | Stage 1 写 SQLite 后 Stage 3 读并 `history[:-1]` 剥离刚写入的消息。违反顺序则历史错乱 |
| 2→5→6 | SystemContext→Compress→LLM | 系统上下文必须先构建，压缩后才能 LLM 调用 |
| 3→5→6 | History→Compress→LLM | 历史必须先取出再压缩 |
| 4→5 | ModelRoute→Compress | 模型名必须在压缩前确定（用于 token 上限校验） |

**可并行/重排的**：Stage 2 和 Stage 3 独立（可异步并行），Stage 8/9/10 两两独立（可任意顺序）。

### 异步调用方适配

4 个调用方各不相同：

| 调用方 | 当前模式 | 最小改动 |
|--------|---------|---------|
| `app.py:476` (CLI) | 同步回调链 | `asyncio.run()` 或改为 `async def handle_message` |
| `gui.py:1053` (GUI) | `threading.Thread(daemon=True)` + PyQt6 signal 跨线程 | `asyncio.run()` 在线程内，signal emit 模式不变 |
| `feishu/adapter.py:449` (飞书) | `ThreadPoolExecutor` + `threading.Lock` per-conv | `with conv_lock: asyncio.run(...)` |
| `scheduler/scheduler.py:516` | APScheduler `ThreadPoolExecutor(max_workers=4)` | `asyncio.run(...)` |

PipelineRunner 对调用上下文完全无感——它是纯协程链，被 `asyncio.run()` 或 `await` 调用均可。

### 阶段列表快照 vs 锁

`insert_stage()`/`remove_stage()` 在运行时可能并发修改阶段列表。建议 PipelineRunner 在 `run()` 入口点对 `List[PipelineStage]` 做浅拷贝快照——O(n) 成本可忽略，无锁，避免执行中列表被外部修改。

## Code References

- `src/llm_chat/chat_core.py:136-690` — ChatCore 全部管道逻辑，`send_message`(176)、`send_message_stream`(229)、`_prepare_pipeline`(391-437)、`_finalize_pipeline`(439-448)、`_handle_shortcut`(302-388)、`_build_system_context`(451-505)、`_compress_context`(572-645)、`_call_llm`(651-662)、`_call_llm_stream`(668-712)、`_extract_pending_card`(745-757)、`_extract_memory_async`(759-772)、`_record_tokens`(792-822)
- `src/llm_chat/tools/base.py:5-47` — BaseTool ABC 参考模式
- `src/llm_chat/decision/submit_tool.py:1-183` — Card context：`init_card_context`(37-47)、`clear_card_context`(49-55)、`submit_card`(57-68)、`get_pending_card`(78-86)、`SubmitDecisionCardTool`(99-183)
- `src/llm_chat/utils/observability.py:53,67-79,195-221` — `@observe` 同步装饰器、`threading.Lock`、`start_span()`/`end_span()`
- `src/llm_chat/intent/types.py:27-53` — `RoutingDecision` dataclass（8 字段）
- `src/llm_chat/intent/classifier.py:210-390` — `IntentClassifier.classify()` + Layer 0-1 路由
- `src/llm_chat/context/types.py:1-48` — `CompressionLevel`、`ContextMessage`、`CompressionResult`
- `src/llm_chat/context/manager.py:60-130` — `ContextManager.process_context()`
- `src/llm_chat/decision/schema.py:58-135` — `DecisionCard` + `DecisionOption` Pydantic 模型
- `src/llm_chat/conversation.py:151` — `Conversation.get_history()` → `Storage.get_messages()`
- `src/llm_chat/app.py:130-135` — `_init_chat_core()` 创建 ChatCore；`app.py:471-489` — `handle_message` 回调
- `src/llm_chat/frontends/gui.py:1040-1072` — daemon Thread + PyQt6 signal 跨线程
- `src/llm_chat/frontends/feishu/adapter.py:424-471` — `_process_with_llm()` + ThreadPoolExecutor
- `src/llm_chat/scheduler/scheduler.py:491-520` — `_run_llm_chat_task()` + APScheduler ThreadPoolExecutor

## Integration Points

### Inbound References
- `src/llm_chat/app.py:476` — CLI 通过 `handle_message` 回调调用 `chat_core.send_message()`
- `src/llm_chat/frontends/gui.py:1053` — GUI 通过 daemon Thread 调用 `chat_core.send_message_stream()`
- `src/llm_chat/frontends/feishu/adapter.py:449` — 飞书通过 `_process_with_llm()` 调用 `chat_core.send_message()`
- `src/llm_chat/scheduler/scheduler.py:516` — Scheduler 通过 ThreadPoolExecutor 调用 `chat_core.send_message()`

### Outbound Dependencies
- `src/llm_chat/client/__init__.py` — `LLMClient`（chat/chat_with_tools/chat_stream_with_tools）
- `src/llm_chat/conversation.py` — `ConversationManager`、`Conversation`（add_message、get_history）
- `src/llm_chat/context/manager.py` — `ContextManager`（process_context）
- `src/llm_chat/memory/manager.py` — `MemoryManager`（build_system_prompt、schedule_extraction）
- `src/llm_chat/decision/submit_tool.py` — card context（init/clear/submit/get_pending）
- `src/llm_chat/utils/observability.py` — `@observe` 装饰器、`get_observability()`
- `src/llm_chat/intent/classifier.py` — `IntentClassifier`

### Infrastructure Wiring
- `src/llm_chat/app.py:130-135` — `_init_chat_core()` 创建 ChatCore 并注入 client、conversation_manager、config
- `src/llm_chat/app.py:67` — `_init_prompt_skills()` → `chat_core.set_prompt_skills_context()`

## Architecture Insights

1. **PipelineStage ABC 遵循项目既有模式**：与 `BaseTool` 相同的属性+抽象方法风格，加上 `init_card_context/clear_card_context` 先例的 setup/teardown 生命周期
2. **10 个阶段严格顺序链**：仅 Stage 2-3、Stage 8-9-10 可内部重排。Stage 1→3 有隐藏约束——SQLite 先写后读 + `history[:-1]` 剥离
3. **异步化影响范围可控**：全部 4 个调用方可用 `asyncio.run()` 作为最小化桥接，无共享 event loop 依赖
4. **可扩展性**：`insert_stage(after_name, stage)` + `remove_stage(name)` API 允许在 10 个命名锚点间插入新阶段

## Precedents & Lessons

6 个历史先例分析了 5 次相关提交。

### Precedent: Conversation.send_message() → 5-stage Pipeline Decomposition
**Commit(s)**: `f93664e` — "refactor: 拆解 Conversation.send_message() 巨石方法为 Pipeline 阶段" (2026-05-02)
**Blast radius**: 2 files across 2 layers
  `src/llm_chat/conversation.py` — 5-stage pipeline
  `docs/architecture-optimization.md` — 文档更新

**Follow-up fixes**:
- `7b49e48` — `count_tokens` 缺失导入导致崩溃 (2026-05-03)
- `e0e91a8` — 双轨归一：删除 Conversation 管道，ChatCore 成为唯一管道 (2026-05-03)

**Takeaway**: 管道重构产生双轨问题——Conversation 和 ChatCore 各自有 `send_message` 实现，13 小时后才归并。新抽象必须是**唯一**管道，从第一天起就不留 fallback。

### Precedent: ChatCore Unified Engine Introduction
**Commit(s)**: `9e781f5` — "refactor: 引入 ChatCore 统一对话引擎" (2026-05-02)
**Blast radius**: 8 files across 5 layers, net -239 lines

**Follow-up fixes** (4):
- `328e4c1` — `/remember` 捷径在 stream 路径缺失 → SQLite NOT NULL crash (2026-05-04)
- `c95a8de` — ChatCore 创建错误 session ID 给飞书 `/new` (2026-05-09)
- `bef11b4` — 意图路由模型未传入 `_compress_context` (2026-05-15)
- `1e8bce1` — 压缩后 token 校验不一致 (2026-05-15)

**Takeaway**: `send_message` 和 `send_message_stream` 双路径是反复出现的分叉 bug 来源。异步转换必须同时触及两条路径，确保 ShortcutStage 覆盖所有 5 种捷径类型。

### Precedent: BaseFrontend ABC + Architecture Phases 1-2
**Commit(s)**: `8c761fe`, `8bfa454`, `c64929a` (2026-03-21)
**Blast radius**: 9 files across 4 layers

**Follow-up fixes**:
- `02c66ac` — `from pathlib import Path` 缺失→启动崩溃 (2026-05-03, 43d later)
- `7b49e48` — 引入的 `ConversationService` 贫血删除 (2026-05-03)

**Takeaway**: 仅做委托的抽象是死重。每个 PipelineStage 必须拥有实际逻辑，不能只是一个方法调用包装。导入卫生在模块拆分时退化——将 10 个 stage 拆到独立文件需特别关注。

### Precedent: Test Suite Breakage After Pipeline Refactoring
**Commit(s)**: `b069303` — "fix: test suite + 3 source bugs discovered during self-test" (2026-05-15)
**Blast radius**: 8 test files

**Takeaway**: 自测发现 3 个作者未察觉的源 bug。应将 `poetry run pytest` 作为硬性关卡，非软性目标。

### Composite Lessons

1. **双轨管道是 #1 bug 来源** — `f93664e`→`e0e91a8` 的 Conversation+ChatCore 双管道和 `328e4c1` 的 sync vs stream 分叉都证实了这点。新抽象必须原子替换 `_prepare_pipeline`/`_finalize_pipeline`。
2. **ABC 仅做委托会被删除** — `ConversationService` 在 Phase 1 引入，`e0e91a8` 删除。每个 PipelineStage 必须拥有真实逻辑。
3. **send_message 和 send_message_stream 必须同步** — 捷径处理器的遗漏 (`/remember`) 导致 stream 路径静默崩溃。
4. **异步签名转换级联影响 4+ 调用方** — GUI 需 PyQt6 事件循环桥接（`asyncio.run()` 在线程内或 `qasync`），飞书有自己的异步适配层。
5. **导入卫生在重构时退化** — 三次先例 (`count_tokens`, `Path`, compressor NameError) 都因移动代码导致导入缺失。
6. **`architecture-optimization.md` 已有 4 阶段 PipelineStage 草稿** — 150-263 行。FRD 的 10 阶段设计是其演进。
7. **测试应在"完成"前运行** — FRD 验收标准应包含"pytest 零失败"作为硬性门禁。

## Historical Context (from thoughts/)
- `thoughts/shared/discover/2026-05-16_22-06-03_formal-pipeline-stage-abstraction.md` — 前置 FRD：9 需求、9 决策

## Developer Context

**Q (discover: PipelineStage ABC 设计：生命周期钩子)**: PipelineStage ABC 是否沿用项目既有的 ABC 模式 — 属性 + 抽象方法，同步 process(ctx) → ctx，外加 setup/teardown 钩子？
A: 带 setup/process/teardown 生命周期钩子；改为异步 process

**Q (discover: 异步 process)**: process() 改为异步还是保持同步？
A: 改为异步 — 为后续扩展留空间

**Q (discover: 阶段粒度)**: 10 个逻辑阶段全拆还是合并？
A: 10 个全拆 — 最大化可插拔

**Q (discover: PipelineContext 设计)**: PipelineContext 承载什么？
A: 大而全的 dataclass，含流式回调字段

**Q (discover: 短路机制)**: 管道短路如何实现？
A: `ctx.should_short_circuit` flag + PipelineRunner 检查

**Q (discover: 阶段配置)**: 阶段列表如何配置？
A: ChatCore.__init__ 硬编码列表 + insert/remove 方法

**Q (discover: 重构范围)**: 全部在范围 — 核心抽象 + 10 Stage + insert API + 异步化 + 调用方适配 + @observe

**Q (discover: 约束)**: 不改 API 签名 + 无新依赖 + 无 YAML + 测试全绿

**Q (discover: 验收标准)**: 插入验证 + CLI 正常 + 测试全绿 + 阶段指标

**Q (chat_core.py:398 vs chat_core.py:449)**: PipelineContext 需要 `user_message` 和 `effective_message` 两个字段吗？
A: 两个字段 — `user_message`(原始输入)和 `effective_message`(覆盖后)。IntentStage 设置 effective，永不修改 user_message

**Q (chat_core.py:194-200)**: teardown() 是否应像 finally 一样始终执行？
A: teardown 始终执行 — PipelineRunner 用 try/finally 包裹，Stage 8-10 副作用放 teardown

**Q (chat_core.py:147-148)**: `_prompt_skills_context` 和 `_current_style` 跨请求可变状态如何共享？
A: MutableStrHolder 包装 — 构造时注入 ShortcutStage 和 SystemContextStage

## Related Research
（无——本文件为首次研究）

## Open Questions
（无——检查点期间无显式推迟项）
