# 解决 lark-oapi 导入错误

**错误信息**:
```
ModuleNotFoundError: No module named 'lark'
```

---

## 问题原因

**问题1（已修复）**: `src/llm_chat/frontends/feishu/server.py` 中的导入语句错误

```python
# 错误的导入（已修复）
from lark import ws  # ❌ 模块名称错误

# 正确的导入（已修复为）
from lark_oapi import ws  # ✅ 正确的模块名
```

**问题2**: `lark-oapi` 包未安装

如果运行时仍然遇到 `ModuleNotFoundError`，说明 `lark-oapi` 包尚未安装。

---

## ✅ 解决方案

### 方式一：使用虚拟环境安装（推荐）

```bash
# 1. 进入项目目录
cd /Users/xunwu/Documents/git/vermilion-bird

# 2. 激活现有虚拟环境（如存在）
source venv/bin/activate  # Linux/macOS
# 或
# venv\Scripts\activate  # Windows

# 3. 安装 lark-oapi
python3 -m pip install lark-oapi

# 4. 验证安装
python3 -m pip show lark-oapi

# 应该看到类似输出：
# Name: lark-oapi
# Version: 1.0.0
```

### 方式二：使用 --user 标志（快速）

```bash
# 直接使用 --user 标志安装
python3 -m pip install --user lark-oapi

# 验证安装
python3 -m pip show lark-oapi
```

### 方式三：使用 requirements.txt（一键安装）

```bash
# 进入项目目录
cd /Users/xunwu/Documents/git/vermilion-bird

# 安装所有依赖（包含 lark-oapi）
python3 -m pip install -r requirements.txt

# 验证安装
python3 -m pip show lark-oapi
```

### 方式四：创建新的虚拟环境（如果当前环境有问题）

```bash
# 1. 创建新的虚拟环境
python3 -m venv venv

# 2. 激活虚拟环境
source venv/bin/activate  # Linux/macOS
# venv\Scripts\activate  # Windows

# 3. 升级 pip
python3 -m pip install --upgrade pip

# 4. 安装依赖
pip install -r requirements.txt

# 5. 验证安装
python3 -m pip show lark-oapi
```

---

## 验证安装成功

安装完成后，运行以下命令验证：

```bash
# 应该看到 lark-oapi 包信息
python3 -m pip show lark-oapi

# 应该显示类似输出：
# Name: lark-oapi
# Version: 1.0.0
# Summary: Lark Open API Python SDK

# 测试导入（应该没有错误）
python3 -c "from lark import ws; print('lark-oapi 安装成功')"
```

---

## 🔧 如果仍然失败

### 问题：pip 安装失败

**解决方案**：
```bash
# 使用国内镜像源
python3 -m pip install lark-oapi -i https://pypi.tuna.tsinghua.edu.cn/simple

# 或使用清华镜像
python3 -m pip install lark-oapi -i https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple/
```

### 问题：权限错误

**解决方案**：
```bash
# 使用 --user 标志
python3 -m pip install --user lark-oapi
```

### 问题：版本冲突

**解决方案**：
```bash
# 指定版本
python3 -m pip install lark-oapi==1.0.0
```

---

## 安装后测试

安装成功后，再次运行：

```bash
# 确认当前目录
cd /Users/xunwu/Documents/git/vermilion-bird

# 运行飞书 Bot
python3 -m llm_chat.cli feishu

# 或使用项目入口
./venv/bin/vermilion-bird feishu
```

---

## 📝 推荐安装流程（最简单）

```bash
# 进入项目目录
cd /Users/xunwu/Documents/git/vermilion-bird

# 激活虚拟环境（如已存在）
source venv/bin/activate

# 安装 lark-oapi（使用 --user 标志避免权限问题）
python3 -m pip install --user lark-oapi

# 验证安装
python3 -m pip show lark-oapi

# 运行飞书 Bot（需要先配置 FEISHU_APP_ID 和 FEISHU_APP_SECRET）
python3 -m llm_chat.cli feishu
```

---

**生成时间**: 2026-03-22
**问题**: lark-oapi 模块未找到
**状态**: ✅ 提供多种解决方案
