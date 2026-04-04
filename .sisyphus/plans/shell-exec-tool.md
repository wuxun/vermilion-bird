# Shell 执行工具开发计划

## TL;DR
> **Quick Summary**: 开发符合现有技能架构的Shell执行工具，支持模型调用执行受控Shell命令获取外部信息，包含完整安全限制机制
> 
> **Deliverables**:
> - Shell执行技能实现（支持白名单、工作目录限制、超时控制）
> - 配置项支持（默认启用、白名单配置）
> - 单元测试覆盖
> - 文档更新
> 
> **Estimated Effort**: Short
> **Parallel Execution**: NO - sequential
> **Critical Path**: 技能实现 → 配置集成 → 测试 → 文档

---

## Context

### Original Request
增加一个执行shell的tool，让模型能获取一些外部的信息，另外需要增加能执行命令的白名单限制

### Interview Summary
**Key Decisions**:
- 安全策略：配置化白名单，可在config.yaml中配置允许执行的命令列表
- 默认超时：5秒
- 工作目录：仅允许在当前项目目录内执行
- 日志记录：记录所有命令、参数、输出到日志
- 输出处理：超出长度限制时截断输出
- 默认启用：是，用户可在config.yaml中关闭
- 默认白名单：包含ls, pwd, cat, grep, head, tail, wc, du, df, git status, git log等只读安全命令
- 单元测试：需要添加完整单元测试

**Research Findings**:
现有技能架构使用BaseSkill和BaseTool抽象类，技能在src/llm_chat/skills/目录下自动发现和注册，工具通过ToolRegistry全局管理，自动适配OpenAI/Anthropic等协议的工具调用格式。

### Metis Review
无额外gap，所有需求清晰明确。

---

## Work Objectives

### Core Objective
开发一个安全、受控的Shell执行技能，允许大模型在权限范围内执行系统命令获取外部信息。

### Concrete Deliverables
- src/llm_chat/skills/shell_exec/skill.py：Shell执行工具实现
- config.yaml配置项更新：添加shell_exec技能配置
- 单元测试文件：tests/test_skills_shell_exec.py
- 文档更新：README中新增Shell技能说明

### Definition of Done
- [ ] 技能可以正常加载并注册到ToolRegistry
- [ ] 白名单校验功能正常，非白名单命令被拒绝
- [ ] 工作目录限制有效，无法访问项目外目录
- [ ] 超时控制生效，长命令被自动终止
- [ ] 所有命令执行记录到日志
- [ ] 单元测试全部通过
- [ ] 模型可以正常调用工具执行命令并获取结果

### Must Have
- 配置化白名单机制
- 工作目录访问限制
- 执行超时控制
- 完整执行日志记录
- 输出截断处理

### Must NOT Have (Guardrails)
- 不允许执行任意未授权命令
- 不允许访问项目目录外的文件系统
- 不允许执行会修改系统状态的危险命令（默认白名单不包含）
- 不允许泄露系统敏感信息

---

## Verification Strategy (MANDATORY)
> **ZERO HUMAN INTERVENTION** — ALL verification is agent-executed. No exceptions.
> Acceptance criteria requiring "user manually tests/confirms" are FORBIDDEN.

### Test Decision
- **Infrastructure exists**: YES
- **Automated tests**: TDD
- **Framework**: pytest
- **If TDD**: Each task follows RED (failing test) → GREEN (minimal impl) → REFACTOR

### QA Policy
Every task MUST include agent-executed QA scenarios (see TODO template below).
Evidence saved to `.sisyphus/evidence/task-{N}-{scenario-slug}.{ext}`.

- **Library/Module**: Use Bash (poetry run pytest) — Run tests, verify results
- **CLI**: Use Bash (poetry run vermilion-bird) — 测试工具调用功能

---

## Execution Strategy

### Parallel Execution Waves
```
Wave 1 (Start Immediately):
├── Task 1: 创建Shell执行技能目录和基础结构
├── Task 2: 实现ShellExecTool工具类（包含安全校验、执行逻辑）
├── Task 3: 实现ShellExecSkill技能类
├── Task 4: 添加配置项支持
├── Task 5: 编写单元测试
├── Task 6: 更新文档
└── Task 7: 功能验证与集成测试

Wave FINAL (After ALL tasks):
├── F1: Plan Compliance Audit
├── F2: Code Quality Review
├── F3: Real Manual QA
└── F4: Scope Fidelity Check
```

### Dependency Matrix
- **1**: — — 2, 1
- **2**: 1 — 3, 2
- **3**: 2 — 4, 2
- **4**: 3 — 5, 3
- **5**: 4 — 6, 4
- **6**: 5 — 7, 5
- **7**: 6 — FINAL, 6

### Agent Dispatch Summary
- **1**: **7** — T1-T2 → `quick`, T3 → `quick`, T4 → `quick`, T5 → `quick`, T6 → `quick`, T7 → `unspecified-low`
- **FINAL**: **4** — F1 → `oracle`, F2 → `unspecified-high`, F3 → `unspecified-high`, F4 → `deep`

---

## TODOs

> Implementation + Test = ONE Task. Never separate.
> EVERY task MUST have: Recommended Agent Profile + Parallelization info + QA Scenarios.
> **A task WITHOUT QA Scenarios is INCOMPLETE. No exceptions.**

- [ ] 1. 创建Shell执行技能目录和基础结构

  **What to do**:
  - 在src/llm_chat/skills/目录下创建shell_exec子目录
  - 创建skill.py文件，导入必要的依赖（BaseSkill, BaseTool等）
  - 创建__init__.py文件（如果需要）

  **Must NOT do**:
  - 不要修改现有其他技能的代码
  - 不要修改核心注册逻辑

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 简单的目录和文件创建任务
  - **Skills**: []
    - 不需要特殊技能
  - **Skills Evaluated but Omitted**:
    - 无

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 1
  - **Blocks**: Task 2, Task 3
  - **Blocked By**: None (can start immediately)

  **References**:
  **Pattern References**:
  - `src/llm_chat/skills/calculator/` - 参考计算器技能的目录结构

  **Acceptance Criteria**:
  - [ ] 目录src/llm_chat/skills/shell_exec/已创建
  - [ ] 文件src/llm_chat/skills/shell_exec/skill.py已创建
  - [ ] 文件src/llm_chat/skills/shell_exec/__init__.py已创建（可选）

  **QA Scenarios**:
  ```
  Scenario: 目录结构检查
    Tool: Bash (ls)
    Preconditions: 无
    Steps:
      1. 运行 ls src/llm_chat/skills/
      2. 验证shell_exec目录存在
      3. 运行 ls src/llm_chat/skills/shell_exec/
      4. 验证skill.py文件存在
    Expected Result: 目录和文件都存在
    Failure Indicators: 目录或文件不存在
    Evidence: .sisyphus/evidence/task-1-directory-check.txt
  ```

  **Commit**: YES
  - Message: `feat: add shell exec skill directory structure`
  - Files: `src/llm_chat/skills/shell_exec/*`


- [ ] 2. 实现ShellExecTool工具类（包含安全校验、执行逻辑）

  **What to do**:
  - 实现ShellExecTool类继承自BaseTool
  - 实现name、description属性
  - 实现get_parameters_schema方法，定义command（必填）、workdir（可选）、timeout（可选）参数
  - 实现execute方法，包含以下逻辑：
    1. 白名单校验：检查命令是否在配置的白名单中
    2. 工作目录校验：检查工作目录是否在项目目录范围内
    3. 执行命令：使用subprocess.run执行，设置超时时间
    4. 输出处理：超出长度限制时截断
    5. 日志记录：记录所有执行的命令、参数、返回码、输出
  - 默认输出长度限制：10000字符，超出部分截断并提示

  **Must NOT do**:
  - 不要使用shell=True执行命令，避免注入风险
  - 不要允许执行未在白名单中的命令
  - 不要泄露系统敏感信息到输出中

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 工具类实现，遵循现有模式
  - **Skills**: []
    - 不需要特殊技能
  - **Skills Evaluated but Omitted**:
    - 无

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 1
  - **Blocks**: Task 3
  - **Blocked By**: Task 1

  **References**:
  **Pattern References**:
  - `src/llm_chat/skills/calculator/skill.py:CalculatorTool` - 参考工具类实现模式
  - `src/llm_chat/tools/base.py` - BaseTool接口定义

  **Acceptance Criteria**:
  - [ ] ShellExecTool类已实现所有必要接口
  - [ ] 白名单校验逻辑正确
  - [ ] 工作目录限制逻辑正确
  - [ ] 超时控制逻辑正确
  - [ ] 输出截断逻辑正确
  - [ ] 日志记录功能正常

  **QA Scenarios**:
  ```
  Scenario: 白名单校验 - 允许执行白名单命令
    Tool: Python REPL
    Preconditions: 白名单包含"ls"
    Steps:
      1. 实例化ShellExecTool
      2. 调用execute(command="ls")
      3. 验证命令执行成功，返回正确输出
    Expected Result: 执行成功，返回当前目录文件列表
    Failure Indicators: 执行被拒绝或返回错误
    Evidence: .sisyphus/evidence/task-2-whitelist-pass.txt

  Scenario: 白名单校验 - 拒绝执行非白名单命令
    Tool: Python REPL
    Preconditions: 白名单不包含"rm"
    Steps:
      1. 实例化ShellExecTool
      2. 调用execute(command="rm test.txt")
      3. 验证命令被拒绝，返回错误信息
    Expected Result: 执行被拒绝，提示命令不在白名单中
    Failure Indicators: 命令被执行或无错误提示
    Evidence: .sisyphus/evidence/task-2-whitelist-fail.txt
  ```

  **Commit**: YES
  - Message: `feat: implement ShellExecTool with security checks`
  - Files: `src/llm_chat/skills/shell_exec/skill.py`


- [ ] 3. 实现ShellExecSkill技能类

  **What to do**:
  - 实现ShellExecSkill类继承自BaseSkill
  - 实现name、description、version属性
  - 实现get_tools方法，返回[ShellExecTool()]实例
  - 实现on_load方法，处理配置加载和日志记录
  - 默认白名单配置：["ls", "pwd", "cat", "grep", "head", "tail", "wc", "du", "df", "git status", "git log"]

  **Must NOT do**:
  - 不要修改SkillManager的核心逻辑
  - 不要添加不必要的依赖

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 技能类实现，遵循现有模式
  - **Skills**: []
    - 不需要特殊技能
  - **Skills Evaluated but Omitted**:
    - 无

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 1
  - **Blocks**: Task 4
  - **Blocked By**: Task 2

  **References**:
  **Pattern References**:
  - `src/llm_chat/skills/calculator/skill.py:CalculatorSkill` - 参考技能类实现模式
  - `src/llm_chat/skills/base.py` - BaseSkill接口定义

  **Acceptance Criteria**:
  - [ ] ShellExecSkill类已实现所有必要接口
  - [ ] get_tools方法返回正确的ShellExecTool实例
  - [ ] on_load方法可以正确加载配置
  - [ ] 默认白名单配置正确

  **QA Scenarios**:
  ```
  Scenario: 技能加载测试
    Tool: Python REPL
    Steps:
      1. 导入ShellExecSkill类
      2. 实例化技能
      3. 调用get_tools()方法，验证返回的工具列表包含ShellExecTool实例
      4. 调用on_load方法，验证配置加载正常
    Expected Result: 技能加载成功，工具实例正确
    Failure Indicators: 加载失败或工具实例不正确
    Evidence: .sisyphus/evidence/task-3-skill-load.txt
  ```

  **Commit**: YES
  - Message: `feat: implement ShellExecSkill`
  - Files: `src/llm_chat/skills/shell_exec/skill.py`


- [ ] 4. 添加配置项支持

  **What to do**:
  - 在config.yaml中添加shell_exec技能配置项：
    ```yaml
    skills:
      shell_exec:
        enabled: true
        whitelist: ["ls", "pwd", "cat", "grep", "head", "tail", "wc", "du", "df", "git status", "git log"]
        default_timeout: 5
        max_output_length: 10000
        allowed_workdir: "./"
    ```
  - 在ShellExecSkill的on_load方法中读取这些配置项
  - 确保配置优先级：环境变量 > config.yaml > 默认值

  **Must NOT do**:
  - 不要破坏现有配置加载逻辑
  - 不要添加不必要的全局配置

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 配置项添加，简单修改
  - **Skills**: []
    - 不需要特殊技能
  - **Skills Evaluated but Omitted**:
    - 无

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 1
  - **Blocks**: Task 5
  - **Blocked By**: Task 3

  **References**:
  **Pattern References**:
  - `src/llm_chat/config.py` - 参考配置加载逻辑
  - 其他技能的配置实现方式

  **Acceptance Criteria**:
  - [ ] config.yaml中已添加shell_exec配置项
  - [ ] ShellExecSkill可以正确读取配置
  - [ ] 配置优先级逻辑正确

  **QA Scenarios**:
  ```
  Scenario: 配置加载测试
    Tool: Python REPL
    Steps:
      1. 修改config.yaml中的shell_exec配置
      2. 加载ShellExecSkill
      3. 验证配置项被正确读取
    Expected Result: 配置项读取正确，与config.yaml中的值一致
    Failure Indicators: 配置读取错误或使用默认值
    Evidence: .sisyphus/evidence/task-4-config-load.txt
  ```

  **Commit**: YES
  - Message: `feat: add shell exec skill config support`
  - Files: `config.yaml`, `src/llm_chat/skills/shell_exec/skill.py`


- [ ] 5. 编写单元测试

  **What to do**:
  - 创建tests/test_skills_shell_exec.py测试文件
  - 编写测试用例覆盖以下场景：
    1. 技能加载和工具注册测试
    2. 白名单校验测试（允许/拒绝场景）
    3. 工作目录限制测试（允许/拒绝场景）
    4. 超时控制测试
    5. 输出截断测试
    6. 配置加载测试
    7. 错误处理测试（命令不存在、执行失败等）
  - 确保所有测试用例可以独立运行，不依赖外部环境

  **Must NOT do**:
  - 不要编写会修改系统状态的测试用例
  - 不要使用真实系统中的敏感信息进行测试

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 单元测试编写，遵循现有测试模式
  - **Skills**: []
    - 不需要特殊技能
  - **Skills Evaluated but Omitted**:
    - 无

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 1
  - **Blocks**: Task 6
  - **Blocked By**: Task 4

  **References**:
  **Pattern References**:
  - `tests/test_skills_calculator.py` - 参考现有技能测试的结构和写法
  - pytest文档 - 测试用例编写规范

  **Acceptance Criteria**:
  - [ ] 测试文件tests/test_skills_shell_exec.py已创建
  - [ ] 所有测试用例编写完成
  - [ ] 运行poetry run pytest tests/test_skills_shell_exec.py全部通过

  **QA Scenarios**:
  ```
  Scenario: 单元测试运行
    Tool: Bash (poetry run pytest)
    Steps:
      1. 运行 poetry run pytest tests/test_skills_shell_exec.py -v
      2. 验证所有测试用例通过
    Expected Result: 所有测试用例PASS，无失败
    Failure Indicators: 有测试用例失败或报错
    Evidence: .sisyphus/evidence/task-5-unit-tests.txt
  ```

  **Commit**: YES
  - Message: `test: add shell exec skill unit tests`
  - Files: `tests/test_skills_shell_exec.py`


- [ ] 6. 更新文档

  **What to do**:
  - 在README.md中添加Shell执行技能的说明文档
  - 包含功能介绍、配置说明、使用示例
  - 说明安全限制和最佳实践

  **Must NOT do**:
  - 不要修改其他无关文档内容
  - 不要提供不安全的使用示例

  **Recommended Agent Profile**:
  - **Category**: `writing`
    - Reason: 文档更新任务
  - **Skills**: []
    - 不需要特殊技能
  - **Skills Evaluated but Omitted**:
    - 无

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 1
  - **Blocks**: Task 7
  - **Blocked By**: Task 5

  **References**:
  **Pattern References**:
  - README.md中其他技能的文档说明格式

  **Acceptance Criteria**:
  - [ ] README.md中已添加Shell执行技能的完整说明
  - [ ] 文档内容准确，包含配置和使用示例

  **QA Scenarios**:
  ```
  Scenario: 文档检查
    Tool: Bash (cat)
    Steps:
      1. 运行 cat README.md | grep -A 10 "Shell 执行技能"
      2. 验证文档内容存在且完整
    Expected Result: 找到Shell执行技能的说明文档，内容完整
    Failure Indicators: 找不到文档或内容不完整
    Evidence: .sisyphus/evidence/task-6-documentation.txt
  ```

  **Commit**: YES
  - Message: `docs: update README for shell exec skill`
  - Files: `README.md`


- [ ] 7. 功能验证与集成测试

  **What to do**:
  - 启动应用，验证Shell技能可以正常加载
  - 测试模型调用工具执行命令的完整流程
  - 验证所有安全限制生效
  - 修复发现的问题

  **Must NOT do**:
  - 不要修改核心功能逻辑，仅修复发现的bug
  - 不要引入新的功能特性

  **Recommended Agent Profile**:
  - **Category**: `unspecified-low`
    - Reason: 集成测试和bug修复
  - **Skills**: []
    - 不需要特殊技能
  - **Skills Evaluated but Omitted**:
    - 无

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 1
  - **Blocks**: Final Verification Wave
  - **Blocked By**: Task 6

  **References**:
  **Pattern References**:
  - 现有技能的集成测试方法

  **Acceptance Criteria**:
  - [ ] 应用启动时Shell技能正常加载，无报错
  - [ ] 模型可以正常调用Shell工具执行白名单命令
  - [ ] 所有安全限制功能正常工作
  - [ ] 所有单元测试仍然通过

  **QA Scenarios**:
  ```
  Scenario: 集成测试 - 应用启动加载
    Tool: Bash (poetry run)
    Steps:
      1. 运行 poetry run vermilion-bird --help
      2. 验证应用启动无报错，Shell技能正常加载
    Expected Result: 应用启动成功，无技能加载错误
    Failure Indicators: 应用启动失败或有技能加载错误
    Evidence: .sisyphus/evidence/task-7-integration-startup.txt

  Scenario: 集成测试 - 工具调用
    Tool: Python REPL
    Steps:
      1. 初始化应用，加载所有技能
      2. 从ToolRegistry获取shell_exec工具
      3. 调用execute(command="pwd")，验证返回正确的当前目录
    Expected Result: 工具调用成功，返回正确的工作目录路径
    Failure Indicators: 工具调用失败或返回错误
    Evidence: .sisyphus/evidence/task-7-integration-tool-call.txt
  ```

  **Commit**: YES (if fixes needed)
  - Message: `fix: resolve shell exec skill integration issues`
  - Files: 仅修改需要修复的文件

---

## Final Verification Wave (MANDATORY — after ALL implementation tasks)
> 4 review agents run in PARALLEL. ALL must APPROVE. Present consolidated results to user and get explicit "okay" before completing.
>
> **Do NOT auto-proceed after verification. Wait for user's explicit approval before marking work complete.**
> **Never mark F1-F4 as checked before getting user's okay.** Rejection or user feedback -> fix -> re-run -> present again -> wait for okay.

- [ ] F1. **Plan Compliance Audit** — `oracle`
  Read the plan end-to-end. For each "Must Have": verify implementation exists (read file, curl endpoint, run command). For each "Must NOT Have": search codebase for forbidden patterns — reject with file:line if found. Check evidence files exist in .sisyphus/evidence/. Compare deliverables against plan.
  Output: `Must Have [N/N] | Must NOT Have [N/N] | Tasks [N/N] | VERDICT: APPROVE/REJECT`

- [ ] F2. **Code Quality Review** — `unspecified-high`
  Run `poetry run flake8` + `poetry run black --check .` + `poetry run tsc --noEmit` (如果适用) + `poetry run pytest`. Review all changed files for: `as any`/`@ts-ignore` (如果适用), empty catches, console.log in prod, commented-out code, unused imports. Check AI slop: excessive comments, over-abstraction, generic names (data/result/item/temp).
  Output: `Build [PASS/FAIL] | Lint [PASS/FAIL] | Tests [N pass/N fail] | Files [N clean/N issues] | VERDICT`

- [ ] F3. **Real Manual QA** — `unspecified-high`
  Start from clean state. Execute EVERY QA scenario from EVERY task — follow exact steps, capture evidence. Test cross-task integration (features working together, not isolation). Test edge cases: empty state, invalid input, rapid actions. Save to `.sisyphus/evidence/final-qa/`.
  Output: `Scenarios [N/N pass] | Integration [N/N] | Edge Cases [N tested] | VERDICT`

- [ ] F4. **Scope Fidelity Check** — `deep`
  For each task: read "What to do", read actual diff (git log/diff). Verify 1:1 — everything in spec was built (no missing), nothing beyond spec was built (no creep). Check "Must NOT do" compliance. Detect cross-task contamination: Task N touching Task M's files. Flag unaccounted changes.
  Output: `Tasks [N/N compliant] | Contamination [CLEAN/N issues] | Unaccounted [CLEAN/N files] | VERDICT`

---

## Commit Strategy
- Task 1: `feat: add shell exec skill directory structure`
- Task 2: `feat: implement ShellExecTool with security checks`
- Task 3: `feat: implement ShellExecSkill`
- Task 4: `feat: add shell exec skill config support`
- Task 5: `test: add shell exec skill unit tests`
- Task 6: `docs: update README for shell exec skill`
- Task 7: `test: integrate shell exec skill verification`

---

## Success Criteria

### Verification Commands
```bash
poetry run pytest tests/test_skills_shell_exec.py  # Expected: all tests pass
poetry run vermilion-bird --version  # Expected: app loads without error
```

### Final Checklist
- [ ] 所有"Must Have"功能已实现
- [ ] 所有"Must NOT Have"限制已生效
- [ ] 所有单元测试通过
- [ ] 技能可以被模型正常调用
