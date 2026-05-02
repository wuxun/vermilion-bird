# 定时任务调度系统

## 概述

基于 APScheduler 的定时任务调度系统，支持 cron/date 触发器，任务持久化到 SQLite，支持飞书/前端双通道通知。

## 结构

```
scheduler/
├── __init__.py        # 懒加载导出（Python 3.14 pkg_resources 兼容）
├── models.py          # 数据模型（Task/TaskExecution/TaskType/TaskStatus）
├── scheduler.py       # SchedulerService（APScheduler 封装）
├── task_executor.py   # TaskExecutor（独立执行器 + 指数退避重试）
└── notification.py    # NotificationService（飞书卡片/前端消息通知）
```

## 快速定位

| 任务 | 文件 | 说明 |
|------|------|------|
| 添加新任务类型 | `models.py` | 在 TaskType 枚举添加新值 |
| 添加新触发器类型 | `scheduler.py` | `_build_trigger()` 方法 |
| 修改任务执行逻辑 | `task_executor.py` | `_execute_llm_chat()` 等 |
| 修改通知方式 | `notification.py` | `send_notification()` |
| 添加新的通知渠道 | `notification.py` | 新增 `_send_xxx_notification()` |

## 核心接口

### SchedulerService

```python
class SchedulerService:
    def start(self) -> None                          # 启动调度器
    def shutdown(self, wait: bool = True) -> None    # 关闭调度器
    def add_task(self, task: Task) -> str            # 添加任务
    def remove_task(self, task_id: str) -> bool      # 删除任务
    def pause_task(self, task_id: str) -> bool       # 暂停任务
    def resume_task(self, task_id: str) -> bool      # 恢复任务
    def trigger_task(self, task_id: str) -> bool     # 手动触发
    def get_task(self, task_id: str) -> Optional[Task] # 查询任务
    def get_all_tasks(self) -> List[Task]            # 查询所有任务
```

### Task（数据模型）

```python
class Task(BaseModel):
    id: str                     # UUID
    name: str                   # 显示名称
    task_type: TaskType         # LLM_CHAT / SKILL_EXECUTION / SYSTEM_MAINTENANCE
    trigger_config: Dict        # {"cron": "0 9 * * *"} 或 {"date": "2026-..."}
    params: Dict                # 任务参数
    enabled: bool               # 是否启用
    max_retries: int = 3        # 最大重试次数
    notify_enabled: bool = True # 是否发送通知
    notify_targets: Optional[list] # 通知目标
```

### TaskType 枚举

| 值 | 说明 |
|---|------|
| `LLM_CHAT` | LLM 对话任务：向模型发送消息 |
| `SKILL_EXECUTION` | 技能执行任务：调用指定技能 |
| `SYSTEM_MAINTENANCE` | 维护任务：记忆清理/会话归档等 |

## 架构

```
用户/LLM (通过 SchedulerSkill)
    │
    v
SchedulerService (APScheduler BackgroundScheduler)
    │
    ├── cron trigger ──→ Job 触发
    ├── date trigger ──→ Job 触发
    │
    v
_execute_job_wrapper (模块级函数，避免 pickle 问题)
    │
    v
SchedulerService._execute_task()
    │
    ├── TaskExecutor (重试逻辑)
    │   ├── _execute_llm_chat() → App.client.chat()
    │   ├── _execute_skill() → SkillManager
    │   └── _execute_maintenance() → 记忆清理/归档
    │
    v
NotificationService
    ├── Frontend (display_message)
    └── Feishu (FeishuAdapter.send_message)
```

## 数据持久化

任务和执行记录存储在 `Storage` 统一 SQLite 数据库（`tasks` / `task_executions` 表）。
APScheduler 自身 job 状态存储在 `apscheduler_jobs` 表（SQLAlchemyJobStore）。

## 通知目标优先级

1. 任务自身 `notify_targets`
2. 配置文件 `notification.default_targets`
3. 数据库最近飞书对话（自动回退）

## Python 3.14 兼容

- `__init__.py` 使用 `__getattr__` 懒加载 `SchedulerService`，避免导入时触发 pkg_resources 依赖
- `scheduler.py` 在 `_setup_scheduler()` 中延迟导入 APScheduler
- `pkg_resources.py` shim（`src/llm_chat/`）在导入前加载确保兼容

## 约定

- 所有时间使用 `datetime.now()`（无时区）
- 任务 ID 使用 `uuid.uuid4()`
- Job 函数使用模块级 `_execute_job_wrapper`（非绑定方法，避免 pickle 问题）
- 全局 `_scheduler_registry` 字典用于查找 SchedulerService 实例

## CLI 命令

```bash
# 创建 cron 任务
vermilion-bird schedule create --name "日报" --cron "0 9 * * *" --message "生成今日摘要"

# 创建一次性任务
vermilion-bird schedule create --name "提醒" --date "2026-12-31 23:59:00" --message "新年快乐！"

# 管理
vermilion-bird schedule list
vermilion-bird schedule delete <task_id>
vermilion-bird schedule pause <task_id>
vermilion-bird schedule resume <task_id>
vermilion-bird schedule trigger <task_id>
```
