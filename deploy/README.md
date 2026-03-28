# Systemd Service 部署指南

本目录包含 Vermilion Bird 的 systemd 服务配置文件，用于在 Linux 系统上长期运行。

## 文件说明

| 文件 | 说明 |
|------|------|
| `vermilion-bird.service` | 飞书机器人服务 |
| `vermilion-bird-chat.service` | CLI 聊天服务 |
| `install.sh` | 自动安装脚本 |

## 快速安装

```bash
# 1. 复制项目到目标服务器
scp -r /path/to/vermilion-bird user@server:/tmp/

# 2. 在服务器上运行安装脚本
sudo /tmp/vermilion-bird/deploy/install.sh
```

## 手动安装

### 1. 创建用户

```bash
sudo useradd -r -s /bin/false -d /var/lib/vermilion-bird vermilion-bird
```

### 2. 创建目录

```bash
sudo mkdir -p /opt/vermilion-bird
sudo mkdir -p /var/lib/vermilion-bird
sudo mkdir -p /var/log/vermilion-bird
```

### 3. 安装项目

```bash
# 复制项目文件
sudo cp -r ./* /opt/vermilion-bird/

# 创建虚拟环境并安装依赖
cd /opt/vermilion-bird
python3 -m venv .venv
.venv/bin/pip install -e .

# 设置权限
sudo chown -R vermilion-bird:vermilion-bird /opt/vermilion-bird
sudo chown -R vermilion-bird:vermilion-bird /var/lib/vermilion-bird
sudo chown -R vermilion-bird:vermilion-bird /var/log/vermilion-bird
```

### 4. 安装 systemd 服务

```bash
# 复制 service 文件
sudo cp deploy/vermilion-bird.service /etc/systemd/system/

# 重载 systemd
sudo systemctl daemon-reload

# 启用开机自启
sudo systemctl enable vermilion-bird

# 启动服务
sudo systemctl start vermilion-bird
```

## 配置

### 环境变量

创建 `/etc/vermilion-bird/config.env`：

```bash
# LLM 配置
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4
LLM_API_KEY=your-api-key
LLM_PROTOCOL=openai
```

然后在 service 文件中取消注释 `EnvironmentFile` 行。

### YAML 配置

编辑 `/opt/vermilion-bird/config.yaml`：

```yaml
llm:
  base_url: "https://api.openai.com/v1"
  model: "gpt-4"
  api_key: "your-api-key"
  protocol: "openai"

feishu:
  enabled: true
  app_id: "your-app-id"
  app_secret: "your-app-secret"
```

## 服务管理

```bash
# 查看状态
sudo systemctl status vermilion-bird

# 启动
sudo systemctl start vermilion-bird

# 停止
sudo systemctl stop vermilion-bird

# 重启
sudo systemctl restart vermilion-bird

# 查看日志
sudo journalctl -u vermilion-bird -f

# 查看最近 100 行日志
sudo journalctl -u vermilion-bird -n 100
```

## 安全加固

service 文件已包含以下安全设置：

- `NoNewPrivileges=true` - 禁止提权
- `PrivateTmp=true` - 使用私有 /tmp
- `ProtectSystem=strict` - 保护系统目录
- `ProtectHome=true` - 保护用户主目录

如需访问其他目录，添加到 `ReadWritePaths`。

## 故障排查

### 服务无法启动

```bash
# 查看详细错误
sudo journalctl -u vermilion-bird -n 50 --no-pager

# 检查配置文件
cat /opt/vermilion-bird/config.yaml

# 手动运行测试
sudo -u vermilion-bird /opt/vermilion-bird/.venv/bin/vermilion-bird feishu
```

### 权限问题

```bash
# 检查文件权限
ls -la /opt/vermilion-bird/
ls -la /var/lib/vermilion-bird/
ls -la /var/log/vermilion-bird/

# 修复权限
sudo chown -R vermilion-bird:vermilion-bird /opt/vermilion-bird
sudo chown -R vermilion-bird:vermilion-bird /var/lib/vermilion-bird
sudo chown -R vermilion-bird:vermilion-bird /var/log/vermilion-bird
```

### 网络问题

```bash
# 检查网络连接
curl -v https://api.openai.com/v1/models

# 检查飞书连接
curl -v https://open.feishu.cn/
```

## 更新

```bash
# 停止服务
sudo systemctl stop vermilion-bird

# 更新代码
cd /opt/vermilion-bird
git pull

# 更新依赖
.venv/bin/pip install -e .

# 重启服务
sudo systemctl start vermilion-bird
```

## 卸载

```bash
# 停止并禁用服务
sudo systemctl stop vermilion-bird
sudo systemctl disable vermilion-bird

# 删除 service 文件
sudo rm /etc/systemd/system/vermilion-bird.service
sudo systemctl daemon-reload

# 删除用户和目录（可选）
sudo userdel vermilion-bird
sudo rm -rf /opt/vermilion-bird
sudo rm -rf /var/lib/vermilion-bird
sudo rm -rf /var/log/vermilion-bird
```
