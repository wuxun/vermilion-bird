# Vermilion Bird - 项目知识库

**生成时间**: 2026-03-20
**Commit**: 861a97c
**Branch**: main

## 概述

大模型对话客户端，支持多种 API 协议（OpenAI/Anthropic/Gemini）和 MCP 工具调用。核心栈：Python 3.9+ / Poetry / PyQt6 / MCP。

## 项目结构

```
vermilion-bird/
├── src/llm_chat/           # 主包
│   ├── client.py           # LLM 客户端 API
│   ├── config.py           # 配置管理（YAML/环境变量/CLI）
│   ├── app.py              # 应用核心协调器
│   ├── cli.py              # CLI 入口（Click）
│   ├── conversation.py     # 会话管理
│   ├── storage.py          # SQLite 持久化
│   ├── protocols/          # 协议适配器（见子目录 AGENTS.md）
│   ├── frontends/          # CLI/GUI 前端（见子目录 AGENTS.md）
│   ├── mcp/                # MCP 工具集成（见子目录 AGENTS.md）
│   ├── memory/             # 多层记忆系统（见子目录 AGENTS.md）
│   ├── skills/             # 技能插件（web_search, calculator 等）
│   ├── tools/              # 工具基础设施
│   └── utils/              # 工具类（token 计数等）
├── tests/                  # pytest 测试
├── skills/                 # 外部技能模板
├── config.yaml             # 运行时配置
└── pyproject.toml          # Poetry 打包配置
```

## 快速定位

| 任务 | 位置 | 说明 |
|------|------|------|
| 添加新协议 | `src/llm_chat/protocols/` | 继承 BaseProtocol，注册到 PROTOCOL_MAP |
| 添加新技能 | `src/llm_chat/skills/` | 继承 BaseSkill，实现 get_tools() |
| 修改配置加载 | `src/llm_chat/config.py` | Config.from_yaml() 处理优先级 |
| 修改 GUI | `src/llm_chat/frontends/gui.py` | PyQt6 实现 |
| 修改 CLI | `src/llm_chat/frontends/cli.py` | 富文本终端输出 |
| MCP 集成 | `src/llm_chat/mcp/` | 工具发现/调用 |
| 记忆系统 | `src/llm_chat/memory/` | 短期/中期/长期记忆 |

## 代码地图

| 符号 | 类型 | 位置 | 职责 |
|------|------|------|------|
| `LLMClient` | Class | client.py | 对外 API，chat/chat_stream/chat_with_tools |
| `Config` | Class | config.py | 全局配置，from_yaml() 加载 |
| `App` | Class | app.py | 应用协调器，连接 client/storage/frontend |
| `BaseProtocol` | Class | protocols/base.py | 协议基类，工具调用支持 |
| `BaseFrontend` | Class | frontends/base.py | 前端基类 |
| `MCPManager` | Class | mcp/manager.py | MCP 服务器管理 |
| `MemoryStorage` | Class | memory/storage.py | 记忆持久化 |
| `BaseSkill` | Class | skills/base.py | 技能基类 |

## 约定

### 打包与依赖
- 使用 Poetry（`pyproject.toml`），无 setup.py
- 开发依赖：pytest, black, flake8
- 入口点：`vermilion-bird = "llm_chat.cli:main"`

### 类型注解
- 广泛使用 typing 模块（Optional, List, Dict, Any）
- Pydantic 模型用于配置验证

### 导入顺序
- 标准库 → 第三方库 → 本地导入（组间空行）

### 文档
- 中文 docstrings，部分模块使用 Google 风格

### 测试
- 测试文件：`tests/test_*.py`
- 无 conftest.py/pytest.ini，使用默认 pytest 发现
- 使用 `setup_module/teardown_module` 进行环境清理

## 反模式（本项目）

 
 ### 安全警告
- **禁止**在用户输入上使用 `eval()`
- 位置：`src/llm_chat/skills/calculator/skill.py`
- 替代方案：使用 ast 白名单或实现安全的表达式解析器

 ### 代码风格
- 缺少显式的 black/flake8 配置（行长等）
- 建议在 pyproject.toml 添加 `[tool.black]` 和 `[tool.flake8]`

## 常用命令

```bash
# 安装
poetry install

# 运行 CLI
poetry run vermilion-bird

# 运行 GUI
poetry run vermilion-bird chat --gui

# 测试
poetry run pytest

# 代码格式化
poetry run black .
poetry run flake8
```

## 配置

### 环境变量（优先级最高）
```bash
LLM_BASE_URL     # API 基础 URL
LLM_MODEL        # 模型名称
LLM_API_KEY      # API 密钥
LLM_PROTOCOL     # openai/anthropic/gemini
```

### config.yaml
```yaml
llm:
  base_url: "https://api.openai.com/v1"
  model: "gpt-3.5-turbo"
  protocol: "openai"
enable_tools: true
memory:
  enabled: true
  storage_dir: "~/.vermilion-bird/memory"
```

## 子目录文档

- [protocols/](src/llm_chat/protocols/AGENTS.md) - 协议适配器
- [mcp/](src/llm_chat/mcp/AGENTS.md) - MCP 工具集成
- [frontends/](src/llm_chat/frontends/AGENTS.md) - CLI/GUI 前端
- [memory/](src/llm_chat/memory/AGENTS.md) - 记忆系统

## 注意事项

- 记忆文件存储在 `~/.vermilion-bird/memory/`
- 会话数据存储在 `.vb/vermilion_bird.db`（SQLite）
- 技能配置通过 `config.yaml` 的 `skills` 节点控制
- MCP 服务器配置在 `config.yaml` 的 `mcp.servers` 节点
