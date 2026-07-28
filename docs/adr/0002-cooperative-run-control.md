# ADR-0002：Run 采用协作式执行控制

**状态**：Accepted  
**日期**：2026-07-28

## 背景

直接把持久化 Run 改成 `cancelled` 或 `paused`，不能证明后台线程已经停止。LLM 请求、
Tool、子 Agent 或 Scheduler 可能仍在执行，造成界面状态与真实副作用不一致。

## 决策

Run 控制采用请求与确认分离的状态机：

```text
running ──request_cancel──► cancel_requested ──worker_ack──► cancelled
running ──request_pause───► pause_requested  ──checkpoint──► paused
paused  ──resume──────────► running
```

规则：

1. `RunManager` 保存控制请求并通知本进程中的执行器；
2. 执行器只在节点、LLM 响应和 Tool 调用等安全边界确认请求；
3. 取消确认前不得显示为已取消；
4. 暂停确认前必须保存可恢复 checkpoint；
5. 子 Run 继承父 Run 的控制请求；
6. 已开始且结果不确定的外部副作用仍进入 EffectOutbox 人工对账；
7. 进程重启后，未确认的请求根据 checkpoint 和恢复策略确定性收敛。

## 影响

- GUI/CLI 调用任务级控制用例，不直接修改 Run 终态；
- Chat、Graph、ToolExecutor 和 Subagent 必须消费统一控制信号；
- 不支持安全暂停的 handler 不暴露暂停入口；
- 长时间外部调用只能在调用前后响应控制，除非适配器支持主动中止。
