# F3 QA 测试发现的问题

## 测试日期: 2026-03-29

---

## 1. 严重问题 - GUI 管理界面未实现 (BLOCKER)

**问题描述**:
- `src/llm_chat/frontends/scheduler_dialog.py` 不存在
- 计划中的 Task 12-14 (GUI 任务列表、编辑器、执行历史) 全部未完成
- 用户无法通过 GUI 界面管理定时任务

**影响**:
- 无法满足计划中的 "Must Have" 要求：GUI 管理界面
- 用户只能通过编程方式创建和管理任务

**建议修复**:
- 实现 `scheduler_dialog.py` 包含：
  - `SchedulerDialog` - 任务列表对话框
  - `TaskEditDialog` - 任务编辑对话框
  - `ExecutionHistoryDialog` - 执行历史对话框

---

## 2. 环境兼容性问题 (HIGH)

**问题描述**:
- SQLAlchemy 2.0 与 Python 3.14 不兼容
- 错误信息：`AssertionError: Class <class 'sqlalchemy.sql.elements.SQLCoreOperations'> directly inherits TypingOnly but has additional attributes`

**影响**:
- 所有 scheduler 相关测试无法运行
- 无法验证测试覆盖率

**建议修复**:
1. 升级 SQLAlchemy 到兼容 Python 3.14 的版本（如果可用）
2. 或在 pyproject.toml 中限制 Python 版本为 < 3.14

---

## 3. CLI 集成测试未完成 (MEDIUM)

**问题描述**:
- Task 16 (CLI 集成测试) 未完成
- `tests/integration/test_scheduler_cli.py` 不存在

**影响**:
- 无法验证 CLI 模式下的任务执行和恢复功能

---

## 实现状态总结

### 已完成 (后端核心):
- ✅ Task 1-6: 基础设施 + 数据模型
- ✅ Task 7: 调度器核心 (SchedulerService)
- ✅ Task 8: 任务执行器 (TaskExecutor)
- ✅ Task 9-11: 三种任务类型执行
- ✅ Task 15: App 集成
- ✅ Storage 扩展 (tasks/task_executions 表)

### 未完成:
- ❌ Task 12: GUI 任务列表
- ❌ Task 13: GUI 任务编辑器
- ❌ Task 14: GUI 执行历史
- ❌ Task 16: CLI 集成测试

### 完成率: 11/16 任务 = 68.75%

---

## 功能验证清单

| 功能 | 状态 | 备注 |
|------|------|------|
| 任务创建 (Cron) | ⚠️ | 后端支持，无 GUI |
| 任务创建 (一次性) | ⚠️ | 后端支持，无 GUI |
| 任务执行 (LLM 对话) | ✅ | 已实现 |
| 任务执行 (技能调用) | ✅ | 已实现 |
| 任务执行 (系统维护) | ✅ | 已实现 |
| 任务暂停/恢复 | ⚠️ | 后端支持，无 GUI |
| 任务删除 | ⚠️ | 后端支持，无 GUI |
| 手动触发 | ⚠️ | 后端支持，无 GUI |
| 执行历史查询 | ⚠️ | 后端支持，无 GUI |
| 数据持久化 | ✅ | 已实现 |
| 重试逻辑 | ✅ | 已实现 |
| GUI 界面 | ❌ | 未实现 |
| CLI 命令 | ⚠️ | 未验证 |
