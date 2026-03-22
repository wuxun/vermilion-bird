# Vermilion Bird - 依赖安装指南

本文档提供多种方式安装 Vermilion Bird 项目依赖。

---

## 📦 方式一：使用 Poetry（推荐）

### 前提条件
- Python 3.9 或更高版本
- Poetry 已安装（`pip install poetry`）

### 安装步骤

```bash
# 进入项目目录
cd /path/to/vermilion-bird

# 安装所有依赖
poetry install

# 激活虚拟环境
poetry shell
```

### 验证安装

```bash
# 检查 lark-oapi 是否安装
poetry show lark-oapi

# 应该显示类似输出：
# name         : lark-oapi
# version      : 1.0.0
# description  : Lark Open API Python SDK
```

---

## 📦 方式二：使用 pip（备选方案）

### 前提条件
- Python 3.9 或更高版本
- pip 已安装

### 安装步骤

```bash
# 进入项目目录
cd /path/to/vermilion-bird

# 安装所有依赖
pip install -r requirements.txt

# 或逐个安装关键依赖
pip install pydantic pydantic-settings pyyaml
pip install requests httpx httpx-sse tiktoken
pip install lark-oapi  # Feishu 集成必需
pip install click
pip install PyQt6
pip install markdown
pip install mcp
```

### 验证安装

```bash
# 检查 lark-oapi 是否安装
pip show lark-oapi

# 应该显示类似输出：
# Name: lark-oapi
# Version: 1.0.0
# Summary: Lark Open API Python SDK
```

---

## 📦 方式三：开发依赖安装（可选）

如果需要运行测试或代码格式化：

### 使用 Poetry

```bash
# 安装开发依赖
poetry install --with dev

# 包含：
# - pytest, pytest-cov
# - black, flake8
```

### 使用 pip

```bash
# 安装开发依赖
pip install pytest pytest-cov black flake8 playwright
```

---

## 🔑 飞书集成关键依赖

### lark-oapi（必需）

```bash
# 使用 Poetry
poetry install lark-oapi

# 使用 pip
pip install lark-oapi
```

**版本要求**: `^1.0.0` (即 1.0.0 或更高版本，但低于 2.0.0)

**作用**: 提供飞书 WebSocket 连接和 API 调用功能

---

## ⚠️ 常见问题

### 1. Poetry 安装失败

**问题**: `poetry install` 报错

**解决方案**:
```bash
# 更新 Poetry 版本
pip install --upgrade poetry

# 清除缓存
poetry cache clear pypi --all

# 重新安装
poetry install
```

### 2. lark-oapi 安装失败

**问题**: `pip install lark-oapi` 报错

**解决方案**:
```bash
# 尝试使用国内镜像源
pip install lark-oapi -i https://pypi.tuna.tsinghua.edu.cn/simple

# 或使用清华镜像
pip install lark-oapi -i https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple/
```

### 3. PyQt6 安装问题

**问题**: PyQt6 安装失败

**解决方案**:
```bash
# macOS
brew install pyqt6

# Linux (Ubuntu/Debian)
sudo apt-get install python3-pyqt6

# Windows
pip install pyqt6-tools
```

### 4. 权限错误

**问题**: 安装时提示权限不足

**解决方案**:
```bash
# 使用虚拟环境（推荐）
python -m venv venv
source venv/bin/activate  # Linux/macOS
# venv\Scripts\activate  # Windows
pip install -r requirements.txt

# 或使用 --user 参数
pip install --user -r requirements.txt
```

---

## ✅ 验证安装成功

### 检查关键依赖

```bash
# Python 版本
python --version  # 应该 >= 3.9

# 检查所有依赖
pip list | grep -E "pydantic|lark-oapi|httpx|PyQt6|click|pytest"

# 或使用 Poetry
poetry show | grep -E "pydantic|lark-oapi|httpx|PyQt6|click|pytest"
```

### 运行测试

```bash
# 使用 Poetry
poetry run pytest tests/test_feishu*.py -v

# 使用 pip（需要先激活虚拟环境）
pytest tests/test_feishu*.py -v
```

---

## 📝 环境变量配置（可选）

安装依赖后，可以通过环境变量配置飞书集成：

```bash
# 飞书配置
export FEISHU_APP_ID="cli_xxxxx"
export FEISHU_APP_SECRET="xxxxx"
export FEISHU_ENABLED="true"

# LLM 配置
export LLM_BASE_URL="https://api.openai.com/v1"
export LLM_MODEL="gpt-3.5-turbo"
export LLM_API_KEY="your-api-key"
export LLM_PROTOCOL="openai"
```

---

## 🚀 快速开始

### 1. 安装依赖

```bash
# 推荐：使用 Poetry
poetry install

# 备选：使用 pip
pip install -r requirements.txt
```

### 2. 配置飞书

```bash
# 创建配置文件
cp config.example.yaml config.yaml

# 编辑配置，填入飞书凭据
vim config.yaml
```

### 3. 启动服务

```bash
# 启动飞书 Bot
poetry run vermilion-bird feishu

# 或使用 pip（需要虚拟环境）
vermilion-bird feishu
```

---

## 📊 依赖清单

### 核心依赖（必需）
- ✅ pydantic (>=2.5.0)
- ✅ pydantic-settings (>=2.1.0)
- ✅ pyyaml (>=6.0.0)
- ✅ requests (>=2.31.0)
- ✅ httpx (>=0.27.0)
- ✅ httpx-sse (>=0.4.0)
- ✅ tiktoken (>=0.7.0)
- ✅ lark-oapi (>=1.0.0) - **飞书集成必需**

### CLI 依赖（必需）
- ✅ click (>=8.1.7)

### GUI 依赖（可选）
- ✅ PyQt6 (>=6.6.0)

### 其他依赖
- ✅ markdown (>=3.5.0)
- ✅ mcp (>=1.0.0)
- ✅ duckduckgo-search (>=6.0.0)
- ✅ ddgs (>=9.0.0)
- ✅ beautifulsoup4 (>=4.12.0)

### 开发依赖（测试/格式化）
- ✅ pytest (>=7.4.0)
- ✅ pytest-cov (>=4.1.0)
- ✅ black (>=23.11.0)
- ✅ flake8 (>=6.1.0)
- ✅ playwright (>=1.40.0)

---

## 📞 获取帮助

如果在安装过程中遇到问题：

1. 查看 [README.md](README.md) 了解更多详情
2. 查看 [pyproject.toml](pyproject.toml) 了解完整依赖列表
3. 查看 [.sisyphus/notepads/feishu-integration/](.sisyphus/notepads/feishu-integration/) 了解飞书集成文档

---

**生成时间**: 2026-03-22
**项目版本**: 0.1.0
**Python 版本要求**: >= 3.9
