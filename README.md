# Vermilion Bird

[![Build & Package](https://github.com/your-username/vermilion-bird/actions/workflows/build.yml/badge.svg)](https://github.com/your-username/vermilion-bird/actions/workflows/build.yml)

大模型对话客户端，支持多协议（OpenAI/Anthropic/Gemini）、MCP 工具调用、容器化沙箱执行、意图识别路由、事件驱动触发器、多层记忆系统。

## 功能特性

- **多协议支持** — OpenAI、Anthropic Claude、Google Gemini 及兼容服务（DeepSeek、Ollama、智谱 GLM 等）
- **MCP 工具集成** — 通过 Model Context Protocol 连接外部工具（Tavily/Brave 搜索、天气、文件系统等）
- **三层意图识别** — 快捷指令直返 / 模式匹配路由 / 模型映射，节省 30-50% API 费用
- **多层记忆系统** — 短期/中期/长期记忆 + SOUL 人格设定，AI 持续了解你
- **容器化沙箱** — Docker → bwrap → 白名单三级回退，安全执行 Shell 命令
- **定时任务调度** — APScheduler + Webhook 事件驱动触发器，支持飞书通知
- **飞书（Lark）集成** — WebSocket 实时消息，自动重连 + 事件去重
- **图形界面 (PyQt6)** — 对话、模型切换、MCP 配置、技能管理、定时任务面板
- **执行与审批中心** — Run/事件持久化、高风险动作审批、重启恢复与副作用人工对账
- **任务与交付物** — 以用户目标聚合多次执行、审批和最终报告/文件，支持 CLI 与 GUI
- **会话管理** — SQLite（WAL + FTS5）持久化，支持中文分词搜索
- **子 Agent 委托** — spawn_subagent 动态创建子对话，Workflow 引擎编排多工具
- **API Key 安全存储** — 系统密钥环（macOS Keychain / Linux Secret Service）
- **可观测性** — Span/Counter/Gauge 埋点 + 健康检查（DB/LLM/Disk/MCP/Services）
- **一键打包** — PyInstaller 构建独立 `.app`（双击启动 GUI）

## 快速开始

### 安装

```bash
# 方式一：Poetry（推荐开发）
git clone https://github.com/your-username/vermilion-bird.git
cd vermilion-bird
poetry install -E all

# 方式二：下载打包的 .app（macOS 用户）
# 从 Releases 页面下载 Vermilion Bird.app，双击启动
```

核心 CLI 可只安装基础依赖；按需启用适配器：

```bash
pip install vermilion-bird
pip install 'vermilion-bird[gui]'               # PyQt6
pip install 'vermilion-bird[feishu]'            # Lark SDK
pip install 'vermilion-bird[semantic-knowledge]' # numpy + embeddings
pip install 'vermilion-bird[all]'                # 完整桌面能力
```

### 配置

复制配置模板并编辑：

```bash
cp config.example.yaml config.yaml
# 编辑 config.yaml，填入你的 API Key
```

最小配置：

```yaml
llm:
  base_url: "https://api.openai.com/v1"
  model: "gpt-4o"
  api_key: "sk-xxx"          # 或使用 keyring 安全存储
  protocol: "openai"
```

> API Key 安全存储：`vermilion-bird keyring set openai` 输入密码，然后配置 `api_key: "keyring:openai/default"`

### 启动

```bash
# CLI 模式
poetry run vermilion-bird chat

# GUI 模式
poetry run vermilion-bird chat --gui

# 飞书服务
poetry run vermilion-bird feishu

# 创建并执行持久化任务
poetry run vermilion-bird task start "调研三个 Agent 框架并形成报告"
poetry run vermilion-bird task list
```

GUI 顶栏的“任务”按钮（或 `Ctrl+Shift+T`）打开面向用户目标和交付物的任务中心；
`🧭` 按钮（或 `Ctrl+Shift+R`）打开高级“执行与审批中心”。“运行记录”
页可按类型和状态筛选并查看完整事件时间线；“审批”页集中展示待执行动作的风险、
能力、影响和参数，只有明确批准后才会执行。待审批动作和历史 Run 均保存在 SQLite
中。“副作用对账”页集中处理崩溃窗口内无法确认结果的外部操作，要求填写审计说明，
并可将 Outbox、审批记录和来源 Run 可恢复地收敛为成功或失败。副作用工具由 LangGraph
持久化到审批 interrupt，应用重启后仍可继续批准或拒绝；
Chat 与普通可恢复工作流可从 SQLite checkpoint 重试、恢复或重放；Scheduler、
Webhook 和 Proactive 任务也通过同一 Run Dispatcher 管理。Chat 消息写入带执行幂等键，
恢复节点时不会重复保存同一轮消息。

### 打包独立应用

```bash
# 需要 macOS + Python 3.12/3.13；依赖安装在隔离的 .venv-build
./build.sh
# 产物同时包含应用、Release ZIP 和 SHA-256 校验文件
# dist/Vermilion Bird.app
# dist/Vermilion-Bird-macOS-arm64.zip
# dist/Vermilion-Bird-macOS-arm64.zip.sha256
open "dist/Vermilion Bird.app"
```

发布依赖由 `requirements-build.in` 声明并固定在 `requirements-build.lock`。更新依赖时
应使用 Python 3.12 按输入文件顶部命令重新生成锁文件，并将二者一同提交。

## 支持的协议

| 协议 | 适用平台 | 工具调用 |
|------|----------|----------|
| **openai** | OpenAI、DeepSeek、Ollama、vLLM、智谱 GLM | ✅ Function Calling |
| **anthropic** | Claude 系列 | ✅ Tool Use |
| **gemini** | Google Gemini | ✅ Function Declarations |

## 配置参考

完整配置见 [`config.example.yaml`](config.example.yaml)。

### 主要配置段

| 节点 | 说明 |
|------|------|
| `llm` | 模型连接（base_url / protocol / api_key / 代理） |
| `mcp` | MCP 服务器列表（stdio / SSE） |
| `tools` | 工具执行参数 + 意图识别 + 模型路由 |
| `memory` | 多层记忆（short / mid / long / soul） |
| `context` | 上下文压缩与缓存 |
| `scheduler` | 定时任务 + Webhook 端口 |
| `skills` | 各技能开关与参数 |
| `feishu` | 飞书应用配置 |
| `log_file` | 日志文件路径（默认 `~/.vermilion-bird/app.log`） |

### 多模型路由

```yaml
llm:
  model: "gpt-4o-mini"             # 默认模型（小/便宜）
tools:
  enable_intent: true
  intent_model_map:
    small: "gpt-4o-mini"           # 问候/简单问答
    medium: "deepseek-chat"        # 常规任务（$0.07/1M tokens）
    large: "gpt-4o"                # 复杂推理/代码
```

## CLI 命令

```bash
vermilion-bird chat [--gui] [--model ...]     # 启动对话
vermilion-bird feishu                          # 启动飞书服务
vermilion-bird keyring set <username>           # 安全存储 API Key
vermilion-bird memory status                   # 查看记忆状态
vermilion-bird schedule list                   # 查看定时任务
vermilion-bird skills list                     # 查看技能列表
vermilion-bird search <query>                  # 全文搜索历史对话
```

## 项目结构

```
src/llm_chat/
├── app.py              # 应用核心协调器
├── chat_core.py        # 对话引擎（意图→记忆→压缩→LLM→工具→持久化）
├── cli/                # CLI 入口（Click 命令组）
├── client/             # LLM 客户端（chat/stream/tools/generate）
├── config.py           # Pydantic 配置管理（YAML/环境变量/CLI）
├── conversation.py     # 会话管理 + FTS5 搜索
├── storage/            # SQLite 单例（WAL + 迁移 + CRUD）
├── runtime/            # Run 生命周期、事件流、能力策略与动作审批
├── protocols/          # 协议适配器（openai/anthropic/gemini）
├── frontends/          # 用户界面（CLI / PyQt6 GUI / 飞书）
├── mcp/                # MCP 客户端（stdio/SSE + 后台管理）
├── scheduler/          # APScheduler + Webhook 事件触发器
├── memory/             # 四层记忆系统（提取/压缩/去重/进化）
├── context/            # 三级上下文压缩 + SQLite 缓存
├── skills/             # 10+ 内置技能（shell/文件/搜索/计算/定时...）
├── tools/              # 工具注册表 + 并行执行器
├── intent/             # 三层意图识别路由器
├── services/           # 业务服务层
└── utils/              # Token 计数 / 安全存储 / 可观测性
```

## GitHub Actions 自动打包

CI 会先在 Python 3.10、3.12、3.13 上执行编译和完整测试，再以 Python 3.12 构建
macOS arm64 发布包。推送到 `main` 分支或打 tag 会自动运行：

```bash
git tag v0.0.1
git push origin v0.0.1
```

产物在 Actions 页面可下载，tag 触发时会上传到 Release 附件。

## 开发

```bash
# 安装开发依赖
poetry install

# 测试
poetry run pytest

# 代码格式化
poetry run black .

# 代码检查
poetry run flake8
```

## 许可证

MIT
