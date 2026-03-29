# 定时任务功能

## TL;DR

> **Quick Summary**: 为 Vermilion Bird 添加生产级定时任务功能，支持 Cron 表达式和一次性任务，可定时调用 LLM 对话、执行技能/工具、运行系统维护任务。使用 APScheduler + ThreadPoolExecutor（无 Qt 依赖），支持 GUI 和 CLI 两种模式。

> **Deliverables**:
> - 新增 `src/llm_chat/scheduler/` 模块（核心调度器、任务执行器、持久化）
> - 新增 `src/llm_chat/frontends/scheduler_dialog.py`（GUI 管理界面）
> - 集成到 App 生命周期，支持应用重启后自动恢复任务
> - 完整的测试覆盖（pytest + TDD）

> **Estimated Effort**: Large
> **Parallel Execution**: YES - 4 waves
> **Critical Path**: Wave 1 (基础) → Wave 2 (核心) → Wave 3 (GUI) → Wave FINAL (验证)

---

## Context

### Original Request
用户希望在 Vermilion Bird 系统中添加定时任务功能，支持：
1. 定时调用 LLM 对话
2. 定时执行技能/工具（包括 MCP 工具）
3. 系统维护任务（清理记忆、备份数据等）

### Interview Summary
**Key Discussions**:
- **触发方式**: Cron 表达式 + 一次性定时任务（不需要固定间隔）
- **GUI 管理**: 需要可视化界面（创建、编辑、删除、查看状态）
- **持久化**: 任务定义需要持久化，应用重启后自动恢复
- **失败处理**: 自动重试 + 日志记录
- **历史记录**: 保存完整执行历史（开始时间、结束时间、结果、错误信息）
- **运行时控制**: 手动触发、状态监控、暂停/恢复
- **参数配置**: 每个任务可配置不同的输入参数
- **测试策略**: TDD（测试驱动开发）
- **关键约束**: 必须支持 CLI 模式（无 GUI），不能依赖 QThreadPool

**Research Findings**:
- **现有架构**: 模块化分层（Config/Client/Memory/Skills/Tools/MCP/Frontend），App 统一协调
- **现有调度能力**: Memory 有后台提取任务（线程方式），MCP 使用 asyncio 事件循环，无正式调度框架
- **扩展点**: App 生命周期（app.py）、MCP 工具调用（mcp/manager.py）、Skills 加载（skills/manager.py）、Memory 调度（memory/manager.py）、前端配置（frontends/gui.py, frontends/mcp_dialog.py）
- **技术选型**: APScheduler 3.x + ThreadPoolExecutor（纯 Python，无 Qt 依赖）
- **常见陷阱**: GUI 操作必须在主线程、异常必须处理、资源必须清理

### Metis Review
**Identified Gaps** (addressed):
- **任务类型定义不清晰**: 明确三种任务类型（LLM 对话、技能执行、系统维护）
- **任务参数序列化**: 使用 JSON 序列化任务参数，确保可持久化
- **任务执行上下文**: 任务执行时需要访问 App 实例（通过闭包或上下文对象传递）
- **历史记录存储位置**: 复用现有 `.vb/vermilion_bird.db` 数据库（在 storage.py 中添加 task_executions 表）
- **并发控制**: 避免同一任务并发执行（APScheduler 的 coalesce 和 max_instances）
- **时区处理**: 使用系统本地时区，支持用户配置时区
- **任务依赖**: 不支持任务间依赖（第一版保持简单）
- **数据库复用**: 复用现有 `.vb/vermilion_bird.db`，不创建独立的 scheduler.db

---

## Work Objectives

### Core Objective
实现一个生产级定时任务系统，支持 GUI 和 CLI 两种模式，可定时执行 LLM 对话、技能/工具调用和系统维护任务，任务持久化且应用重启后自动恢复。

### Concrete Deliverables
- `src/llm_chat/scheduler/__init__.py` - 模块入口
- `src/llm_chat/scheduler/scheduler.py` - 调度器核心（APScheduler 封装）
- `src/llm_chat/scheduler/task_executor.py` - 任务执行器（支持 LLM/技能/维护任务）
- `src/llm_chat/scheduler/models.py` - 任务定义、执行历史的数据模型
- `src/llm_chat/storage.py` - 扩展现有存储类，添加任务持久化方法（复用 `.vb/vermilion_bird.db`）
- `src/llm_chat/frontends/scheduler_dialog.py` - GUI 管理界面
- `src/llm_chat/config.py` - 新增 scheduler 配置项（无独立 db_path）
- `src/llm_chat/app.py` - 集成 scheduler 到 App 生命周期
- `tests/test_scheduler/` - 完整测试套件
- `tests/test_storage.py` - 扩展测试，添加任务相关测试

### Definition of Done
- [ ] 所有测试通过（pytest）
- [ ] 代码覆盖率 ≥ 80%
- [ ] GUI 模式下可创建、编辑、删除、暂停、恢复、手动触发任务
- [ ] CLI 模式下任务正常执行
- [ ] 应用重启后任务自动恢复
- [ ] 任务执行历史可查询
- [ ] 任务失败自动重试（最多 3 次）
- [ ] 文档更新（README.md）

### Must Have
- 支持三种任务类型（LLM 对话、技能执行、系统维护）
- Cron 表达式 + 一次性任务
- 任务持久化（SQLite）
- GUI 管理界面
- 执行历史记录
- 失败重试机制
- 手动触发、暂停/恢复功能
- 支持 CLI 模式（无 Qt 依赖）

### Must NOT Have (Guardrails)
- **不使用 QThreadPool/QThread**（必须支持 CLI 模式）
- **不支持固定间隔触发**（仅 Cron + 一次性任务）
- **不支持任务间依赖**（第一版保持简单）
- **不支持分布式调度**（单机应用）
- **不在工作线程直接操作 GUI**（使用 QMetaObject.invokeMethod）
- **不引入 Celery 等重型框架**（过度设计）
- **不在任务执行时阻塞主线程**（所有任务异步执行）

---

## Verification Strategy (MANDATORY)

> **ZERO HUMAN INTERVENTION** — ALL verification is agent-executed. No exceptions.

### Test Decision
- **Infrastructure exists**: YES（pytest）
- **Automated tests**: YES (TDD)
- **Framework**: pytest + unittest.mock
- **TDD**: Each task follows RED (failing test) → GREEN (minimal impl) → REFACTOR

### QA Policy
Every task MUST include agent-executed QA scenarios.
Evidence saved to `.sisyphus/evidence/task-{N}-{scenario-slug}.{ext}`.

- **Backend/Scheduler**: Use Bash (pytest) — Run tests, assert pass/fail
- **Frontend/UI**: Use Playwright (playwright skill) — Navigate, interact, assert DOM, screenshot
- **CLI/Integration**: Use Bash (CLI commands) — Run command, validate output, check exit code

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (Start Immediately — 基础设施 + 数据模型):
├── Task 1: 添加 APScheduler 依赖 [quick]
├── Task 2: 定义数据模型（models.py） [quick]
├── Task 3: 配置扩展（config.py） [quick]
├── Task 4: 持久化存储（storage.py） [quick]
├── Task 5: 测试基础设施（test_scheduler/__init__.py） [quick]
└── Task 6: 模块入口（scheduler/__init__.py） [quick]

Wave 2 (After Wave 1 — 核心调度器 + 执行器):
├── Task 7: 调度器核心（scheduler.py） [deep]
├── Task 8: 任务执行器（task_executor.py） [deep]
├── Task 9: LLM 对话任务 [unspecified-high]
├── Task 10: 技能执行任务 [unspecified-high]
└── Task 11: 系统维护任务 [unspecified-high]

Wave 3 (After Wave 2 — GUI + 集成):
├── Task 12: GUI 任务列表（scheduler_dialog.py） [visual-engineering]
├── Task 13: GUI 任务编辑器 [visual-engineering]
├── Task 14: GUI 执行历史 [visual-engineering]
├── Task 15: App 集成（app.py） [deep]
└── Task 16: CLI 集成测试 [unspecified-high]

Wave FINAL (After ALL tasks — 4 parallel reviews, then user okay):
├── Task F1: Plan compliance audit (oracle)
├── Task F2: Code quality review (unspecified-high)
├── Task F3: Real manual QA (unspecified-high + playwright)
└── Task F4: Scope fidelity check (deep)
-> Present results -> Get explicit user okay

Critical Path: Task 1 → Task 4 → Task 7 → Task 8 → Task 15 → F1-F4 → user okay
Parallel Speedup: ~60% faster than sequential
Max Concurrent: 6 (Wave 1)
```

### Dependency Matrix

- **1-6**: — — 7-16, 1
- **7**: 1, 2, 4, 5 — 8-11, 15, 2
- **8**: 2, 7 — 9-11, 15, 2
- **9-11**: 8 — 15, 2
- **12-14**: 7, 8 — 15, 3
- **15**: 7, 8, 9-14 — 16, 4
- **16**: 15 — F1-F4, 1

### Agent Dispatch Summary

- **Wave 1**: **6** — T1 → `quick`, T2 → `quick`, T3 → `quick`, T4 → `quick`, T5 → `quick`, T6 → `quick`
- **Wave 2**: **5** — T7 → `deep`, T8 → `deep`, T9 → `unspecified-high`, T10 → `unspecified-high`, T11 → `unspecified-high`
- **Wave 3**: **5** — T12 → `visual-engineering`, T13 → `visual-engineering`, T14 → `visual-engineering`, T15 → `deep`, T16 → `unspecified-high`
- **FINAL**: **4** — F1 → `oracle`, F2 → `unspecified-high`, F3 → `unspecified-high`, F4 → `deep`

---

## TODOs

> Implementation + Test = ONE Task. Never separate.
> EVERY task MUST have: Recommended Agent Profile + Parallelization info + QA Scenarios.

### Wave 1: 基础设施 + 数据模型（6 个并行任务）

- [x] 1. 添加 APScheduler 依赖

  **What to do**:
  - 在 `pyproject.toml` 添加 `apscheduler = "^3.10.0"` 和 `sqlalchemy = "^2.0.0"`
  - 运行 `poetry lock && poetry install`
  - 验证安装成功：`poetry run python -c "from apscheduler.schedulers.background import BackgroundScheduler; print('OK')"`

  **Must NOT do**:
  - 不添加 Celery、schedule 等其他调度库
  - 不升级其他依赖版本

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 简单的依赖添加和验证任务
  - **Skills**: []
    - 无特殊技能需求

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 2-6)
  - **Blocks**: Task 7（需要 APScheduler 已安装）
  - **Blocked By**: None (can start immediately)

  **References**:
  - `pyproject.toml` - 依赖配置文件

  **Acceptance Criteria**:
  - [ ] pyproject.toml 包含 apscheduler 和 sqlalchemy 依赖
  - [ ] poetry lock 成功执行
  - [ ] poetry install 成功执行
  - [ ] 验证命令成功输出 "OK"

  **QA Scenarios**:

  ```
  Scenario: 依赖安装验证
    Tool: Bash
    Preconditions: pyproject.toml 已更新
    Steps:
      1. poetry run python -c "from apscheduler.schedulers.background import BackgroundScheduler"
      2. poetry run python -c "from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore"
    Expected Result: 两个命令都成功执行，无错误输出
    Failure Indicators: ImportError 或 ModuleNotFoundError
    Evidence: .sisyphus/evidence/task-01-dependency-check.txt
  ```

  **Commit**: YES
  - Message: `chore(deps): add apscheduler and sqlalchemy for scheduled tasks`
  - Files: `pyproject.toml, poetry.lock`
  - Pre-commit: `poetry run python -c "from apscheduler import __version__; print(__version__)"`

- [x] 2. 定义数据模型

  **What to do**:
  - 创建 `src/llm_chat/scheduler/models.py`
  - 定义 `TaskType` 枚举（LLM_CHAT, SKILL_EXECUTION, SYSTEM_MAINTENANCE）
  - 定义 `TaskStatus` 枚举（PENDING, RUNNING, PAUSED, COMPLETED, FAILED）
  - 定义 `Task` 数据类（使用 dataclass 或 Pydantic）：
    - id: str
    - name: str
    - task_type: TaskType
    - trigger_config: dict（cron 表达式或 date）
    - params: dict（任务参数，JSON 序列化）
    - enabled: bool
    - max_retries: int = 3
    - created_at: datetime
    - updated_at: datetime
  - 定义 `TaskExecution` 数据类（执行历史）：
    - id: str
    - task_id: str
    - status: TaskStatus
    - started_at: datetime
    - finished_at: datetime | None
    - result: str | None
    - error: str | None
    - retry_count: int
  - 编写单元测试（TDD）：`tests/test_scheduler/test_models.py`

  **Must NOT do**:
  - 不引入 ORM 框架（使用纯 Pydantic/dataclass）
  - 不添加 GUI 相关字段

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 数据模型定义，逻辑清晰
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 3-6)
  - **Blocks**: Task 4, Task 7, Task 8（需要数据模型）
  - **Blocked By**: None

  **References**:
  - `src/llm_chat/config.py` - 参考 Pydantic 模型定义风格
  - `src/llm_chat/mcp/types.py` - 参考枚举和数据类定义

  **Acceptance Criteria**:
  - [ ] models.py 包含所有枚举和数据类
  - [ ] 测试文件 test_models.py 存在
  - [ ] `poetry run pytest tests/test_scheduler/test_models.py -v` 通过
  - [ ] Task 和 TaskExecution 可 JSON 序列化/反序列化

  **QA Scenarios**:

  ```
  Scenario: 数据模型验证
    Tool: Bash
    Preconditions: models.py 已创建
    Steps:
      1. poetry run pytest tests/test_scheduler/test_models.py -v
      2. poetry run python -c "from llm_chat.scheduler.models import Task, TaskType; t = Task(id='1', name='test', task_type=TaskType.LLM_CHAT, trigger_config={}, params={}, enabled=True, created_at=datetime.now(), updated_at=datetime.now()); print(t.json())"
    Expected Result: 测试通过，JSON 序列化成功
    Failure Indicators: pytest 失败或序列化错误
    Evidence: .sisyphus/evidence/task-02-models.txt
  ```

  **Commit**: YES
  - Message: `feat(scheduler): define task and execution models`
  - Files: `src/llm_chat/scheduler/models.py, tests/test_scheduler/test_models.py`
  - Pre-commit: `poetry run pytest tests/test_scheduler/test_models.py`

- [x] 3. 配置扩展

  **What to do**:
  - 在 `src/llm_chat/config.py` 添加 `SchedulerConfig` 类：
    - enabled: bool = True
    - max_workers: int = 4
    - default_timezone: str = "local"
  - 在 `Config` 类添加 `scheduler: SchedulerConfig` 字段
  - 更新 `config.yaml` 示例配置
  - 编写单元测试：`tests/test_config.py` 添加 scheduler 相关测试
  - **注意**：复用现有 `.vb/vermilion_bird.db` 数据库，无需单独配置 db_path

  **Must NOT do**:
  - 不修改现有配置字段
  - 不引入新的配置文件格式
  - 不添加独立的 db_path 配置（复用现有数据库）

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 配置扩展，逻辑简单
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1-2, 4-6)
  - **Blocks**: Task 7, Task 15（需要配置）
  - **Blocked By**: None

  **References**:
  - `src/llm_chat/config.py` - 现有配置结构
  - `config.yaml` - 配置示例

  **Acceptance Criteria**:
  - [ ] SchedulerConfig 类定义完成（不包含 db_path）
  - [ ] Config 类包含 scheduler 字段
  - [ ] config.yaml 包含 scheduler 配置示例
  - [ ] 测试通过：`poetry run pytest tests/test_config.py -k scheduler -v`

  **QA Scenarios**:

  ```
  Scenario: 配置加载验证
    Tool: Bash
    Preconditions: config.py 已更新
    Steps:
      1. poetry run pytest tests/test_config.py -k scheduler -v
      2. poetry run python -c "from llm_chat.config import Config; c = Config.from_yaml('config.yaml'); print(c.scheduler.enabled)"
    Expected Result: 测试通过，配置成功加载
    Failure Indicators: 测试失败或配置加载错误
    Evidence: .sisyphus/evidence/task-03-config.txt
  ```

  **Commit**: YES
  - Message: `feat(config): add scheduler configuration`
  - Files: `src/llm_chat/config.py, config.yaml, tests/test_config.py`
  - Pre-commit: `poetry run pytest tests/test_config.py -k scheduler`

---

- [x] 4. 扩展现有存储层（复用数据库）

  **What to do**:
  - 扩展 `src/llm_chat/storage.py`（复用现有 `.vb/vermilion_bird.db`）
  - 在 `_init_db()` 方法中添加 `tasks` 和 `task_executions` 表：
    ```sql
    CREATE TABLE IF NOT EXISTS tasks (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        task_type TEXT NOT NULL,
        trigger_config TEXT NOT NULL,  -- JSON
        params TEXT NOT NULL,           -- JSON
        enabled INTEGER DEFAULT 1,
        max_retries INTEGER DEFAULT 3,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    
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
    
    CREATE INDEX IF NOT EXISTS idx_task_executions_task_id ON task_executions(task_id);
    CREATE INDEX IF NOT EXISTS idx_task_executions_started_at ON task_executions(started_at);
    ```
  - 在 `Storage` 类中添加方法：
    - `save_task(task: Task) -> str` - 保存任务定义
    - `load_task(task_id: str) -> Task | None` - 加载任务
    - `load_all_tasks() -> list[Task]` - 加载所有任务
    - `delete_task(task_id: str)` - 删除任务
    - `save_execution(execution: TaskExecution) -> str` - 保存执行历史
    - `load_executions(task_id: str, limit: int = 100) -> list[TaskExecution]` - 查询执行历史
  - 编写单元测试：`tests/test_storage.py` 添加 scheduler 相关测试

  **Must NOT do**:
  - 不使用 ORM 框架（SQLAlchemy ORM）
  - 不创建独立的 scheduler.db 文件（复用现有数据库）
  - 不修改现有表结构

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 数据库操作，扩展现有代码
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1-3, 5-6)
  - **Blocks**: Task 7（需要存储层）
  - **Blocked By**: Task 2（需要数据模型）

  **References**:
  - `src/llm_chat/storage.py:10-69` - 现有 Storage 类结构和 `_init_db()` 方法
  - `src/llm_chat/storage.py:70-81` - 连接管理模式（`_get_connection()`）
  - `src/llm_chat/scheduler/models.py` - Task 和 TaskExecution 定义

  **Acceptance Criteria**:
  - [ ] Storage 类包含任务相关方法
  - [ ] tasks 和 task_executions 表创建成功
  - [ ] 测试通过：`poetry run pytest tests/test_storage.py -k task -v`
  - [ ] 任务和执行历史可正确保存和查询
  - [ ] 数据库文件仍是 `.vb/vermilion_bird.db`（无新建文件）

  **QA Scenarios**:

  ```
  Scenario: 存储操作验证
    Tool: Bash
    Preconditions: storage.py 已扩展
    Steps:
      1. poetry run pytest tests/test_storage.py -k task -v
      2. poetry run python -c "from llm_chat.storage import Storage; from llm_chat.scheduler.models import Task, TaskType; from datetime import datetime; s = Storage(':memory:'); t = Task(id='1', name='test', task_type=TaskType.LLM_CHAT, trigger_config={}, params={}, enabled=True, created_at=datetime.now(), updated_at=datetime.now()); s.save_task(t); print(s.load_task('1').name)"
    Expected Result: 测试通过，输出 "test"
    Failure Indicators: 测试失败或数据库操作错误
    Evidence: .sisyphus/evidence/task-04-storage.txt
  ```

  ```
  Scenario: 数据库路径验证
    Tool: Bash
    Preconditions: 应用已运行
    Steps:
      1. poetry run python -c "from llm_chat.storage import Storage; s = Storage(); print(s._db_path)"
      2. 检查是否存在 ~/.vermilion-bird/scheduler.db（不应存在）
      3. 检查 .vb/vermilion_bird.db 是否包含 tasks 表
    Expected Result: 输出 ".vb/vermilion_bird.db"，无独立 scheduler.db
    Failure Indicators: 存在独立的 scheduler.db 文件
    Evidence: .sisyphus/evidence/task-04-db-path.txt
  ```

  **Commit**: YES
  - Message: `feat(storage): add task persistence tables to existing database`
  - Files: `src/llm_chat/storage.py, tests/test_storage.py`
  - Pre-commit: `poetry run pytest tests/test_storage.py -k task`

- [x] 5. 测试基础设施

  **What to do**:
  - 创建 `tests/test_scheduler/__init__.py`
  - 创建 `tests/test_scheduler/conftest.py`：
    - 定义 `temp_db` fixture（临时内存数据库）
    - 定义 `sample_task` fixture（示例任务）
    - 定义 `sample_execution` fixture（示例执行历史）
  - 确保测试可以独立运行

  **Must NOT do**:
  - 不修改现有 conftest.py
  - 不引入新的测试框架

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 测试辅助代码
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1-4, 6)
  - **Blocks**: 所有后续测试任务
  - **Blocked By**: Task 2（需要数据模型）

  **References**:
  - `tests/conftest.py` - 参考 fixture 定义

  **Acceptance Criteria**:
  - [ ] tests/test_scheduler/ 目录存在
  - [ ] conftest.py 包含所有 fixture
  - [ ] `poetry run pytest tests/test_scheduler/ --collect-only` 成功

  **QA Scenarios**:

  ```
  Scenario: 测试基础设施验证
    Tool: Bash
    Preconditions: conftest.py 已创建
    Steps:
      1. poetry run pytest tests/test_scheduler/ --collect-only
      2. poetry run python -c "from tests.test_scheduler.conftest import *; print('OK')"
    Expected Result: 测试收集成功，无错误
    Failure Indicators: 收集失败或导入错误
    Evidence: .sisyphus/evidence/task-05-test-infra.txt
  ```

  **Commit**: YES
  - Message: `test(scheduler): add test fixtures and infrastructure`
  - Files: `tests/test_scheduler/__init__.py, tests/test_scheduler/conftest.py`
  - Pre-commit: `poetry run pytest tests/test_scheduler/ --collect-only`

- [x] 6. 模块入口

  **What to do**:
  - 创建 `src/llm_chat/scheduler/__init__.py`
  - 导出主要类和函数：
    - `from .models import Task, TaskExecution, TaskType, TaskStatus`
    - `from .scheduler import SchedulerService`（预留，Task 7 实现）
    - `from .task_executor import TaskExecutor`（预留，Task 8 实现）
  - 添加 `__all__` 列表
  - **注意**：TaskStorage 在 `llm_chat.storage` 模块中，不在 scheduler 模块

  **Must NOT do**:
  - 不导入未实现的类（使用注释标注）
  - 不从 scheduler 模块导入 Storage（Storage 在 llm_chat.storage）

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 模块初始化文件
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1-5)
  - **Blocks**: None
  - **Blocked By**: Task 2（需要已实现的类）

  **References**:
  - `src/llm_chat/mcp/__init__.py` - 参考导出模式

  **Acceptance Criteria**:
  - [ ] __init__.py 包含所有导出
  - [ ] `poetry run python -c "from llm_chat.scheduler import Task; from llm_chat.storage import Storage; print('OK')"` 成功
  - [ ] __all__ 列表完整

  **QA Scenarios**:

  ```
  Scenario: 模块导入验证
    Tool: Bash
    Preconditions: __init__.py 已创建
    Steps:
      1. poetry run python -c "from llm_chat.scheduler import Task, TaskType; from llm_chat.storage import Storage; print('OK')"
    Expected Result: 输出 "OK"，无导入错误
    Failure Indicators: ImportError
    Evidence: .sisyphus/evidence/task-06-module-init.txt
  ```

  **Commit**: YES
  - Message: `feat(scheduler): add module exports`
  - Files: `src/llm_chat/scheduler/__init__.py`
  - Pre-commit: `poetry run python -c "from llm_chat.scheduler import Task"`

---

### Wave 2: 核心调度器 + 执行器（5 个任务，依赖 Wave 1）

- [x] 7. 调度器核心

  **What to do**:
  - 创建 `src/llm_chat/scheduler/scheduler.py`
  - 实现 `SchedulerService` 类：
    - `__init__(config: SchedulerConfig, task_storage: Storage, app: App)`
    - `start()` - 启动调度器
    - `shutdown()` - 关闭调度器
    - `add_task(task: Task) -> str` - 添加任务（返回 task_id）
    - `remove_task(task_id: str) -> bool` - 删除任务
    - `pause_task(task_id: str) -> bool` - 暂停任务
    - `resume_task(task_id: str) -> bool` - 恢复任务
    - `trigger_task(task_id: str) -> bool` - 手动触发任务
    - `get_task(task_id: str) -> Task | None` - 获取任务
    - `get_all_tasks() -> list[Task]` - 获取所有任务
  - 使用 APScheduler BackgroundScheduler + ThreadPoolExecutor
  - 配置 SQLAlchemyJobStore（使用 `.vb/vermilion_bird.db`）
  - 添加任务监听器（执行成功/失败事件）
  - **TDD**: 先写测试（mock APScheduler），再实现

  **Must NOT do**:
  - 不使用 QThreadPool
  - 不在工作线程直接操作 GUI
  - 不阻塞主线程
  - 不创建独立的数据库文件

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: 核心调度器，需要深入理解 APScheduler 和线程模型
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 8-11)
  - **Blocks**: Task 12-15（GUI 和集成需要调度器）
  - **Blocked By**: Task 1-6（依赖和模型）

  **References**:
  - APScheduler 文档: https://apscheduler.readthedocs.io/en/master/
  - `src/llm_chat/app.py` - App 类结构
  - `src/llm_chat/storage.py` - Storage 类（包含任务持久化方法）
  - `src/llm_chat/mcp/manager.py` - 参考 asyncio 事件循环模式

  **Acceptance Criteria**:
  - [ ] SchedulerService 类实现完成
  - [ ] 所有公共方法测试通过
  - [ ] 任务持久化到 `.vb/vermilion_bird.db`
  - [ ] 任务执行不阻塞主线程
  - [ ] 测试覆盖率 ≥ 90%

  **QA Scenarios**:

  ```
  Scenario: 添加并触发任务
    Tool: Bash (pytest)
    Preconditions: 调度器已初始化
    Steps:
      1. poetry run pytest tests/test_scheduler/test_scheduler.py::test_add_task -v
      2. poetry run pytest tests/test_scheduler/test_scheduler.py::test_trigger_task -v
    Expected Result: 测试通过，任务成功添加和触发
    Failure Indicators: 测试失败或超时
    Evidence: .sisyphus/evidence/task-07-scheduler.txt
  ```

  ```
  Scenario: 任务持久化验证
    Tool: Bash (pytest)
    Preconditions: 任务已添加
    Steps:
      1. poetry run pytest tests/test_scheduler/test_scheduler.py::test_task_persistence -v
      2. 检查 .vb/vermilion_bird.db 中存在任务记录
    Expected Result: 任务持久化成功
    Failure Indicators: 数据库文件不存在或记录缺失
    Evidence: .sisyphus/evidence/task-07-persistence.txt
  ```

  **Commit**: YES
  - Message: `feat(scheduler): implement core scheduler service`
  - Files: `src/llm_chat/scheduler/scheduler.py, tests/test_scheduler/test_scheduler.py`
  - Pre-commit: `poetry run pytest tests/test_scheduler/`

- [x] 8. 任务执行器

  **What to do**:
  - 创建 `src/llm_chat/scheduler/task_executor.py`
  - 实现 `TaskExecutor` 类（纯 Python，无 Qt 依赖）：
    - `__init__(app: App, task_storage: Storage)` - 需要访问 App 实例和 Storage（从 llm_chat.storage 导入）
    - `execute(task: Task) -> TaskExecution` - 执行任务
    - `_execute_llm_chat(task: Task) -> str` - 执行 LLM 对话任务
    - `_execute_skill(task: Task) -> str` - 执行技能任务
    - `_execute_maintenance(task: Task) -> str` - 执行系统维护任务
  - 实现重试逻辑（最多 3 次，指数退避）
  - 记录执行历史到 Storage（调用 storage.save_execution()）
  - **TDD**: 先写测试（mock App 和 Storage），再实现

  **Must NOT do**:
  - 不在工作线程直接操作 GUI
  - 不引入 Qt 依赖

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: 需要理解任务执行逻辑和错误处理
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 7, 9-11)
  - **Blocks**: Task 9-11, 15（任务执行器被特定任务类型使用）
  - **Blocked By**: Task 2, 4, 7（依赖模型、存储和调度器）

  **References**:
  - `src/llm_chat/client.py` - LLMClient.chat() 方法
  - `src/llm_chat/skills/manager.py` - SkillManager 执行技能
  - `src/llm_chat/memory/manager.py` - MemoryManager 清理逻辑
  - `src/llm_chat/storage.py` - Storage 类（包含 save_execution 方法）

  **Acceptance Criteria**:
  - [ ] TaskExecutor 类实现完成
  - [ ] 三种任务类型都能执行
  - [ ] 重试逻辑正常工作
  - [ ] 执行历史正确记录到 `.vb/vermilion_bird.db`
  - [ ] 测试覆盖率 ≥ 90%

  **QA Scenarios**:

  ```
  Scenario: LLM 对话任务执行
    Tool: Bash (pytest)
    Preconditions: 调度器和执行器已初始化
    Steps:
      1. poetry run pytest tests/test_scheduler/test_executor.py::test_execute_llm_chat -v
    Expected Result: 测试通过，LLM 调用成功
    Failure Indicators: 测试失败或 mock 未调用
    Evidence: .sisyphus/evidence/task-08-llm.txt
  ```

  ```
  Scenario: 任务重试验证
    Tool: Bash (pytest)
    Preconditions: 任务执行会失败
    Steps:
      1. poetry run pytest tests/test_scheduler/test_executor.py::test_retry_logic -v
      2. 验证重试次数和退避时间
    Expected Result: 任务重试 3 次后失败
    Failure Indicators: 重试次数不正确或无退避
    Evidence: .sisyphus/evidence/task-08-retry.txt
  ```

  **Commit**: YES
  - Message: `feat(scheduler): implement task executor with retry logic`
  - Files: `src/llm_chat/scheduler/task_executor.py, tests/test_scheduler/test_executor.py`
  - Pre-commit: `poetry run pytest tests/test_scheduler/test_executor.py`

- [x] 9. LLM 对话任务

  **What to do**:
  - 在 `task_executor.py` 中完善 `_execute_llm_chat` 方法
  - 支持配置 prompt、model、temperature 等参数
  - 调用 `app.client.chat()` 执行对话
  - 返回对话结果（最后一条消息内容）
  - 错误处理：API 错误、超时等
  - **TDD**: 先写测试，再实现

  **Must NOT do**:
  - 不在任务中保存完整对话历史（仅返回结果）
  - 不修改现有 LLMClient 接口

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: 需要理解 LLM 调用和错误处理
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 7-8, 10-11)
  - **Blocks**: Task 15（集成需要）
  - **Blocked By**: Task 8（依赖执行器框架）

  **References**:
  - `src/llm_chat/client.py:LLMClient.chat()` - 对话 API
  - `src/llm_chat/conversation.py` - 会话管理

  **Acceptance Criteria**:
  - [ ] LLM 对话任务可执行
  - [ ] 支持参数配置
  - [ ] 错误正确处理
  - [ ] 测试通过

  **QA Scenarios**:

  ```
  Scenario: LLM 对话任务执行（带参数）
    Tool: Bash (pytest)
    Preconditions: 执行器已初始化， mock LLMClient
    Steps:
      1. poetry run pytest tests/test_scheduler/test_executor.py::test_llm_chat_with_params -v
      2. 验证参数正确传递给 client.chat()
    Expected Result: 测试通过，参数正确传递
    Failure Indicators: 参数未传递或格式错误
    Evidence: .sisyphus/evidence/task-09-llm-params.txt
  ```

  **Commit**: YES
  - Message: `feat(scheduler): implement LLM chat task execution`
  - Files: `src/llm_chat/scheduler/task_executor.py, tests/test_scheduler/test_executor.py`
  - Pre-commit: `poetry run pytest tests/test_scheduler/test_executor.py::test_llm`

- [x] 10. 技能执行任务

  **What to do**:
  - 在 `task_executor.py` 中完善 `_execute_skill` 方法
  - 支持配置技能名称、工具名称、参数
  - 调用 `app.get_skill_manager().execute_tool()` 或 MCP 工具
  - 返回执行结果（JSON 格式）
  - 错误处理：技能不存在、工具调用失败
  - **TDD**: 先写测试，再实现

  **Must NOT do**:
  - 不引入新的技能执行机制
  - 不修改现有 SkillManager 接口

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: 需要理解技能和 MCP 工具调用
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 7-9, 11)
  - **Blocks**: Task 15（集成需要）
  - **Blocked By**: Task 8（依赖执行器框架）

  **References**:
  - `src/llm_chat/skills/manager.py:SkillManager` - 技能管理器
  - `src/llm_chat/mcp/manager.py:MCPManager.call_tool()` - MCP 工具调用

  **Acceptance Criteria**:
  - [ ] 技能任务可执行
  - [ ] 支持 MCP 工具调用
  - [ ] 错误正确处理
  - [ ] 测试通过

  **QA Scenarios**:

  ```
  Scenario: 技能执行任务
    Tool: Bash (pytest)
    Preconditions: 执行器已初始化， mock SkillManager
    Steps:
      1. poetry run pytest tests/test_scheduler/test_executor.py::test_skill_execution -v
      2. 验证技能正确调用
    Expected Result: 测试通过，技能成功执行
    Failure Indicators: 技能未调用或参数错误
    Evidence: .sisyphus/evidence/task-10-skill.txt
  ```

  **Commit**: YES
  - Message: `feat(scheduler): implement skill execution task`
  - Files: `src/llm_chat/scheduler/task_executor.py, tests/test_scheduler/test_executor.py`
  - Pre-commit: `poetry run pytest tests/test_scheduler/test_executor.py::test_skill`

- [x] 11. 系统维护任务

  **What to do**:
  - 在 `task_executor.py` 中完善 `_execute_maintenance` 方法
  - 支持内置维护任务：
    - `cleanup_memory`: 清理过期记忆
    - `backup_data`: 备份数据库
    - `clear_old_conversations`: 清理旧会话
  - 调用相应的管理器方法
  - 返回执行结果（清理数量、备份路径等）
  - 错误处理：清理失败、权限错误
  - **TDD**: 先写测试，再实现

  **Must NOT do**:
  - 不引入新的维护机制
  - 不修改现有 Manager 接口

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: 需要理解记忆和存储清理逻辑
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 7-10)
  - **Blocks**: Task 15（集成需要）
  - **Blocked By**: Task 8（依赖执行器框架）

  **References**:
  - `src/llm_chat/memory/manager.py:MemoryManager` - 记忆管理
  - `src/llm_chat/storage.py:Storage` - 数据存储

  **Acceptance Criteria**:
  - [ ] 三种维护任务可执行
  - [ ] 错误正确处理
  - [ ] 测试通过

  **QA Scenarios**:

  ```
  Scenario: 记忆清理任务
    Tool: Bash (pytest)
    Preconditions: 执行器已初始化， mock MemoryManager
    Steps:
      1. poetry run pytest tests/test_scheduler/test_executor.py::test_maintenance_cleanup -v
      2. 验证清理方法正确调用
    Expected Result: 测试通过，清理成功
    Failure Indicators: 清理方法未调用
    Evidence: .sisyphus/evidence/task-11-maintenance.txt
  ```

  **Commit**: YES
  - Message: `feat(scheduler): implement system maintenance tasks`
  - Files: `src/llm_chat/scheduler/task_executor.py, tests/test_scheduler/test_executor.py`
  - Pre-commit: `poetry run pytest tests/test_scheduler/test_executor.py::test_maintenance`

---

### Wave 3: GUI + 集成（5 个任务，依赖 Wave 1-2）

- [x] 12. GUI 任务列表

  **What to do**:
  - 创建 `src/llm_chat/frontends/scheduler_dialog.py`
  - 实现 `SchedulerDialog` 类（继承 QDialog）：
    - 任务列表（QTableWidget）显示所有任务
    - 列：名称、类型、触发器、状态、下次执行时间、操作按钮
    - 操作按钮：编辑、删除、暂停/恢复、手动触发
    - 工具栏：添加任务、刷新列表
  - 连接信号槽到 SchedulerService
  - **线程安全**：使用 `QMetaObject.invokeMethod` 更新 UI

  **Must NOT do**:
  - 不在工作线程直接操作 UI
  - 不阻塞主线程

  **Recommended Agent Profile**:
  - **Category**: `visual-engineering`
    - Reason: PyQt6 GUI 开发
  - **Skills**: [`playwright`]
    - `playwright`: UI 自动化测试

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Tasks 13-16)
  - **Blocks**: None
  - **Blocked By**: Task 7, 8（需要调度器和执行器）

  **References**:
  - `src/llm_chat/frontends/mcp_dialog.py` - 参考 GUI 模式
  - `src/llm_chat/frontends/gui.py` - PyQt6 使用方式

  **Acceptance Criteria**:
  - [ ] GUI 显示任务列表
  - [ ] 操作按钮功能正常
  - [ ] 线程安全（无 UI 冻结）
  - [ ] 测试通过

  **QA Scenarios**:

  ```
  Scenario: 任务列表显示
    Tool: Playwright
    Preconditions: 应用已启动，至少有一个任务
    Steps:
      1. 启动 GUI 应用
      2. 打开定时任务对话框
      3. 验证任务列表显示正确（名称、类型、状态）
      4. 截图保存
    Expected Result: 任务列表正确显示，UI 响应流畅
    Failure Indicators: UI 冻结或列表为空
    Evidence: .sisyphus/evidence/task-12-gui-list.png
  ```

  **Commit**: YES
  - Message: `feat(frontend): add scheduler dialog task list`
  - Files: `src/llm_chat/frontends/scheduler_dialog.py, tests/test_frontend/test_scheduler_dialog.py`
  - Pre-commit: `poetry run pytest tests/test_frontend/test_scheduler_dialog.py`

- [x] 13. GUI 任务编辑器

  **What to do**:
  - 在 `scheduler_dialog.py` 添加 `TaskEditDialog` 类
  - 支持三种任务类型的配置：
    - **LLM 对话**: prompt、model、temperature
    - **技能执行**: skill_name、params（JSON 编辑器）
    - **系统维护**: maintenance_type（下拉选择）
  - 触发器配置：
    - Cron 表达式（带验证和预览）
    - 一次性任务（日期时间选择器）
  - 参数编辑器（JSON 格式）
  - 保存/取消按钮
  - **TDD**: 先写测试，再实现

  **Must NOT do**:
  - 不允许无效的 Cron 表达式
  - 不允许无效的 JSON 参数

  **Recommended Agent Profile**:
  - **Category**: `visual-engineering`
    - Reason: 复杂表单 UI 开发
  - **Skills**: [`playwright`]
    - `playwright`: UI 测试

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Tasks 12, 14-16)
  - **Blocks**: None
  - **Blocked By**: Task 7, 8, 12

  **References**:
  - `src/llm_chat/frontends/mcp_dialog.py` - 表单设计参考
  - `src/llm_chat/scheduler/models.py` - 任务数据模型

  **Acceptance Criteria**:
  - [ ] 编辑器支持三种任务类型
  - [ ] Cron 表达式验证
  - [ ] JSON 参数验证
  - [ ] 测试通过

  **QA Scenarios**:

  ```
  Scenario: 创建 LLM 对话任务
    Tool: Playwright
    Preconditions: GUI 已启动
    Steps:
      1. 点击"添加任务"按钮
      2. 选择"LLM 对话"类型
      3. 输入任务名称: "每日问候"
      4. 输入 Cron: "0 8 * * *"
      5. 输入 prompt: "早上好"
      6. 点击保存
      7. 验证任务出现在列表中
    Expected Result: 任务成功创建并显示在列表中
    Failure Indicators: 保存失败或验证错误
    Evidence: .sisyphus/evidence/task-13-edit-llm.png
  ```

  **Commit**: YES
  - Message: `feat(frontend): add task editor dialog`
  - Files: `src/llm_chat/frontends/scheduler_dialog.py, tests/test_frontend/test_scheduler_dialog.py`
  - Pre-commit: `poetry run pytest tests/test_frontend/test_scheduler_dialog.py::test_edit_dialog`

- [x] 14. GUI 执行历史

  **What to do**:
  - 在 `scheduler_dialog.py` 添加 `ExecutionHistoryDialog` 类
  - 显示任务执行历史：
    - 列：执行时间、状态、耗时、结果/错误
  - 支持按任务筛选
  - 支持刷新和清空历史
  - 分页显示（每页 20 条）
  - **TDD**: 先写测试，再实现
  - **注意**：使用 `Storage.load_executions()` 方法（从 llm_chat.storage 导入）

  **Must NOT do**:
  - 不加载所有历史到内存（分页查询）
  - 不阻塞 UI 线程

  **Recommended Agent Profile**:
  - **Category**: `visual-engineering`
    - Reason: 列表 UI 开发
  - **Skills**: [`playwright`]
    - `playwright`: UI 测试

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Tasks 12-13, 15-16)
  - **Blocks**: None
  - **Blocked By**: Task 4, 7（依赖存储层和调度器）

  **References**:
  - `src/llm_chat/storage.py:Storage.load_executions()` - 历史查询接口
  - `src/llm_chat/frontends/gui.py` - 列表显示参考

  **Acceptance Criteria**:
  - [ ] 历史列表正确显示
  - [ ] 筛选功能正常
  - [ ] 分页功能正常
  - [ ] 测试通过

  **QA Scenarios**:

  ```
  Scenario: 查看执行历史
    Tool: Playwright
    Preconditions: 有任务执行历史
    Steps:
      1. 右键点击任务
      2. 选择"查看历史"
      3. 验证历史列表显示
      4. 验证分页功能
    Expected Result: 历史正确显示，分页正常
    Failure Indicators: 列表为空或分页失败
    Evidence: .sisyphus/evidence/task-14-history.png
  ```

  **Commit**: YES
  - Message: `feat(frontend): add execution history dialog`
  - Files: `src/llm_chat/frontends/scheduler_dialog.py, tests/test_frontend/test_scheduler_dialog.py`
  - Pre-commit: `poetry run pytest tests/test_frontend/test_scheduler_dialog.py::test_history_dialog`

- [x] 15. App 集成

  **What to do**:
  - 修改 `src/llm_chat/app.py`:
    - 添加 `scheduler: SchedulerService` 属性
    - 在 `__init__` 中初始化 SchedulerService（如果 config.scheduler.enabled）
    - 在 `run` 方法中启动调度器
    - 在 `cleanup` 或 `closeEvent` 中关闭调度器
    - 提供 `get_scheduler()` 方法
  - 修改 `src/llm_chat/config.py`:
    - 添加 `SchedulerConfig` 类（enabled, max_workers, default_timezone，**无 db_path**）
    - 在 `Config` 类中添加 `scheduler: SchedulerConfig` 属性
  - 更新 `config.yaml` 示例：
    ```yaml
    scheduler:
      enabled: true
      max_workers: 4
      default_timezone: "local"
    ```
  - **TDD**: 先写测试，再实现
  - **注意**：任务数据复用现有 `.vb/vermilion_bird.db` 数据库

  **Must NOT do**:
  - 不在 CLI 模式加载 Qt 相关代码
  - 不阻塞应用启动
  - 不创建独立的数据库文件

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: 核心集成，需要理解 App 生命周期
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Tasks 12-14, 16)
  - **Blocks**: Task 16, F1-F4
  - **Blocked By**: Task 3, 4, 7, 8

  **References**:
  - `src/llm_chat/app.py` - App 类
  - `src/llm_chat/config.py` - 配置加载
  - `src/llm_chat/storage.py` - Storage 类（复用现有数据库）
  - `config.yaml` - 配置示例

  **Acceptance Criteria**:
  - [ ] App 正确初始化调度器
  - [ ] 配置加载正常
  - [ ] 调度器在应用启动时自动启动
  - [ ] 应用关闭时调度器正确关闭
  - [ ] 任务数据存储在 `.vb/vermilion_bird.db`（无独立 scheduler.db）
  - [ ] 测试通过

  **QA Scenarios**:

  ```
  Scenario: 应用启动调度器
    Tool: Bash
    Preconditions: config.yaml 中 scheduler.enabled = true
    Steps:
      1. poetry run vermilion-bird --config config.yaml
      2. 检查日志中是否有 "Scheduler started" 信息
      3. Ctrl+C 退出
    Expected Result: 调度器成功启动和关闭
    Failure Indicators: 启动失败或未启动调度器
    Evidence: .sisyphus/evidence/task-15-app-integration.txt
  ```

  ```
  Scenario: 配置禁用调度器
    Tool: Bash
    Preconditions: config.yaml 中 scheduler.enabled = false
    Steps:
      1. poetry run vermilion-bird --config config.yaml
      2. 检查日志中不应有 "Scheduler started"
    Expected Result: 调度器未启动
    Failure Indicators: 调度器启动（违反配置）
    Evidence: .sisyphus/evidence/task-15-disabled.txt
  ```

  ```
  Scenario: 数据库复用验证
    Tool: Bash
    Preconditions: 应用已运行并创建任务
    Steps:
      1. 检查 .vb/vermilion_bird.db 是否包含 tasks 表
      2. 检查 ~/.vermilion-bird/scheduler.db 是否存在（应不存在）
    Expected Result: 任务数据在 .vb/vermilion_bird.db，无独立 scheduler.db
    Failure Indicators: 存在独立的 scheduler.db 文件
    Evidence: .sisyphus/evidence/task-15-db-reuse.txt
  ```

  **Commit**: YES
  - Message: `feat(app): integrate scheduler into app lifecycle`
  - Files: `src/llm_chat/app.py, src/llm_chat/config.py, config.yaml, tests/test_app.py`
  - Pre-commit: `poetry run pytest tests/test_app.py::test_scheduler_integration`

- [x] 16. CLI 集成测试

  **What to do**:
  - 创建 `tests/integration/test_scheduler_cli.py`
  - 测试场景：
    - CLI 模式下添加任务（通过配置文件）
    - CLI 模式下任务执行
    - CLI 模式下查看任务状态（通过日志）
    - 应用重启后任务恢复
  - 使用真实的 SQLite 数据库（临时文件）
  - **集成测试**（不使用 mock）

  **Must NOT do**:
  - 不 mock APScheduler（真实测试）
  - 不依赖 GUI

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: 集成测试需要真实环境
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Tasks 12-15)
  - **Blocks**: F1-F4
  - **Blocked By**: Task 15

  **References**:
  - `src/llm_chat/cli.py` - CLI 入口
  - `tests/integration/` - 现有集成测试

  **Acceptance Criteria**:
  - [ ] CLI 模式测试通过
  - [ ] 任务恢复测试通过
  - [ ] 无 GUI 依赖

  **QA Scenarios**:

  ```
  Scenario: CLI 模式任务执行
    Tool: Bash
    Preconditions: scheduler 已集成到 App
    Steps:
      1. 创建临时配置文件，启用 scheduler
      2. 添加一个一次性任务（5秒后执行）
      3. 运行 CLI 应用
      4. 等待 6 秒
      5. 检查日志中任务执行记录
    Expected Result: 任务成功执行，日志显示执行结果
    Failure Indicators: 任务未执行或日志缺失
    Evidence: .sisyphus/evidence/task-16-cli-execution.txt
  ```

  ```
  Scenario: 应用重启后任务恢复
    Tool: Bash
    Preconditions: 有持久化的任务
    Steps:
      1. 添加一个 Cron 任务
      2. 关闭应用
      3. 重新启动应用
      4. 检查任务是否恢复
    Expected Result: 任务成功恢复
    Failure Indicators: 任务丢失
    Evidence: .sisyphus/evidence/task-16-recovery.txt
  ```

  **Commit**: YES
  - Message: `test(integration): add scheduler CLI integration tests`
  - Files: `tests/integration/test_scheduler_cli.py`
  - Pre-commit: `poetry run pytest tests/integration/test_scheduler_cli.py`

---

## Final Verification Wave (MANDATORY — after ALL implementation tasks)

> 4 review agents run in PARALLEL. ALL must APPROVE. Present consolidated results to user and get explicit "okay" before completing.
>
> **Do NOT auto-proceed after verification. Wait for user's explicit approval before marking work complete.**
> **Never mark F1-F4 as checked before getting user's okay.** Rejection or user feedback -> fix -> re-run -> present again -> wait for okay.

- [ ] F1. **Plan Compliance Audit** — `oracle`
  Read the plan end-to-end. For each "Must Have": verify implementation exists (read file, curl endpoint, run command). For each "Must NOT Have": search codebase for forbidden patterns — reject with file:line if found. Check evidence files exist in .sisyphus/evidence/. Compare deliverables against plan.
  Output: `Must Have [N/N] | Must NOT Have [N/N] | Tasks [N/N] | VERDICT: APPROVE/REJECT`

  **Verification Checklist**:
  - [ ] Three task types implemented (LLM chat, skill execution, maintenance)
  - [ ] Cron + one-time trigger support
  - [ ] Task persistence working (SQLite)
  - [ ] GUI management interface exists
  - [ ] Execution history saved
  - [ ] Retry logic implemented
  - [ ] Manual trigger/pause/resume working
  - [ ] CLI mode supported (no Qt dependency in scheduler core)
  - [ ] No QThreadPool usage in scheduler
  - [ ] All evidence files exist

  **QA Scenarios**:

  ```
  Scenario: Plan compliance check
    Tool: Bash
    Preconditions: All tasks completed
    Steps:
      1. Check all Must Have items exist
      2. Grep for forbidden patterns (QThreadPool, QThread in scheduler/)
      3. Verify all evidence files exist
    Expected Result: All Must Have present, no Must NOT Have found
    Failure Indicators: Missing features or forbidden patterns
    Evidence: .sisyphus/evidence/final-f1-compliance.txt
  ```

- [ ] F2. **Code Quality Review** — `unspecified-high`
  Run `poetry run flake8 src/llm_chat/scheduler --max-line-length=100` + `poetry run pytest tests/test_scheduler/ -v --cov=src/llm_chat/scheduler --cov-report=term`. Review all changed files for: `as any`/`@ts-ignore`, empty catches, console.log in prod, commented-out code, unused imports. Check AI slop: excessive comments, over-abstraction, generic names (data/result/item/temp).
  Output: `Lint [PASS/FAIL] | Tests [N pass/N fail] | Files [N clean/N issues] | VERDICT`

  **Verification Checklist**:
  - [ ] All tests pass
  - [ ] No lint errors
  - [ ] No AI slop patterns
  - [ ] Code coverage ≥ 80%

  **QA Scenarios**:

  ```
  Scenario: Code quality check
    Tool: Bash
    Preconditions: All code written
    Steps:
      1. poetry run pytest tests/test_scheduler/ -v --cov=src/llm_chat/scheduler --cov-report=term
      2. poetry run flake8 src/llm_chat/scheduler --max-line-length=100
      3. Check coverage report
    Expected Result: Tests pass, lint clean, coverage ≥ 80%
    Failure Indicators: Test failures, lint errors, or low coverage
    Evidence: .sisyphus/evidence/final-f2-quality.txt
  ```

- [ ] F3. **Real Manual QA** — `unspecified-high` (+ `playwright` skill if UI)
  Start from clean state. Execute EVERY QA scenario from EVERY task — follow exact steps, capture evidence. Test cross-task integration (features working together, not isolation). Test edge cases: empty state, invalid input, rapid actions. Save to `.sisyphus/evidence/final-qa/`.
  Output: `Scenarios [N/N pass] | Integration [N/N] | Edge Cases [N tested] | VERDICT`

  **Verification Checklist**:
  - [ ] All task QA scenarios executed
  - [ ] GUI tasks work together (create -> edit -> trigger -> history)
  - [ ] CLI mode tested
  - [ ] Task persistence verified (restart test)
  - [ ] Error scenarios handled gracefully

  **QA Scenarios**:

  ```
  Scenario: End-to-end GUI workflow
    Tool: Playwright
    Preconditions: Clean database
    Steps:
      1. Start GUI application
      2. Create LLM chat task with Cron "*/1 * * * *"
      3. Wait for task to execute
      4. Check execution history
      5. Pause task
      6. Manually trigger task
      7. Delete task
    Expected Result: All operations succeed, no errors
    Failure Indicators: Any operation fails
    Evidence: .sisyphus/evidence/final-f3-e2e.png
  ```

  ```
  Scenario: CLI mode workflow
    Tool: Bash
    Preconditions: Clean database, config with scheduler enabled
    Steps:
      1. Add task via config file
      2. Run CLI application for 2 minutes
      3. Check task execution in logs
      4. Stop and restart
      5. Verify task recovery
    Expected Result: Tasks execute and recover correctly
    Failure Indicators: Execution or recovery fails
    Evidence: .sisyphus/evidence/final-f3-cli.txt
  ```

  ```
  Scenario: Error handling
    Tool: Bash
    Preconditions: Scheduler running
    Steps:
      1. Create task with invalid LLM API key
      2. Wait for task execution
      3. Check execution history for error
      4. Verify retry attempts
    Expected Result: Error logged, retry attempts made
    Failure Indicators: No error handling
    Evidence: .sisyphus/evidence/final-f3-error.txt
  ```

- [ ] F4. **Scope Fidelity Check** — `deep`
  For each task: read "What to do", read actual diff (git log/diff). Verify 1:1 — everything in spec was built (no missing), nothing beyond spec was built (no creep). Check "Must NOT do" compliance. Detect cross-task contamination: Task N touching Task M's files. Flag unaccounted changes.
  Output: `Tasks [N/N compliant] | Contamination [CLEAN/N issues] | Unaccounted [CLEAN/N files] | VERDICT`

  **Verification Checklist**:
  - [ ] All TODO items implemented
  - [ ] No scope creep (no extra features)
  - [ ] No Must NOT do violations
  - [ ] No cross-task contamination
  - [ ] No unaccounted file changes

  **QA Scenarios**:

  ```
  Scenario: Scope fidelity audit
    Tool: Bash
    Preconditions: All tasks completed
    Steps:
      1. git diff main...HEAD --stat
      2. For each task, verify implementation matches spec
      3. Check for unaccounted changes
      4. Verify no forbidden patterns (QThreadPool in scheduler/)
    Expected Result: All tasks match spec, no creep
    Failure Indicators: Missing features or extra features
    Evidence: .sisyphus/evidence/final-f4-scope.txt
  ```

---

- **Wave 1**: `feat(scheduler): add infrastructure and data models`
  - Files: `pyproject.toml, poetry.lock, poetry install -e .`
  - Message: `feat(scheduler): add APScheduler dependency`
  - Files: `pyproject.toml, poetry.lock, config.yaml`
  - Pre-commit: `poetry run pytest tests/test_scheduler/`- **Wave 1**: `feat(scheduler): add infrastructure and data models` — pyproject.toml, models.py, config.py, storage.py, tests
- **Wave 2**: `feat(scheduler): implement core scheduler and executors` — scheduler.py, task_executor.py, tests
- **Wave 3**: `feat(frontend): add scheduler GUI and app integration` — scheduler_dialog.py, app.py, tests
- **Final**: `test: complete scheduler verification` — all verification evidence

---

## Success Criteria

### Verification Commands
```bash
# Run all scheduler tests
poetry run pytest tests/test_scheduler/ -v --cov=src/llm_chat/scheduler

# Run storage tests (including task-related tests)
poetry run pytest tests/test_storage.py -k task -v

# Run integration tests
poetry run pytest tests/integration/test_scheduler_cli.py -v

# Lint check
poetry run flake8 src/llm_chat/scheduler --max-line-length=100

# Verify database structure (tasks and task_executions tables)
sqlite3 .vb/vermilion_bird.db ".schema tasks"
sqlite3 .vb/vermilion_bird.db ".schema task_executions"

# Manual GUI test
poetry run vermilion-bird --gui
# Open scheduler dialog, verify UI works

# Manual CLI test
poetry run vermilion-bird
# Check logs for scheduler startup

# Verify no independent scheduler.db exists
ls ~/.vermilion-bird/scheduler.db 2>/dev/null && echo "ERROR: scheduler.db exists" || echo "OK: no scheduler.db"
```

### Final Checklist
- [ ] All "Must Have" present (3 task types, Cron, persistence, GUI, history, retry, controls, CLI support)
- [ ] All "Must NOT Have" absent (QThreadPool, fixed interval, task dependencies, distributed, GUI blocking, Celery)
- [ ] All tests pass (unit + integration)
- [ ] Code coverage ≥ 80%
- [ ] GUI functional (create, edit, trigger, pause, delete)
- [ ] CLI mode functional (tasks execute without GUI)
- [ ] Task persistence working (restart recovery)
- [ ] Database reuse verified (tasks in `.vb/vermilion_bird.db`, no independent `scheduler.db`)
- [ ] Error handling robust (retry, logging)
- [ ] Documentation updated (README.md)
- [ ] All evidence files captured

