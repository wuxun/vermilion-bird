# 定时任务功能 - Scope Fidelity Check

## 馂览

**验证时间**: 2026-03-29
**验证者**: Sisyphus-Junior (Autonomous Agent)

**验证方法**: 代码审查 + 文件检查

**计划文件**: .sisyphus/plans/scheduled-tasks.md

**验证范围**: 宀 Must Must have + 7 must not have 列

---

## Must Have 验证结果

### ✅ 1. 支持三种任务类型（LLM 对话、技能执行、系统维护）
**位置**: 
- `src/llm_chat/scheduler/models.py:10-13` - TaskType 枚举定义
- `src/llm_chat/scheduler/task_executor.py:50-57` - 任务类型执行逻辑

**计划要求**: 三种任务类型（LLm chat, skill execution, maintenance)
**实际实现**: 三种任务类型（LLm_chat, skill_execution, system_maintenance)

**状态**: ✅ 完全符合

**备注**: 任务类型名称略有差异，但功能一致
- LLM_CHAT: 调用 LLM 对话
- SKILL_EXECUTION: 执行技能/工具调用
- SYSTEM_MAINTENANCE: 系统维护任务（清理记忆、归档会话、演进理解)

---

### ✅ 2. 支持两种触发器（Cron + 一次性)
**位置**: `src/llm_chat/scheduler/scheduler.py:257-279`
**计划要求**: Cron 表达式 + 一次性任务（不支持固定间隔）
**实际实现**: Cron + Date 触发器
**状态**: ✅ 完全符合
**证据**:
```python
# Cron 触发器
if "cron" in trigger_config:
    cron_expr = trigger_config["cron"]
    parts = cron_expr.split()
    if len(parts) == 5:
        return CronTrigger(
            minute=parts[0],
            hour=parts[1],
            day=parts[2],
            month=parts[3],
            day_of_week=parts[4],
            timezone=trigger_config.get("timezone"),
        )

# Date 触发器（一次性任务）
if "date" in trigger_config:
    date_str = trigger_config["date"]
    run_date = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
    return DateTrigger(run_date=run_date)
```

**备注**: 实现完整，符合计划要求

---

### ✅ 3. 任务持久化（SQLite）
**位置**: 
- `src/llm_chat/storage.py:13` - 使用现有数据库
- `src/llm_chat/storage.py:77-87` - tasks 表
- `src/llm_chat/storage.py:89-99` - task_executions 表

- `src/llm_chat/storage.py:189-313` - 存储方法实现
**计划要求**: 任务持久化到现有数据库 `.vb/vermilion_bird.db`（不创建独立的 scheduler.db）
**实际实现**: 
- 使用现有数据库: ✅
- tasks 表存在: ✅
- task_executions 表存在: ✅
- 完整的存储方法: ✅
**状态**: ✅ 完全符合
**验证命令**:
```bash
$ ls ~/.vermilion-bird/scheduler.db 2>/dev/null || echo "OK: no scheduler.db"
OK: no scheduler.db
```
**备注**: 完全符合计划要求

---

### ❌ 4. GUI 管理界面
**位置**: `src/llm_chat/frontends/scheduler_dialog.py`
**计划要求**: GUI 管理界面（任务列表、编辑器、执行历史）
**实际实现**: ❌ 未实现
**状态**: ❌ 缺失（严重)
**影响**: 无法通过 GUI 管理定时任务
**备注**: Task 12-14 未完成，影响用户体验

**建议**: 需要实现 GUI 管理界面以满足计划要求

---

### ✅ 5. 执行历史记录
**位置**: 
- `src/llm_chat/storage.py:89-99` - task_executions 表
- `src/llm_chat/storage.py:272-313` - save_execution() 方法
- `src/llm_chat/storage.py:304-313` - load_executions() 方法
**计划要求**: 保存完整执行历史（开始时间、结束时间、结果、错误信息)
**实际实现**: ✅ 完整实现
**状态**: ✅ 完全符合
**证据**:
```python
# task_executions 表结构
CREATE TABLE IF NOT EXISTS task_executions (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP,
    result TEXT,
    error TEXT,
    retry_count INTEGER DEFAULT 0,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
);
```
**备注**: 执行历史记录功能完整，支持查询、分页和结果/错误详情
---

### ✅ 6. 失败重试机制
**位置**: `src/llm_chat/scheduler/task_executor.py:44-87`
**计划要求**: 任务失败自动重试（最多 3 次)
**实际实现**: ✅ 已实现
**状态**: ✅ 完全符合
**证据**:
```python
retry_count = 0
max_attempts = task.max_retries + 1

last_error: Optional[str] = None
result: Optional[str] = None

while retry_count < max_attempts:
    try:
        # 执行任务逻辑
        if task.task_type == TaskType.LLM_CHAT:
            result = self._execute_llm_chat(task)
        elif task.task_type == TaskType.SKILL_EXECUTION:
            result = self._execute_skill(task)
        elif task.task_type == TaskType.SYSTEM_MAINTENANCE:
            result = self._execute_maintenance(task)
        
        # 成功则保存执行记录并返回
        execution = TaskExecution(...)
        self.task_storage.save_execution(execution)
        return execution
    
    except Exception as e:
        last_error = str(e)
        retry_count += 1
        if retry_count < max_attempts:
            # 指数退避重试
            delay = min(self.base_delay * (2 ** (retry_count - 1)), self.max_delay)
            time.sleep(delay)
```
**备注**: 重试逻辑完整实现，支持指数退避
---

### ✅ 7. 手动触发、暂停/恢复功能
**位置**: 
- `src/llm_chat/scheduler/scheduler.py:194-207` - trigger_task() 方法
- `src/llm_chat/scheduler/scheduler.py:208-220` - pause_task() 方法
- `src/llm_chat/scheduler/scheduler.py:221-232` - resume_task() 方法
- `src/llm_chat/cli.py:620-623` - CLI 刚 remove_task 命令
- `src/llm_chat/cli.py:636-639` - CLI pause task 命令
- `src/llm_chat/cli.py:651-654` - CLI resume task 命令
- `src/llm_chat/cli.py:666-670` - CLI trigger task 命令
**计划要求**: 支持手动触发、暂停/恢复任务
**实际实现**: ✅ 完整实现
**状态**: ✅ 完全符合
**证据**:
```python
# CLI 命令
@schedule_cli_group()
@click.option('--task-id', required=True, help='Remove a scheduled task')
def remove_task(task_id):
    if scheduler.remove_task(task_id):
        click.echo(f"任务 {task_id} 已删除")
    else:
        click.echo(f"任务 {task_id} 不存在或删除失败")

    
@schedule_cli.command()
@click.option('--task-id', required=True, help='Pause a scheduled task')
def pause_task(task_id):
    if scheduler.pause_task(task_id):
        click.echo(f"任务 {task_id} 已暂停")
    else:
        click.echo(f"任务 {task_id} 暂停失败或 未找到或未启用")
    
@schedule_cli.command()
@click.option('--task-id', required=True, help='resume a scheduled task')
def resume_task(task_id):
    if scheduler.resume_task(task_id):
        click.echo(f"任务 {task_id} 已恢复")
    else:
        click.echo(f"任务 {task_id} 恢复失败或 未找到或未启用")
    
@schedule_cli.command()
@click.option('--task-id', required=True, help='manually trigger a scheduled task')
def trigger_task(task_id):
    if scheduler.trigger_task(task_id):
        click.echo(f"任务 {task_id} 已手动触发")
    else:
        click.echo(f"任务 {task_id} 手动触发失败， 未找到或未启用")
```
**备注**: CLI 集成完整，支持所有任务管理操作

---

### ✅ 8. 支持 CLI 模式（无 Qt 依赖)
**位置**: `src/llm_chat/scheduler/` - 整个模块
**计划要求**: 必须支持 CLI 模式（无 Qt 依赖)
**实际实现**: ✅ 满足要求
**状态**: ✅ 完全符合
**证据**:
```bash
# 无 QThreadPool/QThread 导入
$ grep -r "QThreadPool|QThread" src/llm_chat/scheduler
# (无结果)
```
**备注**: scheduler 栲块使用纯 Python 实现，无 Qt 依赖

---

## Must NOT Have 验证结果

### ⚠️ 1. 不支持固定间隔触发
**位置**: `src/llm_chat/scheduler/scheduler.py:270-274, 281`
**计划要求**: 不支持固定间隔触发（仅 Cron + 一次性任务)
**实际实现**: ❌ 客现了 interval 触发器
**状态**: ⚠️ 违规
**严重性**: 中等
**证据**:
```python
# 第 270-274 行
if "interval" in trigger_config or "interval_seconds" in trigger_config:
    seconds = trigger_config.get("interval") or trigger_config.get(
        "interval_seconds", 60
    )
    return IntervalTrigger(seconds=seconds)

# 第 281 行 - 默认返回 interval 触发器
return IntervalTrigger(seconds=60)
```
**影响**: 
- 违反计划约束 "不支持固定间隔触发"
- 可能导致用户混淆，创建固定间隔任务而不是 cron/一次性任务
- 增加了代码复杂性和维护成本

**建议**: **立即移除** interval 触发器支持（第 270-274 行和第 281 行)，仅保留 cron 和 date 触发器

**修复建议**:
```python
# 移除 interval 触发器支持
if "interval" in trigger_config or "interval_seconds" in trigger_config:
    raise ValueError("Interval trigger not supported. Use cron or date triggers only.")
    
if "date" in trigger_config:
    # ... existing date trigger code ...
    
# 移除默认返回值
raise ValueError("Invalid trigger config. Must specify 'cron' or 'date'")
```
**备注**: 这是一个明确的计划违规，需要在修复后重新验证

---

### ✅ 2. 不支持任务间依赖
**位置**: 未发现相关代码
**计划要求**: 不支持任务间依赖（第一版保持简单)
**实际实现**: ✅ 笌发现
**状态**: ✅ 完全符合
**备注**: scheduler 没有实现任务依赖功能

---

### ✅ 3. 不支持分布式调度
**位置**: 未找到相关代码
**计划要求**: 不支持分布式调度（单机应用)
**实际实现**: ✅ 满足要求
**状态**: ✅ 完全符合
**备注**: scheduler 使用单机 Background 模式，无分布式支持
---

### ✅ 4. 不在工作线程直接操作 GUI
**位置**: scheduler 模块
**计划要求**: 不在工作线程直接操作 GUI（使用 QMetaObject.invokeMethod）
**实际实现**: ✅ scheduler 模块无 GUI 操作代码
**状态**: ✅ 完全符合
**备注**: scheduler 模块不包含任何 GUI 代码
---

### ✅ 5. 不引入 Celery 等重型框架
**位置**: 未找到相关导入
**计划要求**: 不引入 Celery 等重型框架（过度设计)
**实际实现**: ✅ 满足要求
**状态**: ✅ 完全符合
**备注**: 使用 APScheduler 轌非 Celery
---

### ✅ 6. 不在任务执行时阻塞主线程
**位置**: `src/llm_chat/scheduler/scheduler.py:14, 67-68`
**计划要求**: 不在任务执行时阻塞主线程（所有任务异步执行)
**实际实现**: ✅ 满足要求
**状态**: ✅ 完全符合
**证据**:
```python
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.executors.pool import ThreadPoolExecutor

# 使用后台调度器
self._scheduler = BackgroundScheduler(...)

# 使用线程池执行器
executors = {
    "default": ThreadPoolExecutor(max_workers=self._config.max_workers)
}
```
**备注**: 使用 BackgroundScheduler 和 ThreadPoolExecutor 绡保异步执行
---

## 任务完成度检查

### Wave 1: 基础设施 + 数据模型 (6 个任务)
- ✅ Task 1: 添加 APScheduler 依赖
- ✅ Task 2: 定义数据模型
- ✅ Task 3: 配置扩展
- ✅ Task 4: 持久化存储
- ✅ Task 5: 测试基础设施
- ✅ Task 6: 模块入口

### Wave 2: 核心调度器 + 执行器 (5 个任务)
- ✅ Task 7: 调度器核心
- ✅ Task 8: 任务执行器
- ✅ Task 9: LLM 对话任务
- ✅ Task 10: 技能执行任务
- ✅ Task 11: 系统维护任务

### Wave 3: GUI + 集成 (2 个任务)
- ❌ Task 12: GUI 任务列表 - **未实现**
- ❌ Task 13: GUI 任务编辑器 - **未实现**
- ❌ Task 14: GUI 执行历史 - **未实现**
- ✅ Task 15: App 集成
- ✅ Task 16: CLI 集成测试

### Final Wave (待完成)
- ⏳ Task F1: Plan compliance audit
- ⏳ Task F2: Code quality review
- ⏳ Task F3: Real manual QA
- ✅ Task F4: Scope fidelity check (本任务)

---

## 总结与建议

### 关键发现
1. **GUI 管理界面缺失**: Task 12-14 未实现，无法通过 GUI 管理定时任务
2. **Interval 触发器违规**: 连现了计划明确禁止的 interval 触发器

3. **功能基本完整**: 核心调度器、任务执行器、持久化、 CLI 集成都已实现
4. **代码质量良好**: 无 QThreadPool/QThread 使用，无 Celery 等重型框架

### 建议
1. **立即实现 GUI 管理界面** (Task 12-14)
   - 创建 `scheduler_dialog.py`
   - 实现任务列表、编辑器、执行历史界面
   
2. **移除 interval 触发器支持**
   - 修改 `scheduler.py:270-274, 281`
   - 仅保留 cron 和 date 触发器
   - 更新相关文档和注释
   
3. **完成剩余的 Final Wave 任务** (F1-f3)
   - 完成所有验证任务后获取用户确认

---

## 最终评估

**状态**: ⚠️ **REJECT**
**原因**: 
1. Must Have 缺失: GUI 管理界面未实现
2. Must NOT Have 迡规: Interval 触发器违规

**需要修复**: 是
1. 实现 GUI 管理界面（scheduler_dialog.py）
2. 移除 interval 触发器支持

**阻塞发布**: 是，直到修复完成并重新验证
