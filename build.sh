#!/usr/bin/env bash
set -euo pipefail

echo "=== Vermilion Bird 打包 ==="
cd "$(dirname "$0")"

# 使用 venv 中的 pip
VENV_PIP="$(pwd)/venv/bin/pip"
if [ ! -f "$VENV_PIP" ]; then
    echo "❌ 未找到 venv，请先运行: poetry install"
    exit 1
fi

# 1. 确保 PyInstaller 已安装
$VENV_PIP install pyinstaller 2>/dev/null | grep -v "already satisfied" || true

# 2. 转换 icon（如已有 .icns 则跳过）
if [ ! -f icon.icns ] && [ -f vermilion_bird_small.png ]; then
    echo "→ 转换 logo 为 .icns ..."
    mkdir -p icon.iconset
    for size in 16 32 128 256 512; do
        sips -z $size $size vermilion_bird_small.png \
            --out "icon.iconset/icon_${size}x${size}.png" >/dev/null
        sips -z $((size*2)) $((size*2)) vermilion_bird_small.png \
            --out "icon.iconset/icon_${size}x${size}@2x.png" >/dev/null
    done
    # 额外生成 1024x1024 (512@2x)
    sips -z 1024 1024 vermilion_bird_small.png \
        --out icon.iconset/icon_512x512@2x.png >/dev/null
    iconutil -c icns icon.iconset -o icon.icns
    rm -rf icon.iconset
    echo "✓ icon.icns 生成完成 ($(ls -lh icon.icns | awk '{print $5}'))"
fi

# 3. 清理旧构建
rm -rf build dist

# 4. 执行构建
echo "→ 开始构建 (可能需要 1-3 分钟)..."
source venv/bin/activate
pyinstaller vermilion-bird.spec

echo ""
echo "=== 打包完成 ==="
echo "CLI:   dist/vermilion-bird"
echo "GUI:   dist/Vermilion Bird.app"
ls -lh dist/ 2>/dev/null
echo ""
echo "使用方式:"
echo "  ./dist/vermilion-bird chat              # CLI 模式"
echo "  ./dist/vermilion-bird chat --gui        # GUI 模式"
echo "  open 'dist/Vermilion Bird.app'          # 双击启动"
