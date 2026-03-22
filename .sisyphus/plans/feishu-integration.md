# 飞书 Bot 集成工作计划

## TL;DR

> **Quick Summary**: 集成飞书 Bot 到 vermilion-bird，支持消息接收、LLM 对话响应和主动推送能力。采用官方 lark-oapi SDK + 长连接模式，新建独立 frontends/feishu/ 模块，复用现有 App/Conversation/Storage/Memory/MCP 组件。
>
> **Deliverables**:
> - `frontends/feishu/` 新模块（Adapter + Server + PushService + Security）
> - `config.yaml` 飞书配置支持
> - CLI 启动命令 `vermilion-bird feishu`
> - 安全措施（签名验证 + Rate Limiting + 访问控制）
> - 单元测试 + 集成测试
>
> **Estimated Effort**: Medium（核心功能 3-4 天）
> **Parallel Execution**: YES - 5 waves
> **Critical Path**: Task 1 → Task 5 → Task 7 → Task 11 → Task 16 → Task 18

---

## Context

### Original Request
用户希望 vermilion-bird 支持与飞书等聊天工具进行对话的能力，包括 Bot 响应和主动推送。

### Interview Summary
**Key Discussions**:
- **平台**: 飞书（单租户）
- **集成模式**: Bot 响应 + 主动推送（定时报告、告警通知、任务提醒、外部触发）
- **部署**: 独立 HTTP 服务
- **消息类型**: 全媒体（文本、图片、卡片、文件）
- **会话策略**: 混合模式（群聊独立，私聊按用户隔离）
- **连接方式**: 长连接（WebSocket）
- **SDK**: lark-oapi（官方）

**Research Findings**:
- **架构建议**: 不直接继承 BaseFrontend，新建 FeishuAdapter + FeishuServer + PushService
- **会话映射**: `feishu_p2p_{open_id}` / `feishu_group_{chat_id}`
- **响应模式**: 异步（先返回 200，后台处理 LLM）
- **飞书要求**: 1s 内响应，需要异步处理

### Metis Review
**Identified Gaps** (addressed):
- **分阶段实施**: Phase 1 聚焦 MVP（文本 + 基础推送），Phase 2-3 增强功能
- **错误处理**: 添加重试、超时、限流策略
- **幂等处理**: 飞书可能重发事件，需要 event_id 去重
- **流式响应**: LLM 流式输出需要累积后发送

---

## Work Objectives

### Core Objective
为 vermilion-bird 添加飞书 Bot 集成能力，使用户能够：
1. 在飞书中与 LLM 进行对话（私聊或群聊 @ 机器人）
2. 通过定时任务、告警、提醒或外部触发主动推送消息

### Concrete Deliverables
- `src/llm_chat/frontends/feishu/` 目录及模块
- `src/llm_chat/frontends/feishu/__init__.py`
- `src/llm_chat/frontends/feishu/adapter.py` - 消息格式转换
- `src/llm_chat/frontends/feishu/server.py` - 长连接服务
- `src/llm_chat/frontends/feishu/push.py` - 主动推送服务
- `src/llm_chat/frontends/feishu/models.py` - 数据模型
- `src/llm_chat/frontends/feishu/security.py` - 安全模块（签名验证、限流、访问控制）
- `src/llm_chat/cli.py` - 添加 `feishu` 命令
- `config.yaml` - 飞书配置示例
- `tests/test_feishu*.py` - 单元测试

### Definition of Done
- [ ] `poetry run vermilion-bird feishu` 能启动飞书 Bot 服务
- [ ] 私聊机器人能收到 LLM 响应
- [ ] 群聊 @ 机器人能收到 LLM 响应
- [ ] 主动推送 API 能发送消息到飞书
- [ ] `poetry run pytest` 全部通过

### Must Have
- 文本消息接收与响应
- 会话持久化（复用 Storage）
- 长连接模式（lark-oapi ws.Client）
- 异步响应（1s 内 ack，后台处理）
- 主动推送基础能力（外部触发）
- **安全措施**:
  - 飞书签名验证（防伪造请求）
  - Rate Limiting（防滥用）
  - 访问控制（白名单/黑名单）
  - 凭据安全存储（环境变量优先）
- **安全措施**:
  - 飞书签名验证（防伪造请求）
  - Rate Limiting（防滥用）
  - 访问控制（白名单/黑名单）
  - 凭据安全存储（环境变量优先）

### Must NOT Have (Guardrails)
- ❌ 不继承 BaseFrontend（设计冲突）
- ❌ 不修改 App 类核心逻辑
- ❌ 不存储敏感凭据在代码中
- ❌ 不在 webhook handler 中同步调用 LLM
- ❌ 不实现复杂卡片编辑器 UI
- ❌ 不支持多租户
- ❌ 不添加其他聊天平台（钉钉、企微等）

---

## Verification Strategy

> **ZERO HUMAN INTERVENTION** — ALL verification is agent-executed.

### Test Decision
- **Infrastructure exists**: YES (Pytest 7.x + pytest-cov)
- **Automated tests**: YES (TDD)
- **Framework**: Pytest + pytest-asyncio
- **TDD**: 每个任务遵循 RED → GREEN → REFACTOR

### QA Policy
Every task MUST include agent-executed QA scenarios.
Evidence saved to `.sisyphus/evidence/task-{N}-{scenario-slug}.{ext}`.

- **API/Backend**: Use Bash (curl) — Send requests, assert status + response fields
- **Library/Module**: Use Bash (python -c) — Import, call functions, verify output

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (Foundation — 配置 + 数据模型):
├── Task 1: 添加 lark-oapi 依赖 + 配置支持 [quick]
├── Task 2: 飞书数据模型定义 [quick]
├── Task 3: 会话映射器实现 [quick]
└── Task 4: 配置加载与验证 [quick]

Wave 2 (Security — 安全模块):
├── Task 5: 签名验证器 [quick]
├── Task 6: Rate Limiter [quick]
├── Task 7: 访问控制器 [quick]
└── Task 8: 消息幂等处理器 [quick]

Wave 3 (Core — 适配器 + 服务):
├── Task 9: FeishuAdapter 核心实现 [deep]
├── Task 10: FeishuServer 长连接服务 [deep]
├── Task 11: 错误处理与重试机制 [unspecified-high]
└── Task 12: 安全集成 [deep]

Wave 4 (Integration — CLI + 推送):
├── Task 13: CLI feishu 命令 [quick]
├── Task 14: PushService 主动推送 [unspecified-high]
├── Task 15: 与 App 集成 [deep]
└── Task 16: 日志与监控 [quick]

Wave 5 (Quality — 测试 + 文档):
├── Task 17: 单元测试 [unspecified-high]
├── Task 18: 集成测试（含安全测试） [unspecified-high]
└── Task 19: 文档更新 [writing]

Wave FINAL (Verification — 4 parallel reviews):
├── Task F1: Plan compliance audit (oracle)
├── Task F2: Code quality review (unspecified-high)
├── Task F3: Real manual QA (unspecified-high)
└── Task F4: Scope fidelity check (deep)
-> Present results -> Get explicit user okay

Critical Path: Task 1 → Task 5 → Task 9 → Task 12 → Task 15 → Task 17 → F1-F4 → user okay
Parallel Speedup: ~65% faster than sequential
Max Concurrent: 4 (Waves 1-4)
```

### Dependency Matrix

- **1-4**: — — 5-12, 1
- **5**: 1 — 9, 12, 2
- **6**: 1 — 9, 12, 2
- **7**: 1 — 9, 12, 2
- **8**: 2 — 10, 2
- **9**: 2, 3, 5, 6, 7 — 10, 12, 15, 3
- **10**: 9, 8, 11 — 13, 15, 3
- **11**: — 10, 14, 2
- **12**: 5, 6, 7, 9 — 15, 3
- **13**: 10 — 19, 4
- **14**: 9, 11 — 15, 4
- **15**: 9, 10, 12, 14 — 17, 18, 5
- **16**: 10, 13 — 19, 4
- **17**: 15 — 18, 6
- **18**: 15, 17 — F1-F4, 6
- **19**: 13, 16 — F1-F4, 5

### Agent Dispatch Summary

- **Wave 1**: **4** — T1-T4 → `quick`
- **Wave 2**: **4** — T5-T8 → `quick`
- **Wave 3**: **4** — T9 → `deep`, T10 → `deep`, T11 → `unspecified-high`, T12 → `deep`
- **Wave 4**: **4** — T13 → `quick`, T14 → `unspecified-high`, T15 → `deep`, T16 → `quick`
- **Wave 5**: **3** — T17 → `unspecified-high`, T18 → `unspecified-high`, T19 → `writing`
- **FINAL**: **4** — F1 → `oracle`, F2 → `unspecified-high`, F3 → `unspecified-high`, F4 → `deep`

---

## TODOs

- [x] 1. 添加 lark-oapi 依赖 + 配置支持

  **What to do**:
  - 在 `pyproject.toml` 添加 `lark-oapi` 依赖
  - 在 `config.example.yaml` 添加飞书配置示例
  - 在 `src/llm_chat/config.py` 添加 `FeishuConfig` 数据类

  **Must NOT do**:
  - 不在代码中硬编码 App ID/Secret
  - 不修改现有 LLM 配置

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 简单的依赖添加和配置修改
  - **Skills**: []
  - **Skills Evaluated but Omitted**: 无

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 2, 3, 4)
  - **Blocks**: Task 5, 7, 9
  - **Blocked By**: None

  **References**:
  - `pyproject.toml` - 依赖格式参考
  - `config.example.yaml:1-30` - 配置格式参考
  - `src/llm_chat/config.py:Config` - 配置类结构参考

  **Acceptance Criteria**:
  - [ ] `lark-oapi` 在 `pyproject.toml` 的 `[tool.poetry.dependencies]` 中
  - [ ] `config.example.yaml` 包含 `feishu:` 配置节
  - [ ] `FeishuConfig` 类包含 `app_id`, `app_secret`, `enabled` 字段

  **QA Scenarios**:
  ```
  Scenario: 依赖安装成功
    Tool: Bash
    Steps:
      1. poetry install
      2. poetry show lark-oapi
    Expected Result: lark-oapi 版本号显示
    Evidence: .sisyphus/evidence/task-01-deps.txt

  Scenario: 配置加载成功
    Tool: Bash
    Steps:
      1. python -c "from llm_chat.config import Config; c = Config.from_yaml('config.example.yaml'); print(c.feishu)"
    Expected Result: 打印 FeishuConfig 对象（app_id 为示例值）
    Evidence: .sisyphus/evidence/task-01-config.txt
  ```

  **Commit**: YES (groups with 1-4)
  - Message: `feat(feishu): add lark-oapi dependency and configuration`
  - Files: `pyproject.toml`, `config.example.yaml`, `src/llm_chat/config.py`

---

- [x] 2. 飞书数据模型定义

  **What to do**:
  - 创建 `src/llm_chat/frontends/feishu/` 目录
  - 创建 `src/llm_chat/frontends/feishu/__init__.py`
  - 创建 `src/llm_chat/frontends/feishu/models.py`，定义：
    - `FeishuMessage` - 飞书消息结构
    - `FeishuEvent` - 飞书事件结构
    - `FeishuUser` - 飞书用户信息
    - `FeishuChat` - 飞书会话信息

  **Must NOT do**:
  - 不依赖 lark-oapi 的内部类型（使用自己的 dataclass）

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 简单的数据模型定义
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 3, 4)
  - **Blocks**: Task 5, 6
  - **Blocked By**: None

  **References**:
  - `src/llm_chat/frontends/base.py:Message` - Message 结构参考
  - `src/llm_chat/frontends/base.py:ConversationContext` - Context 结构参考
  - 飞书 API 文档: https://open.feishu.cn/document/server-docs/im-v1/message/events/receive

  **Acceptance Criteria**:
  - [ ] `frontends/feishu/` 目录存在
  - [ ] `models.py` 包含 `@dataclass` 装饰的 `FeishuMessage`, `FeishuEvent`, `FeishuUser`, `FeishuChat`
  - [ ] 所有字段有类型注解

  **QA Scenarios**:
  ```
  Scenario: 模块导入成功
    Tool: Bash
    Steps:
      1. python -c "from llm_chat.frontends.feishu.models import FeishuMessage, FeishuEvent, FeishuUser, FeishuChat; print('OK')"
    Expected Result: 打印 "OK"
    Evidence: .sisyphus/evidence/task-02-import.txt
  ```

  **Commit**: YES (groups with 1-4)

---

- [x] 3. 会话映射器实现

  **What to do**:
  - 在 `models.py` 或新建 `mapper.py` 实现 `SessionMapper` 类
  - 实现会话 ID 映射逻辑：
    - 私聊：`feishu_p2p_{open_id}`
    - 群聊：`feishu_group_{chat_id}`
  - 实现反向解析（从 conversation_id 获取原始 ID）

  **Must NOT do**:
  - 不在映射中使用特殊字符（只用字母数字下划线）

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 简单的字符串处理逻辑
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 2, 4)
  - **Blocks**: Task 5, 11
  - **Blocked By**: None

  **References**:
  - `src/llm_chat/storage.py:Storage` - 会话 ID 格式参考

  **Acceptance Criteria**:
  - [ ] `SessionMapper.to_conversation_id(chat_type, original_id)` 返回正确格式
  - [ ] `SessionMapper.from_conversation_id(conversation_id)` 返回 (chat_type, original_id)
  - [ ] 单元测试覆盖边界情况

  **QA Scenarios**:
  ```
  Scenario: 私聊会话映射
    Tool: Bash
    Steps:
      1. python -c "from llm_chat.frontends.feishu.mapper import SessionMapper; print(SessionMapper.to_conversation_id('p2p', 'ou_abc123'))"
    Expected Result: 打印 "feishu_p2p_ou_abc123"
    Evidence: .sisyphus/evidence/task-03-p2p.txt

  Scenario: 群聊会话映射
    Tool: Bash
    Steps:
      1. python -c "from llm_chat.frontends.feishu.mapper import SessionMapper; print(SessionMapper.to_conversation_id('group', 'oc_xyz789'))"
    Expected Result: 打印 "feishu_group_oc_xyz789"
    Evidence: .sisyphus/evidence/task-03-group.txt
  ```

  **Commit**: YES (groups with 1-4)

---

- [x] 4. 配置加载与验证

  **What to do**:
  - 在 `config.py` 的 `Config.from_yaml()` 中添加飞书配置加载
  - 支持环境变量覆盖：`FEISHU_APP_ID`, `FEISHU_APP_SECRET`
  - 添加配置验证（app_id 和 app_secret 不能为空如果 enabled=True）
  - 支持环境变量 `FEISHU_APP_ID`, `FEISHU_APP_SECRET`, `FEISHU_ENABLED`

  **Must NOT do**:
  - 不在日志中打印 app_secret

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 简单的配置加载逻辑
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 2, 3)
  - **Blocks**: Task 7, 9
  - **Blocked By**: Task 1

  **References**:
  - `src/llm_chat/config.py:Config.from_yaml()` - 配置加载参考
  - `src/llm_chat/config.py:Config.from_env()` - 环境变量参考

  **Acceptance Criteria**:
  - [ ] `Config.feishu` 返回 `FeishuConfig` 对象
  - [ ] 环境变量 `FEISHU_APP_ID` 覆盖 config.yaml
  - [ ] `enabled=True` 且缺少凭据时抛出 `ValueError`

  **QA Scenarios**:
  ```
  Scenario: 环境变量覆盖
    Tool: Bash
    Steps:
      1. FEISHU_APP_ID=test_id FEISHU_APP_SECRET=test_secret python -c "from llm_chat.config import Config; c = Config(); print(c.feishu.app_id)"
    Expected Result: 打印 "test_id"
    Evidence: .sisyphus/evidence/task-04-env.txt

  Scenario: 配置验证失败
    Tool: Bash
    Steps:
      1. python -c "from llm_chat.config import FeishuConfig; FeishuConfig(enabled=True, app_id='', app_secret='').validate()"
    Expected Result: 抛出 ValueError
    Evidence: .sisyphus/evidence/task-04-validate.txt
  ```

  **Commit**: YES (groups with 1-4)

---

- [x] 5. FeishuAdapter 核心实现 [deep]

  **What to do**:
  - 在 `adapter.py` 新建 `FeishuAdapter` 类
  - 实现消息格式转换:
    - 飞书事件 → 内部消息格式
    - 内部响应 → 飞书消息格式
  - 复用 App 类的 `handle_message()` 方法
  - 实现会话 ID 映射
  - 调用飞书 API 发送消息

  **Must NOT do**:
  - 不继承 BaseFrontend
  - 不修改 App 类核心逻辑
  - 不在 adapter 中存储敏感信息
  - 不实现复杂的卡片构建 UI

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: 核心消息处理逻辑
  - **Skills**: []
    - `librarian`: 查找 lark-oapi SDK 使用模式
      - Reason: 需要理解 SDK 的 API 调用方式

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 6, 7, 8)
  - **Blocks**: Task 9, 11
  - **Blocked By**: Task 2, 3

  **References**:
  - `lark-oapi` SDK 文档: https://open.feishu.cn/document/server-side-sdk/python--sdk
  - `src/llm_chat/app.py:handle_message()` - App 类的消息处理方法
  - `src/llm_chat/frontends/base.py:Message` - 内部消息格式
  - `src/llm_chat/storage.py` - 存储层
  - 飞书 API 文档: https://open.feishu.cn/document/server-docs/im-v1/message/create

  **Acceptance Criteria**:
  - [ ] 能接收飞书消息事件并转换格式
  - [ ] 能调用 App.handle_message() 获取 LLM 响应
  - [ ] 能将 LLM 响应转换为飞书消息并发送
  - [ ] 会话 ID 映射正确
  - [ ] 有单元测试覆盖

  **QA Scenarios**:
  ```
  Scenario: 接收文本消息
    Tool: Bash
    Steps:
      1. 模拟飞书消息事件 JSON
      2. 调用 adapter.receive_message(event)
      3. 验证返回的消息格式正确
    Expected Result: 消息被正确解析
    Evidence: .sisyphus/evidence/task-05-receive.txt

  Scenario: 发送文本消息
    Tool: Bash
    Steps:
      1. 调用 adapter.send_message(open_id, "Hello")
      2. 模拟飞书 API 返回成功
    Expected Result: 消息发送成功
    Evidence: .sisyphus/evidence/task-05-send.txt

  Scenario: 会话 ID 映射
    Tool: Bash
    Steps:
      1. 调用 adapter.get_conversation_id(open_id, "p2p")
      2. 验证返回格式为 feishu_p2p_{open_id}
    Expected Result: 正确的会话 ID
    Evidence: .sisyphus/evidence/task-05-session-id.txt
  ```

  **Commit**: YES (groups with 1-8)

---

- [x] 6. 消息幂等处理器实现 [quick]

  **What to do**:
  - 在 `adapter.py` 新建 `MessageDeduplicator` 类
  - 实现事件 ID 去重逻辑
  - 使用 `threading.Lock` 确保线程安全
  - 提供 `is_duplicate(event_id)` 方法检查是否已处理
  - 提供 `mark_processed(event_id)` 方法标记已处理
  - 实现清理逻辑（可选，定期清理过期记录）

  **Must NOT do**:
  - 不依赖外部存储（可选 Phase 2）
  - 不阻塞主线程
  - 不影响正常消息处理

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 简单的去重和锁逻辑
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 5, 7, 8)
  - **Blocks**: Task 7
  - **Blocked By**: Task 2

  **References**:
  - `src/llm_chat/storage.py` - 存储结构参考
  - Python threading 文档: https://docs.python.org/3/library/threading.html
  - 飞书事件重试文档: https://open.feishu.cn/document/ukTM7Y3-2/calculator-summary

  **Acceptance Criteria**:
  - [ ] `MessageDeduplicator` 类定义完整
  - [ ] 能正确检测重复事件
  - [ ] 使用锁保证线程安全
  - [ ] 清理逻辑能定期执行
  - [ ] 有单元测试覆盖

  **QA Scenarios**:
  ```
  Scenario: 重复事件处理
    Tool: Bash
    Steps:
      1. 创建 MessageDeduplicator 实例
      2. 第一次调用 process() - 应该返回 True
      3. 第二次调用 process() - 应该返回 False
    Expected Result: 第二次处理被跳过
    Evidence: .sisyphus/evidence/task-06-duplicate.txt

  Scenario: 清理过期记录
    Tool: Bash
    Steps:
      1. 添加旧记录并设置过期时间
      2. 调用 cleanup()
      3. 验证记录被删除
    Expected Result: 过期记录被清理
    Evidence: .sisyphus/evidence/task-06-cleanup.txt
  ```

  **Commit**: NO (part of Wave 2 commit)

---

- [x] 7. FeishuServer 长连接服务实现 [deep]

  **What to do**:
  - 在 `server.py` 新建 `FeishuServer` 类
  - 使用 `lark.ws.Client` 建立长连接
  - 注册事件处理器:
    - `im.message.receive_v1` - 接收消息
    - `im.chat.member.bot.added_v1` - 进群事件
  - 调用 `FeishuAdapter.handle_message()` 处理消息
  - 实现优雅关闭（stop 方法）
  - 添加健康检查端点（可选）
  - 实现重连逻辑
  - 实现错误处理

  **Must NOT do**:
  - 不在 `start()` 中阻塞（启动异步事件循环）
  - 不在事件处理器中执行耗时操作
  - 不忽略连接错误
  - 不在关闭时丢失消息

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: 需要处理长连接状态和异步事件
  - **Skills**: []
    - `librarian`: 查找 lark-oapi WebSocket 使用模式
      - Reason: 需要理解 SDK 的长连接 API

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 5, 6, 8)
  - **Blocks**: Task 9, 11
  - **Blocked By**: Task 5

  **References**:
  - `lark-oapi` SDK: `lark.ws.Client` - WebSocket 客户端
  - `src/llm_chat/frontends/feishu/adapter.py` - FeishuAdapter
  - 飞书 WebSocket 文档: https://open.feishu.cn/document/client-sdk/python/websocket
  - Python asyncio 文档: https://docs.python.org/3/library/asyncio.html

  **Acceptance Criteria**:
  - [ ] 能成功启动 WebSocket 连接
  - [ ] 能接收并处理消息事件
  - [ ] 能优雅处理断线重连
  - [ ] `stop()` 能正确关闭连接
  - [ ] 有单元测试覆盖
  - [ ] 能正确处理连接错误

  **QA Scenarios**:
  ```
  Scenario: WebSocket 连接成功
    Tool: Bash
    Steps:
      1. 创建 FeishuServer 实例
      2. 调用 start()
      3. 验证连接状态
    Expected Result: WebSocket 连接建立成功
    Evidence: .sisyphus/evidence/task-07-connect.txt

  Scenario: 断线重连
    Tool: Bash
    Steps:
      1. 模拟 WebSocket 断开
      2. 验证重连逻辑被触发
    Expected Result: 自动重连成功
    Evidence: .sisyphus/evidence/task-07-reconnect.txt

  Scenario: 消息接收
    Tool: Bash
    Steps:
      1. 模拟飞书发送消息事件
      2. 验证事件处理器被调用
    Expected Result: 消息被正确处理
    Evidence: .sisyphus/evidence/task-07-message.txt

  Scenario: 优雅关闭
    Tool: Bash
    Steps:
      1. 调用 stop()
      2. 验证连接被正确关闭
    Expected Result: 无异常退出
    Evidence: .sisyphus/evidence/task-07-stop.txt
  ```

  **Commit**: YES (groups with 1-8)

---

- [x] 8. 错误处理与重试机制实现 [unspecified-high]

  **What to do**:
  - 在 `error_handler.py` 定义统一错误处理
  - 定义 `FeishuError` 异常层级
  - 实现重试装饰器 `retry_on_exception`
  - 实现超时处理 `timeout_handler`
  - 实现错误日志记录
  - 在关键点添加错误处理

  **Must NOT do**:
  - 不吞没异常
  - 不无限重试
  - 不阻塞主线程
  - 不记录敏感信息

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: 需要健壮的错误处理逻辑
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 5, 6, 7)
  - **Blocks**: Task 7, 10
  - **Blocked By**: None

  **References**:
  - Python tenacity 文档: https://tenacity.readthedocs.io/en/stable/usage.html
  - `src/llm_chat/client.py` - 现有错误处理参考
  - 飞书错误码文档: https://open.feishu.cn/document/ukTM7Y3-2/calculator-summary

  **Acceptance Criteria**:
  - [ ] `FeishuError` 异常类定义完整
  - [ ] 重试装饰器实现
  - [ ] 超时处理实现
  - [ ] 错误日志格式统一
  - [ ] 有单元测试覆盖

  **QA Scenarios**:
  ```
  Scenario: 重试机制
    Tool: Bash
    Steps:
      1. 模拟 API 调用暂时失败
      2. 验证重试被触发
    Expected Result: 重试成功或达到最大次数后放弃
    Evidence: .sisyphus/evidence/task-08-retry.txt

  Scenario: 超时处理
    Tool: Bash
    Steps:
      1. 设置短超时时间
      2. 模拟慢操作
      3. 验证超时异常被抛出
    Expected Result: 正确的超时异常
    Evidence: .sisyphus/evidence/task-08-timeout.txt
  ```

  **Commit**: YES (groups with 1-8)

---

- [x] 9. CLI feishu 命令实现 [quick]

  **What to do**:
  - 在 `cli.py` 添加 `@click.command()` 装饰器 `feishu` 命令
  - 实现命令处理逻辑:
    - 加载飞书配置
    - 创建并启动 FeishuServer
    - 处理优雅退出

  **Must NOT do**:
  - 不阻塞主线程启动
  - 不在缺少配置时崩溃
  - 不忽略用户中断信号

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 简单的 CLI 添加
  - **Skills**: []
    - `librarian`: 查看 Click CLI 文档
      - Reason: 需要了解 Click 的命令定义方式

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Tasks 10, 11, 12)
  - **Blocks**: Task 14, 15
  - **Blocked By**: Task 7

  **References**:
  - `src/llm_chat/cli.py` - 现有 CLI 结构
  - Click 文档: https://click.palletsprojects.com/en/8.x/quickstart/
  - `src/llm_chat/frontends/feishu/server.py` - FeishuServer

  **Acceptance Criteria**:
  - [ ] `poetry run vermilion-bird feishu` 能启动
  - [ ] 缺少配置时显示友好错误信息
  - [ ] `--config` 参数能指定配置文件
  - [ ] Ctrl+C 能优雅退出
  - [ ] 有单元测试覆盖

  **QA Scenarios**:
  ```
  Scenario: 命令启动
    Tool: Bash
    Steps:
      1. poetry run vermilion-bird feishu --help
      2. 验证帮助信息显示
    Expected Result: 显示帮助信息
    Evidence: .sisyphus/evidence/task-09-cli-help.txt

  Scenario: 缺少配置
    Tool: Bash
    Steps:
      1. 不设置环境变量运行命令
      2. 验证错误信息
    Expected Result: 显示配置缺失错误
    Evidence: .sisyphus/evidence/task-09-cli-no-config.txt
  ```

  **Commit**: YES (groups with 5-12)

---

- [x] 10. PushService 主动推送实现 [unspecified-high]

  **What to do**:
  - 在 `push.py` 新建 `PushService` 类
  - 实现推送接口:
    - `push_to_user(open_id, message)` - 推送给用户
    - `push_to_group(chat_id, message)` - 推送给群聊
    - `broadcast(message)` - 广播给所有活跃会话
  - 实现定时任务支持（使用 APScheduler 或简单调度）
  - 实现外部触发 API 端点
  - 添加重试和错误处理

  **Must NOT do**:
  - 不实现复杂的调度 UI
  - 不存储推送历史（可选 Phase 2）
  - 不实现推送队列持久化

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: 需要设计推送 API 和调度逻辑
  - **Skills**: []
    - `librarian`: 查找 APScheduler 文档
      - Reason: 可能需要任务调度库

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Tasks 9, 11, 12)
  - **Blocks**: Task 14, 15
  - **Blocked By**: Task 5, 8

  **References**:
  - `src/llm_chat/frontends/feishu/adapter.py` - FeishuAdapter
  - APScheduler 文档: https://apscheduler.readthedocs.io/
  - 飞书消息 API: https://open.feishu.cn/document/server-docs/im-v1/message/create
  - `src/llm_chat/app.py` - App 类

  **Acceptance Criteria**:
  - [ ] 能推送给指定用户
  - [ ] 能推送给指定群聊
  - [ ] 外部 API 端点能接收推送请求
  - [ ] 有单元测试覆盖

  **QA Scenarios**:
  ```
  Scenario: 推送给用户
    Tool: Bash
    Steps:
      1. 调用 push_to_user("ou_test", "Hello")
      2. 验证消息发送成功
    Expected Result: 消息发送成功
    Evidence: .sisyphus/evidence/task-10-push-user.txt

  Scenario: 外部触发 API
    Tool: Bash (curl)
    Steps:
      1. curl -X POST http://localhost:8080/push -d '{"open_id":"ou_test","message":"Hello"}'
      2. 验证响应
    Expected Result: 200 OK
    Evidence: .sisyphus/evidence/task-10-api.txt
  ```

  **Commit**: YES (groups with 5-12)

---

- [x] 11. 与 App 集成 [deep]

---

**Commit**: YES (groups with 5-12)

---

- [x] 12. 日志与监控 [quick]

  **What to do**:
  - 使用 Python logging 模块
  - 定义日志格式和级别
  - 在关键点添加日志:
    - 连接建立/断开
    - 消息接收/发送
    - 错误发生
    - 推送触发
  - 添加健康检查日志

  **Must NOT do**:
  - 不实现复杂的监控系统
  - 不添加外部监控集成（可选 Phase 2）
  - 不记录敏感信息

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 简单的日志添加
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Tasks 9, 10, 11)
  - **Blocks**: Task 15
  - **Blocked By**: Task 7, 9

  **References**:
  - Python logging 文档: https://docs.python.org/3/library/logging.html
  - `src/llm_chat/` - 现有日志模式

  **Acceptance Criteria**:
  - [ ] 关键操作有日志记录
  - [ ] 日志格式统一
  - [ ] 不记录敏感信息
  - [ ] 有单元测试覆盖

  **QA Scenarios**:
  ```
  Scenario: 日志输出
    Tool: Bash
    Steps:
      1. 触发各种操作
      2. 检查日志输出
    Expected Result: 日志包含预期信息
    Evidence: .sisyphus/evidence/task-12-logging.txt
  ```

  **Commit**: YES (groups with 5-12)

---

- [x] 13. 单元测试 [unspecified-high]

  **What to do**:
  - 创建 `tests/test_feishu_adapter.py` 测试 FeishuAdapter
  - 创建 `tests/test_feishu_server.py` 测试 FeishuServer
  - 创建 `tests/test_feishu_push.py` 测试 PushService
  - 创建 `tests/test_feishu_mapper.py` 测试 SessionMapper
  - Mock 飞书 API 和 LLM 调用
  - 确保测试覆盖率 ≥ 80%

  **Must NOT do**:
  - 不在测试中调用真实 API
  - 不跳过失败的测试
  - 不使用不稳定的 Mock

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: 需要全面的测试覆盖
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4 (with Tasks 14, 15)
  - **Blocks**: Task 14
  - **Blocked By**: Task 11

  **References**:
  - `tests/test_client.py` - 现有测试参考
  - `tests/test_conversation.py` - 现有测试参考
  - pytest 文档: https://docs.pytest.org/
  - pytest-asyncio 文档: https://pytest-asyncio.readthedocs.io/

  **Acceptance Criteria**:
  - [ ] 所有新模块有对应测试文件
  - [ ] `poetry run pytest tests/test_feishu*.py` 通过
  - [ ] 测试覆盖率 ≥ 80%

  **QA Scenarios**:
  ```
  Scenario: 测试运行
    Tool: Bash
    Steps:
      1. poetry run pytest tests/test_feishu*.py -v
      2. 验证所有测试通过
    Expected Result: 0 failed
    Evidence: .sisyphus/evidence/task-13-tests.txt
  ```

  **Commit**: YES (groups with 13-15)

---

- [x] 14. 集成测试 [unspecified-high]

  **What to do**:
  - 创建 `tests/test_feishu_integration.py`
  - 测试完整的消息流转:
    - 飞书消息 → Adapter → App → LLM → 响应 → 飞书
  - 测试会话持久化
  - 测试主动推送
  - 使用 Mock 但模拟真实流程

  **Must NOT do**:
  - 不在测试中调用真实 API
  - 不依赖外部服务

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: 需要端到端测试
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4 (with Tasks 13, 15)
  - **Blocks**: Final Verification
  - **Blocked By**: Task 11, 13

  **References**:
  - `tests/test_feishu_adapter.py` - 单元测试参考
  - pytest 文档: https://docs.pytest.org/

  **Acceptance Criteria**:
  - [ ] 完整消息流转测试通过
  - [ ] 会话持久化测试通过
  - [ ] 主动推送测试通过

  **QA Scenarios**:
  ```
  Scenario: 集成测试运行
    Tool: Bash
    Steps:
      1. poetry run pytest tests/test_feishu_integration.py -v
      2. 验证所有测试通过
    Expected Result: 0 failed
    Evidence: .sisyphus/evidence/task-14-integration.txt
  ```

  **Commit**: YES (groups with 13-15)

---

- [x] 15. 文档更新 [writing]

  **What to do**:
  - 更新 `README.md` 添加飞书集成说明
  - 更新 `config.example.yaml` 添加完整配置示例
  - 更新 `src/llm_chat/frontends/AGENTS.md`（如果存在）
  - 添加飞书集成的使用文档

  **Must NOT do**:
  - 不添加过多细节（保持简洁）
  - 不重复官方文档内容

  **Recommended Agent Profile**:
  - **Category**: `writing`
    - Reason: 文档更新
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 4 (with Tasks 13, 14)
  - **Blocks**: Final Verification
  - **Blocked By**: Task 9, 12

  **References**:
  - `README.md` - 现有文档结构
  - `config.example.yaml` - 现有配置示例

  **Acceptance Criteria**:
  - [ ] README.md 包含飞书集成说明
  - [ ] config.example.yaml 包含完整飞书配置
  - [ ] 使用文档清晰易懂

  **QA Scenarios**:
  ```
  Scenario: 文档检查
    Tool: Bash
    Steps:
      1. grep -q "feishu" README.md
      2. grep -q "feishu:" config.example.yaml
    Expected Result: 找到飞书相关内容
    Evidence: .sisyphus/evidence/task-15-docs.txt
  ```

  **Commit**: YES (groups with 13-15)

---

## Final Verification Wave (MANDATORY)

> 4 review agents run in PARALLEL. ALL must APPROVE. Present consolidated results to user and get explicit "okay" before completing.

- [ ] F1. **Plan Compliance Audit** — `oracle`
  Read the plan end-to-end. For each "Must Have": verify implementation exists. For each "Must NOT Have": search codebase for forbidden patterns. Check evidence files exist. Compare deliverables against plan.
  Output: `Must Have [N/N] | Must NOT Have [N/N] | Tasks [N/N] | VERDICT: APPROVE/REJECT`

- [ ] F2. **Code Quality Review** — `unspecified-high`
  Run type checks + linter + tests. Review all changed files for: type safety, error handling, code smells. Check AI slop patterns.
  Output: `Build [PASS/FAIL] | Lint [PASS/FAIL] | Tests [N pass/N fail] | Files [N clean/N issues] | VERDICT`

- [ ] F3. **Real Manual QA** — `unspecified-high`
  Start from clean state. Execute EVERY QA scenario from EVERY task. Test cross-task integration. Save evidence to `.sisyphus/evidence/final-qa/`.
  Output: `Scenarios [N/N pass] | Integration [N/N] | Edge Cases [N tested] | VERDICT`

- [ ] F4. **Scope Fidelity Check** — `deep`
  For each task: read "What to do", read actual diff. Verify 1:1 — everything in spec was built, nothing beyond spec was built. Check "Must NOT do" compliance.
  Output: `Tasks [N/N compliant] | Contamination [CLEAN/N issues] | Unaccounted [CLEAN/N files] | VERDICT`

---

## Security Measures (安全措施详细说明)

> **必须在 Wave 2 完成所有安全模块，确保核心功能实现时已具备安全防护。**

### 新增安全任务 (Task 5-8)

| Task | 名称 | 优先级 | 说明 |
|------|------|--------|------|
| **5** | SignatureVerifier ✅ | 高 | 飞书签名验证，防伪造请求 |
| **6** | RateLimiter ✅ | 中 | 限流，防滥用（滑动窗口算法） |
| **7** | AccessController ✅ | 低 | 访问控制（白名单/黑名单） |
| **8** | MessageDeduplicator ✅ | 高 | 消息幂等，防重复处理 |

### 安全模块实现规范

**文件**: `src/llm_chat/frontends/feishu/security.py`

```python
# security.py 结构
from dataclasses import dataclass
from typing import Optional, Dict, Set
import hmac
import hashlib
import time
from collections import defaultdict
from datetime import datetime, timedelta
import threading

@dataclass
class SecurityConfig:
    """安全配置"""
    rate_limit: int = 10  # 每分钟最大请求数
    rate_window: int = 60  # 限流窗口（秒）
    access_mode: str = "open"  # open/whitelist/blacklist
    whitelist: Set[str] = None
    blacklist: Set[str] = None
    signature_enabled: bool = True

class SignatureVerifier:
    """飞书签名验证器"""
    def verify(self, timestamp: str, nonce: str, signature: str, body: str, secret: str) -> bool:
        # 验证时间戳（5分钟有效期）
        # 计算 HMAC-SHA256 签名
        # 使用 hmac.compare_digest 防止时序攻击
        pass

class RateLimiter:
    """限流器（滑动窗口算法）"""
    def __init__(self, max_requests: int = 10, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window = timedelta(seconds=window_seconds)
        self.requests = defaultdict(list)
        self.lock = threading.Lock()
    
    def is_allowed(self, user_id: str) -> bool:
        # 滑动窗口限流
        pass

class AccessController:
    """访问控制器"""
    def is_allowed(self, user_id: str, chat_id: str) -> bool:
        # 白名单/黑名单检查
        pass

class MessageDeduplicator:
    """消息幂等处理器"""
    def __init__(self, max_size: int = 10000):
        self.processed = {}
        self.lock = threading.Lock()
    
    def is_duplicate(self, event_id: str) -> bool:
        # 检查是否已处理
        pass
    
    def cleanup(self, max_age_seconds: int = 3600):
        # 清理过期记录
        pass
```

### 配置示例 (config.yaml)

```yaml
feishu:
  enabled: true
  app_id: "${FEISHU_APP_ID}"
  app_secret: "${FEISHU_APP_SECRET}"
  
  # 安全配置
  security:
    # 签名验证（生产环境必须启用）
    signature_enabled: true
    
    # 限流配置
    rate_limit: 10        # 每分钟最大请求数
    rate_window: 60       # 限流窗口（秒）
    
    # 访问控制
    access_mode: "open"   # open / whitelist / blacklist
    whitelist: []         # 白名单用户/群聊 ID
    blacklist: []         # 黑名单用户/群聊 ID
```

### 安全检查清单

在 Task 9 (FeishuAdapter) 实现时，必须集成以下安全检查：

```
消息处理流程:
1. 接收飞书事件
2. [签名验证] - 使用 SignatureVerifier
3. [限流检查] - 使用 RateLimiter.is_allowed()
4. [访问控制] - 使用 AccessController.is_allowed()
5. [幂等检查] - 使用 MessageDeduplicator.is_duplicate()
6. 处理消息
7. 标记已处理 - MessageDeduplicator.mark_processed()
```

### 更新后的任务依赖

```
Wave 1 (Task 1-4): 配置 + 数据模型
    ↓
Wave 2 (Task 5-8): 安全模块 [新增]
    ↓
Wave 3 (Task 9-12): 核心功能（依赖安全模块）
    ↓
Wave 4 (Task 13-16): 集成 + CLI
    ↓
Wave 5 (Task 17-19): 测试 + 文档
```

### 安全测试要求

在 Task 17-18 (测试) 中，必须包含以下安全测试：

- [ ] 签名验证测试（有效/无效/过期签名）
- [ ] 限流测试（正常/超限请求）
- [ ] 访问控制测试（白名单/黑名单）
- [ ] 幂等测试（重复消息处理）
- [ ] 并发安全测试（多线程场景）

---

## Security Measures (安全措施详细说明)

> **必须在 Wave 2 完成所有安全模块，确保核心功能实现时已具备安全防护。**
> **安全模块文件**: `src/llm_chat/frontends/feishu/security.py`

### 安全组件

| 组件 | 类名 | 职责 | 优先级 |
|------|------|------|--------|
| SignatureVerifier | 签名验证器 | 验证飞书请求签名，防止伪造 | 高 |
| RateLimiter | 限流器 | 基于用户/群聊的限流 | 中 |
| AccessController | 访问控制器 | 白名单/黑名单访问控制 | 低 |
| MessageDeduplicator | 幂等处理器 | 防止重复消息处理 | 高 |

### 宺议代码结构

```python
# security.py
import hmac
import hashlib
import time
from collections import defaultdict
from datetime import datetime, timedelta
import threading
from typing import Optional, Dict, Set
from dataclasses import dataclass

@dataclass
class SecurityConfig:
    """安全配置"""
    encrypt_key: str = ""  # 签名加密密钥
    rate_limit: int = 10  # 每分钟最大请求数
    rate_window: int = 60  # 限流窗口（秒）

class SignatureVerifier:
    """飞书签名验证器"""
    
    def __init__(self, encrypt_key: str):
        self.encrypt_key = encrypt_key
    
    def verify(self, timestamp: str, nonce: str, 
              signature: str, body: str) -> bool:
        """验证签名"""
        # 防重放攻击：时间戳不能超过 5 分钟
        if abs(time.time() - int(timestamp)) > 300:
            return False
        
        # 计算签名
        sign_base = timestamp + nonce + self.encrypt_key
        expected = hmac.new(
            self.encrypt_key.encode(),
            body.encode(),
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(signature, expected)

class RateLimiter:
    """基于滑动窗口的限流器"""
    
    def __init__(self, max_requests: int = window_seconds: int):
        self.max_requests = max_requests
        self.window = timedelta(seconds=window_seconds)
        self.requests: Dict[str, list] = defaultdict(list)
        self.lock = threading.Lock()
    
    def is_allowed(self, user_id: str) -> bool:
        """检查是否允许请求"""
        with self.lock:
            now = datetime.now()
            # 清理过期记录
            self.requests[user_id] = [
                t for t in self.requests[user_id]
                if now - t < self.window
            ]
            
            if len(self.requests[user_id]) >= self.max_requests:
                return False
            
            
            self.requests[user_id].append(now)
            return True

class AccessController:
    """访问控制器"""
    
    def __init__(self, mode: str, 
                 whitelist: Optional[Set[str]] = None,
                 blacklist: Optional[Set[str]] = None):
        self.mode = mode
        self.whitelist = whitelist or set()
        self.blacklist = blacklist or set()
    
    def is_allowed(self, user_id: str, chat_id: str) -> bool:
        """检查访问权限"""
        if self.mode == "whitelist":
            return user_id in self.whitelist or chat_id in self.whitelist
        elif self.mode == "blacklist":
            return user_id not in self.blacklist and chat_id not in self.blacklist
        return True  # open 模式

class MessageDeduplicator:
    """消息幂等处理器"""
    
    def __init__(self, max_size: int = 10000, ttl: int = 3600):
        self.max_size = max_size
        self.ttl = ttl
        self.processed: Dict[str, float] = {}
        self.lock = threading.Lock()
    
    def is_duplicate(self, event_id: str) -> bool:
        """检查是否重复"""
        with self.lock:
            if event_id in self.processed:
                return True
            return False
    
    def mark_processed(self, event_id: str) -> None:
        """标记已处理"""
        with self.lock:
                self.processed[event_id] = time.time()
                # 清理超容量记录
                if len(self.processed) > self.max_size:
                    self._cleanup()
    
    def _cleanup(self) -> None:
        """清理过期记录"""
        now = time.time()
        expired = [
            k for k, v in self.processed.items()
            if now - v > self.ttl
        ]
        for k in expired:
            del self.processed[k]
```

### 配置示例 (config.yaml)

```yaml
feishu:
  app_id: "cli_xxxxx"
  app_secret: "xxxxx"
  enabled: true
  
  security:
    encrypt_key: "your-encrypt-key"  # 签名加密密钥
    rate_limit: 10  # 每分钟最大请求数
    rate_window: 60  # 限流窗口（秒）
    access_mode: "open"  # open/whitelist/blacklist
    whitelist: []  # 白名单用户/群聊 ID
    blacklist: []  # 黑名单用户/群聊 ID
```

### 安全测试要求

- [ ] 签名验证测试（有效/无效/过期签名）
- [ ] 限流测试（正常/超限请求）
- [ ] 访问控制测试（白名单/黑名单模式）
- [ ] 幂等测试（重复消息处理）
- [ ] 并发安全测试（多线程场景）

---

## Commit Strategy

- **Task 5-8**: `feat(feishu): implement security module (signatures + rate limiting + access control)`
- **Task 9-12**: `feat(feishu): implement FeishuAdapter and server`
- **Task 13-16**: `feat(feishu): add CLI command and push service`
- **Task 17-19**: `test(feishu): add unit and integration tests and and - **Task 5-8**: `feat(feishu): implement security module (signatures + rate limiting + access control)`
- **Task 9-12**: `feat(feishu): implement FeishuAdapter and server`
- **Task 13-16**: `feat(feishu): add CLI command and push service`
- **Task 17-19**: `test(feishu): add unit, integration tests (security tests included)

---

## Success Criteria

### Verification Commands
```bash
# 安装依赖
poetry install

# 启动飞书 Bot（需要配置 FEISHU_APP_ID 和 FEISHU_APP_SECRET）
poetry run vermilion-bird feishu

# 运行测试
poetry run pytest tests/test_feishu*.py -v

# 代码检查
poetry run black --check src/llm_chat/frontends/feishu/
poetry run flake8 src/llm_chat/frontends/feishu/
```

### Final Checklist
- [ ] All "Must Have" present
- [ ] All "Must NOT Have" absent
- [ ] All tests pass
- [ ] Bot can receive and respond to text messages
- [ ] Push service can send messages proactively
- [ ] Configuration documented in config.example.yaml
- [ ] **安全措施生效**:
  - [ ] 签名验证拒绝伪造请求
  - [ ] 限流阻止滥用行为
  - [ ] 访问控制按白名单/黑名单过滤
  - [ ] 幂等处理防止重复消息
- [ ] **安全测试通过**:
  - [ ] 有效签名验证测试
  - [ ] 限流测试
  - [ ] 访问控制测试
  - [ ] 并发安全测试
