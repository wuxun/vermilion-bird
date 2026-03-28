# Systemd 服务配置

## 安装步骤

### 1. 创建虚拟环境并安装依赖

```bash
cd /path/to/vermilion-bird

# 创建虚拟环境
python3 -m venv .venv

# 安装依赖
.venv/bin/pip install -e .
```

### 2. 编辑配置文件

修改 `vermilion-bird.service` 中的以下内容：

```ini
User=%USER%        # 替换为你的用户名
Group=%GROUP%      # 替换为你的组名
WorkingDirectory=/path/to/vermilion-bird  # 替换为项目实际路径
ExecStart=/path/to/vermilion-bird/.venv/bin/vermilion-bird  # 替换为实际路径
Environment="LLM_API_KEY=your-api-key-here"  # 设置你的 API Key
```

### 3. 安装服务

```bash
# 复制到 systemd 目录
sudo cp vermilion-bird.service /etc/systemd/system/

# 重新加载 systemd 配置
sudo systemctl daemon-reload

# 启用开机自启
sudo systemctl enable vermilion-bird

# 启动服务
sudo systemctl start vermilion-bird
```

### 4. 管理服务

```bash
# 查看状态
sudo systemctl status vermilion-bird

# 查看日志
sudo journalctl -u vermilion-bird -f

# 停止服务
sudo systemctl stop vermilion-bird

# 重启服务
sudo systemctl restart vermilion-bird

# 禁用开机自启
sudo systemctl disable vermilion-bird
```

## 用户级服务（无需 sudo）

如果希望以用户级服务运行：

```bash
# 创建用户服务目录
mkdir -p ~/.config/systemd/user/

# 复制配置文件
cp vermilion-bird.service ~/.config/systemd/user/

# 重新加载
systemctl --user daemon-reload

# 启用并启动
systemctl --user enable vermilion-bird
systemctl --user start vermilion-bird

# 查看状态
systemctl --user status vermilion-bird

# 查看日志
journalctl --user -u vermilion-bird -f
```

## 配置说明

| 参数 | 说明 |
|------|------|
| `Type=simple` | 适用于前台运行的服务 |
| `Restart=on-failure` | 服务异常退出时自动重启 |
| `RestartSec=10` | 重启前等待 10 秒 |
| `StandardOutput=journal` | 输出重定向到 systemd 日志 |

## 环境变量

可以在 service 文件中设置以下环境变量：

- `LLM_API_KEY` - API 密钥（必需）
- `LLM_BASE_URL` - API 基础 URL
- `LLM_MODEL` - 模型名称
- `LLM_PROTOCOL` - 协议类型 (openai/anthropic/gemini)

或使用 `config.yaml` 配置文件。
