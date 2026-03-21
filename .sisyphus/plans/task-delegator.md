# Task Delegator Skill - 子Agent任务分配

## TL;DR

> **Quick Summary**: 创建 `task_delegator` skill，支持父agent创建子agent分配任务，子agent拥有独立的上下文和工具白名单，且不能再创建子agent以防止递归。
> 
> **Deliverables**:
> - `SpawnSubagentTool` - 创建子agent并分配任务
> - `Get_subagent_status` - 查询子agent状态
> - `cancel_subagent` - 取消子agent任务
> - `AgentContext` - agent上下文管理
> - TDD测试套件
>
> **Estimated Effort**: Medium
> **Parallel Execution**: YES - 4 waves
> **Critical Path**: AgentContext → SpawnSubagentTool → TDD tests

---

## Context

### Original Request
创建一个能创建子agent分配任务的skill，要求：
1. 父子agent上下文隔离
2. 防止过度递归（子agent不能再创建子agent）

### Interview Summary
**Key Discussions**:
- **使用场景**: 混合场景（并行执行、专业分工、沙箱隔离）
- **生命周期**: 同步等待 - 父agent等待子agent完成后返回结果
- **工具权限**: 白名单 + 递归限制 - 子agent只能使用指定工具，不能使用 `spawn_subagent`
- **上下文共享**: 完全隔离 - 子agent有独立的对话历史
- **提供工具**: spawn_subagent, get_subagent_status, cancel_subagent
- **测试策略**: TDD（先写测试，再实现）

### Research Findings
- **Skill架构**: BaseSkill/BaseTool基类，SkillManager加载，ToolRegistry注册
- **会话管理**: Conversation/ConversationManager，每个conversation_id独立
- **工具调用**: LLMClient.chat_with_tools() → ToolRegistry/MCPManager
- **权限系统**: 只有全局enable_tools开关，无细粒度权限

### Metis Review
**Identified Gaps** (addressed):
1. 子agent ID生成策略 - 使用UUID
2. 超时和错误处理 - 设置默认值和友好错误消息
3. 工具名称冲突 - spawn_subagent（下划线）
4. 并发控制 - 顺序执行，不需要并发
5. TDD流程 - 遵循现有模式
6. 子agent会话生命周期管理 - 在AgentContext中管理
7. 工具白名单验证 - 在AgentContext中管理

**Guardrails Applied**:
- 子agent不能调用 `spawn_subagent`（硬性限制）
- 超时默认60秒
- 错误消息必须包含agent_id以便调试
- 使用独立的conversation_id隔离上下文

---

## Work Objectives

### Core Objective
创建 `task_delegator` skill，使LLM能够通过工具调用创建子agent分配任务，实现上下文隔离和递归防护。

### Concrete Deliverables
- `src/llm_chat/skills/task_delegator/__init__.py`
- `src/llm_chat/skills/task_delegator/skill.py` - TaskDelegatorSkill
- `src/llm_chat/skills/task_delegator/tools.py` - 3个工具类
- `src/llm_chat/skills/task_delegator/context.py` - AgentContext
- `src/llm_chat/skills/task_delegator/registry.py` - 子agent注册表
- `tests/test_task_delegator.py` - TDD测试
- 更新 `src/llm_chat/skills/registry.py` 注册新skill

### Definition of Done
- [ ] `poetry run pytest tests/test_task_delegator.py` 全部通过
- [ ] 子agent可以成功执行任务并返回结果
- [ ] 子agent尝试调用 `spawn_subagent` 时被拒绝
- [ ] 超时的子agent任务被正确取消

### Must Have
- AgentContext 跟踪 agent_id, parent_id, depth, allowed_tools
- SpawnSubagentTool 检查 depth >= 1 时拒绝
- 子agent的工具列表中不包含 `spawn_subagent`
- 完整的错误处理和友好的错误消息

### Must NOT Have (Guardrails)
- 子agent不能创建子agent（硬性限制）
- 子agent不能访问父agent的对话历史（上下文隔离）
- 不能修改现有的LLMClient/Conversation核心逻辑
- 不引入复杂的权限系统（保持简单）

---

## Verification Strategy

### Test Decision
- **Infrastructure exists**: YES (pytest)
- **Automated tests**: TDD
- **Framework**: pytest

### QA Policy
每个task包含agent-executed QA scenarios：
- **Backend/Skill**: Bash (pytest) - 运行测试验证功能
- **Evidence**: `.sisyphus/evidence/task-{N}-{scenario-slug}.txt`

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (Start Immediately — 基础设施):
├── Task 1: 创建目录结构和 __init__.py [quick]
├── Task 2: AgentContext 上下文类 [quick]
├── Task 3: SubAgentRegistry 注册表 [quick]
└── Task 4: TDD 测试骨架 [quick]

Wave 2 (After Wave 1 — 核心工具):
├── Task 5: SpawnSubagentTool 实现 [deep]
├── Task 6: GetSubagentStatusTool 实现 [quick]
└── Task 7: CancelSubagentTool 实现 [quick]

Wave 3 (After Wave 2 — 集成):
├── Task 8: TaskDelegatorSkill 集成 [quick]
├── Task 9: 注册到 registry.py [quick]
└── Task 10: 运行测试验证 [unspecified-high]

Critical Path: Task 2 → Task 3 → Task 5 → Task 8 → Task 10
Parallel Speedup: ~50% faster than sequential
Max Concurrent: 4 (Wave 1)
```

### Dependency Matrix
- **1-4**: — — 5-7
- **5**: 2, 3 — 8, 10
- **6**: 2, 3 — 8, 10
- **7**: 2, 3 — 8, 10
- **8**: 5, 6, 7 — 10
- **9**: 8 — 10
- **10**: 8, 9 — —

### Agent Dispatch Summary
- **1**: **4** — T1-T4 → `quick`
- **2**: **3** — T5 → `deep`, T6-T7 → `quick`
- **3**: **2** — T8-T9 → `quick`, T10 → `unspecified-high`

---

## TODOs

- [ ] 1. 创建目录结构和 `__init__.py`

  **What to do**:
  - 创建 `src/llm_chat/skills/task_delegator/` 目录
  - 创建 `__init__.py` 导出模块

  **Must NOT do**:
  - 不要修改现有代码结构

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 简单的目录创建和文件写入
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 2, 3, 4)
  - **Blocks**: Tasks 5, 6, 7, 8
  - **Blocked By**: None

  **References**:
  - `src/llm_chat/skills/web_search/` - 现有skill目录结构参考
  - `src/llm_chat/skills/base.py` - BaseSkill接口

  **Acceptance Criteria**:
  - [ ] 目录 `src/llm_chat/skills/task_delegator/` 存在
  - [ ] `__init__.py` 正确导出 `AgentContext`, `SubAgentRegistry`, `SpawnSubagentTool` 等

  **QA Scenarios**:
  ```
  Scenario: 验证目录结构
    Tool: Bash
    Preconditions: 工作目录是项目根目录
    Steps:
      1. ls -la src/llm_chat/skills/task_delegator/
      2. cat src/llm_chat/skills/task_delegator/__init__.py
    Expected Result: 目录存在，__init__.py包含正确的导出
    Evidence: .sisyphus/evidence/task-1-directory-structure.txt
  ```

  **Commit**: NO

---

- [ ] 2. 实现 AgentContext 上下文类

  **What to do**:
  - 创建 `context.py`
  - 实现 `AgentContext` dataclass：
    - `agent_id: str` - UUID
    - `parent_id: Optional[str]` - None表示root
    - `depth: int` - 0=root, 1=子agent
    - `allowed_tools: Set[str]` - 工具白名单
    - `conversation_id: str` - 独立会话ID
    - `created_at: datetime`
    - `status: str` - running/completed/failed
  - `result: Optional[str]` - 任务结果

  **Must NOT do**:
  - 不要添加复杂的权限系统

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 简单的数据类定义
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 3, 4)
  - **Blocks**: Tasks 5, 6, 7, 8
  - **Blocked By**: None

  **References**:
  - `src/llm_chat/conversation.py` - Conversation类参考
  - `src/llm_chat/storage.py` - Storage类参考

  **Acceptance Criteria**:
  - [ ] `AgentContext` 类定义完成
  - [ ] 所有字段有正确的类型注解
  - [ ] dataclass 装饰器正确使用

  **QA Scenarios**:
  ```
  Scenario: 验证AgentContext创建
    Tool: Bash (python -c)
    Preconditions: context.py 文件存在
    Steps:
      1. cd /Users/xunwu/Documents/git/vermilion-bird
      2. python -c "from llm_chat.skills.task_delegator.context import AgentContext; ctx = AgentContext(agent_id='test', parent_id=None, depth=0, allowed_tools={'tool1'}, conversation_id='conv_1'); print(ctx)"
    Expected Result: AgentContext 实例创建成功， 打印包含 agent_id='test', depth=0
 allowed_tools={'tool1'}
    Evidence: .sisyphus/evidence/task-2-agent-context.txt
  ```

  **Commit**: NO

---

- [ ] 3. 实现 SubAgentRegistry 注册表

  **What to do**:
  - 创建 `registry.py`
  - 实现子agent注册表，管理所有活跃的子agent
  - 方法：
    - `spawn(agent_id, config)` - 创建子agent
    - `get(agent_id)` - 获取子agent
    - `cancel(agent_id)` - 取消子agent
    - `list_active()` - 列出所有活跃子agent
    - `clear_completed()` - 清理已完成的子agent

  **Must NOT do**:
  - 不要使用全局变量

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 简单的注册表实现
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 2, 4)
  - **Blocks**: Tasks 5, 6, 7, 8
  - **Blocked By**: None

  **References**:
  - `src/llm_chat/skills/task_delegator/context.py` - AgentContext
  - `src/llm_chat/storage.py` - Storage参考

  **Acceptance Criteria**:
  - [ ] `SubAgentRegistry` 类实现完成
  - [ ] `spawn()` 方法正确创建子agent
  - [ ] `get()` 方法正确获取子agent
  - [ ] `cancel()` 方法正确取消子agent
  - [ ] `list_active()` 方法正确列出活跃子agent

  **QA Scenarios**:
  ```
  Scenario: 验证子agent注册和取消
    Tool: Bash (python -c)
    Preconditions: registry.py 文件存在
    Steps:
      1. cd /Users/xunwu/Documents/git/vermilion-bird
      2. python -c "
      from llm_chat.skills.task_delegator.registry import SubAgentRegistry
      registry = SubAgentRegistry()
      agent_id = registry.spawn('test', AgentContext(agent_id='test', ...))
      print(registry.get('test'))  # Should return agent
      agent = registry.cancel('test')
      print(registry.get('test'))  # Should return None
    Expected Result: 子agent可以正确注册和取消
    Evidence: .sisyphus/evidence/task-3-registry.txt
  ```

  **Commit**: NO

---

- [ ] 4. 创建 TDD 测试骨架

  **What to do**:
  - 创建 `tests/test_task_delegator.py`
  - 编写测试用例框架（RED阶段）
  - 测试场景：
      - 测试递归防护（depth检查）
      - 测试工具白名单过滤
      - 测试上下文隔离

  **Must NOT do**:
  - 不要实现具体功能（只写测试框架）

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 创建测试文件和测试框架
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 2, 3)
  - **Blocks**: Task 10
  - **Blocked By**: None

  **References**:
  - `tests/` - 现有测试目录结构
  - `pytest` 文档 - 测试模式参考

  **Acceptance Criteria**:
  - [ ] `tests/test_task_delegator.py` 文件存在
  - [ ] 测试框架包含基本的测试用例

  **QA Scenarios**:
  ```
  Scenario: 验证测试框架
    Tool: Bash
    Steps:
      1. cd /Users/xunwu/Documents/git/vermilion-bird
      2. poetry run pytest tests/test_task_delegator.py -v
    Expected Result: 测试运行，没有错误（即使测试失败也是正常，因为是RED阶段）
    Evidence: .sisyphus/evidence/task-4-test-skeleton.txt
  ```

  **Commit**: NO

---

- [ ] 5. 实现 SpawnSubagentTool

  **What to do**:
  - 创建 `tools.py`
  - 实现 `SpawnSubagentTool(BaseTool)`:
    - `name`: "spawn_subagent"
    - `description`: 创建子agent并分配任务
    - `get_parameters_schema()`: 定义 task, allowed_tools, timeout 参数
    - `execute()`:
      1. 检查 `context.depth >= 1`，如果是则拒绝
      2. 生成 agent_id (UUID)
      3. 创建 AgentContext
      4. 创建独立的 Conversation
      5. 过滤工具列表（排除 spawn_subagent）
      6. 调用 LLMClient.chat_with_tools() 执行任务
      7. 等待完成，返回结果

  **Must NOT do**:
  - 不要在 depth >= 1 时创建子agent
  - 不要让子agent访问 spawn_subagent 工具

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: 核心业务逻辑，需要深入理解
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Sequential (depends on Task 3)
  - **Blocks**: Tasks 8, 10
  - **Blocked By**: Tasks 2, 3

  **References**:
  - `src/llm_chat/tools/base.py` - BaseTool接口
  - `src/llm_chat/client.py:88-100` - LLMClient使用示例
  - `src/llm_chat/conversation.py` - Conversation创建
  - `src/llm_chat/skills/task_delegator/context.py` - AgentContext
  - `src/llm_chat/skills/task_delegator/registry.py` - SubAgentRegistry

  **Acceptance Criteria**:
  - [ ] `SpawnSubagentTool` 类实现完成
  - [ ] depth >= 1 时返回错误
  - [ ] 成功创建子agent并返回结果
  - [ ] 工具列表正确过滤（不包含 spawn_subagent）

  **QA Scenarios**:
  ```
  Scenario: 递归防护测试
    Tool: Bash (pytest)
    Steps:
      1. 创建depth=1的AgentContext
      2. 调用 SpawnSubagentTool.execute()
      3. 验证返回错误消息
    Expected Result: 返回 "Cannot spawn subagent: recursion not allowed"
    Evidence: .sisyphus/evidence/task-5-recursion-prevention.txt

  Scenario: 工具白名单过滤测试
    Tool: Bash (pytest)
    Steps:
      1. 创建depth=0的AgentContext，allowed_tools包含 'web_search', 'calculator', 'spawn_subagent'
      2. 调用 SpawnSubagentTool.execute()
      3. 验证子agent的allowed_tools不包含 'spawn_subagent'
    Expected Result: 子agent的allowed_tools = {'web_search', 'calculator'}
    Evidence: .sisyphus/evidence/task-5-tool-filtering.txt

  Scenario: 成功创建子agent测试
    Tool: Bash (pytest)
    Steps:
      1. 创建depth=0的AgentContext
      2. 调用 SpawnSubagentTool.execute(task="搜索Python教程", allowed_tools=['web_search'])
      3. 验证返回包含agent_id
      4. 验证子agent在registry中注册
    Expected Result: 返回结果包含agent_id，registry中有对应记录
    Evidence: .sisyphus/evidence/task-5-spawn-success.txt
  ```

  **Commit**: NO

---

- [ ] 6. 实现 GetSubagentStatusTool

  **What to do**:
  - 在 `tools.py` 中实现 `GetSubagentStatusTool(BaseTool)`:
    - `name`: "get_subagent_status"
    - `description`: 查询子agent状态
    - `get_parameters_schema()`: 定义 agent_id 参数
    - `execute()`:
      1. 从registry获取子agent
      2. 返回状态信息（status, result, created_at等）

  **Must NOT do**:
  - 不要查询不存在的agent

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 简单的查询操作
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 5, 7)
  - **Blocks**: Task 10
  - **Blocked By**: Task 3

  **References**:
  - `src/llm_chat/tools/base.py` - BaseTool接口
  - `src/llm_chat/skills/task_delegator/registry.py` - SubAgentRegistry

  **Acceptance Criteria**:
  - [ ] `GetSubagentStatusTool` 类实现完成
  - [ ] 查询存在的agent返回正确状态
  - [ ] 查询不存在的agent返回错误

  **QA Scenarios**:
  ```
  Scenario: 查询存在的子agent
    Tool: Bash (pytest)
    Steps:
      1. 创建一个子agent
      2. 调用 GetSubagentStatusTool.execute(agent_id)
      3. 验证返回状态为 'running' 或 'completed'
    Expected Result: 返回正确的状态信息
    Evidence: .sisyphus/evidence/task-6-status-success.txt

  Scenario: 查询不存在的子agent
    Tool: Bash (pytest)
    Steps:
      1. 调用 GetSubagentStatusTool.execute('non-existent-id')
      2. 验证返回错误消息
    Expected Result: 返回 "Subagent not found" 错误
    Evidence: .sisyphus/evidence/task-6-status-not-found.txt
  ```

  **Commit**: NO

---

- [ ] 7. 实现 CancelSubagentTool

  **What to do**:
  - 在 `tools.py` 中实现 `CancelSubagentTool(BaseTool)`:
    - `name`: "cancel_subagent"
    - `description`: 取消子agent任务
    - `get_parameters_schema()`: 定义 agent_id 参数
    - `execute()`:
      1. 从registry获取子agent
      2. 如果正在运行，取消并清理
      3. 返回取消结果

  **Must NOT do**:
  - 不要取消已完成的agent

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 简单的取消操作
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 5, 6)
  - **Blocks**: Task 10
  - **Blocked By**: Task 3

  **References**:
  - `src/llm_chat/tools/base.py` - BaseTool接口
  - `src/llm_chat/skills/task_delegator/registry.py` - SubAgentRegistry

  **Acceptance Criteria**:
  - [ ] `CancelSubagentTool` 类实现完成
  - [ ] 取消running状态的agent成功
  - [ ] 取消不存在的agent返回错误

  **QA Scenarios**:
  ```
  Scenario: 取消运行中的子agent
    Tool: Bash (pytest)
    Steps:
      1. 创建一个子agent（不等待完成）
      2. 调用 CancelSubagentTool.execute(agent_id)
      3. 验证返回成功消息
    Expected Result: 返回 "Subagent cancelled successfully"
    Evidence: .sisyphus/evidence/task-7-cancel-success.txt

  Scenario: 取消不存在的子agent
    Tool: Bash (pytest)
    Steps:
      1. 调用 CancelSubagentTool.execute('non-existent-id')
      2. 验证返回错误消息
    Expected Result: 返回 "Subagent not found" 错误
    Evidence: .sisyphus/evidence/task-7-cancel-not-found.txt
  ```

  **Commit**: NO

---

- [ ] 8. 实现 TaskDelegatorSkill

  **What to do**:
  - 创建 `skill.py`
  - 实现 `TaskDelegatorSkill(BaseSkill)`:
    - `name`: "task_delegator"
    - `description`: 子agent任务分配能力
    - `get_tools()`: 返回 [SpawnSubagentTool(), GetSubagentStatusTool(), CancelSubagentTool()]
    - `on_load()`: 初始化，日志记录

  **Must NOT do**:
  - 不要在on_load中执行复杂操作

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 简单的skill集成
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Sequential (depends on Tasks 5, 6, 7)
  - **Blocks**: Tasks 9, 10
  - **Blocked By**: Tasks 5, 6, 7

  **References**:
  - `src/llm_chat/skills/base.py` - BaseSkill接口
  - `src/llm_chat/skills/task_delegator/tools.py` - 工具类
  - `src/llm_chat/skills/web_search/skill.py` - 现有skill参考

  **Acceptance Criteria**:
  - [ ] `TaskDelegatorSkill` 类实现完成
  - [ ] `get_tools()` 返回正确的工具列表
  - [ ] `on_load()` 正确执行

  **QA Scenarios**:
  ```
  Scenario: 验证skill加载
    Tool: Bash (python -c)
    Steps:
      1. from llm_chat.skills.task_delegator.skill import TaskDelegatorSkill
      2. skill = TaskDelegatorSkill()
      3. tools = skill.get_tools()
      4. 验证len(tools) == 3
    Expected Result: 返回3个工具
    Evidence: .sisyphus/evidence/task-8-skill-load.txt
  ```

  **Commit**: NO

---

- [ ] 9. 注册到 registry.py

  **What to do**:
  - 更新 `src/llm_chat/skills/registry.py`
  - 添加 `TaskDelegatorSkill` 到 `_BUILTIN_SKILLS`

  **Must NOT do**:
  - 不要删除现有的skill注册

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 简单的注册操作
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Sequential (depends on Task 8)
  - **Blocks**: Task 10
  - **Blocked By**: Task 8

  **References**:
  - `src/llm_chat/skills/registry.py` - 现有注册表
  - `src/llm_chat/skills/task_delegator/skill.py` - TaskDelegatorSkill

  **Acceptance Criteria**:
  - [ ] `registry.py` 正确导入 TaskDelegatorSkill
  - [ ] `_BUILTIN_SKILLS` 包含 "task_delegator"

  **QA Scenarios**:
  ```
  Scenario: 验证skill注册
    Tool: Bash (python -c)
    Steps:
      1. from llm_chat.skills.registry import get_builtin_skills
      2. skills = get_builtin_skills()
      3. 验证 "task_delegator" in skills
    Expected Result: "task_delegator" 在内置skill列表中
    Evidence: .sisyphus/evidence/task-9-registry.txt
  ```

  **Commit**: NO

---

- [ ] 10. 运行测试验证（GREEN阶段）

  **What to do**:
  - 运行 `poetry run pytest tests/test_task_delegator.py -v`
  - 确保所有测试通过
  - 修复任何失败的测试

  **Must NOT do**:
  - 不要跳过失败的测试

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: 测试运行和修复
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Sequential (final验证)
  - **Blocks**: None
  - **Blocked By**: Tasks 8, 9

  **References**:
  - `tests/test_task_delegator.py` - 测试文件
  - `pytest` 文档

  **Acceptance Criteria**:
  - [ ] `poetry run pytest tests/test_task_delegator.py` 全部通过
  - [ ] 测试覆盖率 >= 80%

  **QA Scenarios**:
  ```
  Scenario: 运行完整测试套件
    Tool: Bash (pytest)
    Steps:
      1. cd /Users/xunwu/Documents/git/vermilion-bird
      2. poetry run pytest tests/test_task_delegator.py -v
      3. 验证所有测试通过
    Expected Result: 所有测试通过，0 failures
    Evidence: .sisyphus/evidence/task-10-tests-pass.txt
  ```

  **Commit**: YES
  - Message: `feat(skills): add task_delegator skill for subagent task delegation`
  - Files: `src/llm_chat/skills/task_delegator/`, `tests/test_task_delegator.py`
  - Pre-commit: `poetry run pytest tests/test_task_delegator.py`

---

## Final Verification Wave

- [ ] F1. **Plan Compliance Audit** - `oracle`
  验证所有 Must Have 和 Must NOT Have 条件
  Output: Must Have [N/N] | Must NOT Have [N/N] | VERDICT: APPROVE/reject

- [ ] F2. **Code Quality Review** - `unspecified-high`
  运行 tsc + linter + 测试
  Output: Build [PASS/FAIL] | Lint [PASS/FAIL] | Tests [N/N] | VERDICT

- [ ] F3. **Real Manual QA** - `unspecified-high`
  执行所有QA场景
  Output: Scenarios [N/N pass] | VERDICT
- [ ] F4. **Scope Fidelity Check** - `deep`
  验证实现与计划一致
  Output: Tasks [N/N compliant] | VERDICT

---

## Commit Strategy

- **10**: `feat(skills): add task_delegator skill for subagent task delegation` — task_delegator/, tests/test_task_delegator.py, `poetry run pytest tests/test_task_delegator.py`

---

## Success Criteria

### Verification Commands
```bash
poetry run pytest tests/test_task_delegator.py -v  # Expected: all tests pass
```

### Final Checklist
- [ ] 所有 Must Have 条件满足
- [ ] 所有 Must NOT Have 条件满足
- [ ] 所有测试通过
- [ ] 子agent递归防护生效
- [ ] 工具白名单过滤生效
