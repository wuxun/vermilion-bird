# ADR 0007：Application Service 与三层依赖边界

- 状态：Accepted
- 日期：2026-07-28

## 决策

依赖方向固定为：

```text
ember-core <- ember-agent <- llm_chat application
                              ^
                              |
                    CLI / GUI / Scheduler
```

- `ember-core` 不依赖 Agent、桌面应用或 LangChain/LangGraph。
- `ember-agent` 可依赖 `ember-core`，不依赖 `llm_chat`。
- `llm_chat.work`、`llm_chat.workflows` 是产品领域及应用服务，不依赖 PyQt、前端、LLM
  Client 或具体 ChatGraph。
- `App` 是组合根和跨服务用例门面，不保存第二套领域状态。
- WorkItem 状态只由持久化 Run 事实投影；GUI/CLI 不直接写数据库。
- LangGraph 是应用运行时实现，不能渗透到 Ember 公共 API。

以上边界由 `tests/test_architecture_boundaries.py` 使用 AST 扫描持续验证。
