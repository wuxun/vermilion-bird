#!/bin/bash
# Vermilion Bird Systemd Service 安装脚本
# 用法: sudo ./install.sh

set -e

# 配置变量
SERVICE_NAME="vermilion-bird"
INSTALL_DIR="/opt/vermilion-bird"
DATA_DIR="/var/lib/vermilion-bird"
LOG_DIR="/var/log/vermilion-bird"
USER_NAME="vermilion-bird"
GROUP_NAME="vermilion-bird"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检查 root 权限
if [ "$EUID" -ne 0 ]; then
    log_error "请使用 root 权限运行此脚本 (sudo ./install.sh)"
    exit 1
fi

# 选择服务类型
echo "请选择要安装的服务类型:"
echo "  1) feishu    - 飞书机器人服务 (推荐)"
echo "  2) chat      - CLI 聊天服务"
echo "  3) both      - 两者都安装"
read -p "请输入选项 [1-3]: " choice

case $choice in
    1)
        SERVICES=("feishu")
        ;;
    2)
        SERVICES=("chat")
        ;;
    3)
        SERVICES=("feishu" "chat")
        ;;
    *)
        log_error "无效选项"
        exit 1
        ;;
esac

# 创建用户和组
if ! id -u $USER_NAME >/dev/null 2>&1; then
    log_info "创建用户 $USER_NAME..."
    useradd -r -s /bin/false -d $DATA_DIR $USER_NAME
fi

# 创建目录
log_info "创建目录..."
mkdir -p $INSTALL_DIR
mkdir -p $DATA_DIR
mkdir -p $LOG_DIR
mkdir -p $DATA_DIR/memory
mkdir -p $DATA_DIR/.vb

# 复制项目文件（如果当前目录是项目根目录）
if [ -f "$(dirname $0)/../pyproject.toml" ]; then
    log_info "复制项目文件..."
    cp -r "$(dirname $0)/.."/* $INSTALL_DIR/
fi

# 设置权限
log_info "设置权限..."
chown -R $USER_NAME:$GROUP_NAME $INSTALL_DIR
chown -R $USER_NAME:$GROUP_NAME $DATA_DIR
chown -R $USER_NAME:$GROUP_NAME $LOG_DIR
chmod 750 $INSTALL_DIR
chmod 750 $DATA_DIR
chmod 750 $LOG_DIR

# 安装 Python 依赖
log_info "检查 Python 环境..."
if command -v python3 &> /dev/null; then
    cd $INSTALL_DIR
    
    # 创建虚拟环境（如果不存在）
    if [ ! -d ".venv" ]; then
        log_info "创建虚拟环境..."
        python3 -m venv .venv
    fi
    
    # 安装依赖
    log_info "使用 pip 安装依赖..."
    .venv/bin/pip install --upgrade pip setuptools wheel poetry-core
    .venv/bin/pip install -e .
    
    chown -R $USER_NAME:$GROUP_NAME $INSTALL_DIR
fi

# 安装 systemd 服务
for service in "${SERVICES[@]}"; do
    SERVICE_FILE="vermilion-bird"
    if [ "$service" = "chat" ]; then
        SERVICE_FILE="vermilion-bird-chat"
    fi
    
    if [ -f "$(dirname $0)/${SERVICE_FILE}.service" ]; then
        log_info "安装 ${SERVICE_FILE} 服务..."
        cp "$(dirname $0)/${SERVICE_FILE}.service" /etc/systemd/system/
        systemctl daemon-reload
        systemctl enable ${SERVICE_FILE}.service
        
        read -p "是否立即启动 ${SERVICE_FILE} 服务? [y/N]: " start_now
        if [ "$start_now" = "y" ] || [ "$start_now" = "Y" ]; then
            systemctl start ${SERVICE_FILE}.service
            log_info "${SERVICE_FILE} 服务已启动"
        fi
    fi
done

# 创建环境变量文件示例
log_info "创建配置文件示例..."
cat > /etc/vermilion-bird/config.env.example << 'EOF'
# LLM 配置
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4
LLM_API_KEY=your-api-key-here
LLM_PROTOCOL=openai

# 飞书配置（如果使用飞书服务）
FEISHU_APP_ID=your-app-id
FEISHU_APP_SECRET=your-app-secret
EOF

mkdir -p /etc/vermilion-bird
if [ ! -f /etc/vermilion-bird/config.env ]; then
    cp /etc/vermilion-bird/config.env.example /etc/vermilion-bird/config.env
    log_warn "请编辑 /etc/vermilion-bird/config.env 配置你的 API 密钥"
fi

echo ""
log_info "安装完成!"
echo ""
echo "常用命令:"
echo "  查看状态:   sudo systemctl status vermilion-bird"
echo "  启动服务:   sudo systemctl start vermilion-bird"
echo "  停止服务:   sudo systemctl stop vermilion-bird"
echo "  重启服务:   sudo systemctl restart vermilion-bird"
echo "  查看日志:   sudo journalctl -u vermilion-bird -f"
echo ""
echo "配置文件:     /opt/vermilion-bird/config.yaml"
echo "环境变量:     /etc/vermilion-bird/config.env"
echo "数据目录:     $DATA_DIR"
echo "日志目录:     $LOG_DIR"
