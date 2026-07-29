#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
echo "=== Vermilion Bird 可重复打包 ==="

BUILD_PYTHON="${VB_BUILD_PYTHON:-}"
if [ -n "$BUILD_PYTHON" ]; then
    # Accept either an executable path or a command name supplied by CI/users.
    BUILD_PYTHON="$(command -v "$BUILD_PYTHON" || true)"
fi
if [ -z "$BUILD_PYTHON" ]; then
    for candidate in python3.12 python3.13; do
        if command -v "$candidate" >/dev/null 2>&1; then
            BUILD_PYTHON="$(command -v "$candidate")"
            break
        fi
    done
fi
if [ -z "$BUILD_PYTHON" ] || [ ! -x "$BUILD_PYTHON" ]; then
    echo "❌ 需要 Python 3.12 或 3.13；可通过 VB_BUILD_PYTHON 指定解释器。"
    exit 1
fi

PYTHON_VERSION="$("$BUILD_PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
case "$PYTHON_VERSION" in
    3.12|3.13) ;;
    *)
        echo "❌ 不支持 Python $PYTHON_VERSION；发布构建固定使用 Python 3.12/3.13。"
        exit 1
        ;;
esac

DEFAULT_BUILD_VENV="$(pwd)/.venv-build"
BUILD_VENV="${VB_BUILD_VENV:-$DEFAULT_BUILD_VENV}"
VENV_VERSION=""
if [ -x "$BUILD_VENV/bin/python" ]; then
    VENV_VERSION="$("$BUILD_VENV/bin/python" -c \
        'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
fi
if [ "$VENV_VERSION" != "$PYTHON_VERSION" ]; then
    if [ -d "$BUILD_VENV" ]; then
        if [ "$BUILD_VENV" != "$DEFAULT_BUILD_VENV" ]; then
            echo "❌ 自定义构建环境的 Python 版本为 $VENV_VERSION，期望 $PYTHON_VERSION。"
            echo "   请更换 VB_BUILD_VENV；脚本不会自动删除自定义目录。"
            exit 1
        fi
        echo "→ 重建版本不匹配的构建环境（$VENV_VERSION → $PYTHON_VERSION）..."
        rm -rf "$DEFAULT_BUILD_VENV"
    fi
    echo "→ 创建 Python $PYTHON_VERSION 构建环境..."
    "$BUILD_PYTHON" -m venv "$BUILD_VENV"
fi

VENV_PYTHON="$BUILD_VENV/bin/python"
VENV_PIP="$BUILD_VENV/bin/pip"
VENV_PYINSTALLER="$BUILD_VENV/bin/pyinstaller"

echo "→ 同步锁定依赖..."
if [ ! -f requirements-build.lock ]; then
    echo "❌ 缺少 requirements-build.lock；请先更新发布依赖锁。"
    exit 1
fi
"$VENV_PIP" install --disable-pip-version-check -r requirements-build.lock
"$VENV_PIP" install \
    --disable-pip-version-check \
    --no-deps \
    --no-build-isolation \
    -e packages/ember-core \
    -e packages/ember-agent \
    -e .
"$VENV_PIP" check

if [ ! -f icon.icns ] && [ -f vermilion_bird_small.png ]; then
    echo "→ 转换 logo 为 .icns ..."
    mkdir -p icon.iconset
    for size in 16 32 128 256 512; do
        sips -z "$size" "$size" vermilion_bird_small.png \
            --out "icon.iconset/icon_${size}x${size}.png" >/dev/null
        sips -z "$((size*2))" "$((size*2))" vermilion_bird_small.png \
            --out "icon.iconset/icon_${size}x${size}@2x.png" >/dev/null
    done
    sips -z 1024 1024 vermilion_bird_small.png \
        --out icon.iconset/icon_512x512@2x.png >/dev/null
    iconutil -c icns icon.iconset -o icon.icns
    rm -rf icon.iconset
fi

echo "→ 清理旧产物..."
rm -rf build/vermilion-bird
rm -rf dist/vermilion-bird
rm -rf "dist/Vermilion Bird.app"
rm -f dist/Vermilion-Bird-macOS-arm64.zip
rm -f dist/Vermilion-Bird-macOS-arm64.zip.sha256
mkdir -p dist

echo "→ 使用 Python $PYTHON_VERSION 构建..."
"$VENV_PYINSTALLER" vermilion-bird.spec --noconfirm
rm -f dist/vermilion-bird-gui

echo "→ 执行包内烟雾与签名结构校验..."
dist/vermilion-bird/vermilion-bird --help >/dev/null
codesign --verify --deep --strict "dist/Vermilion Bird.app"

echo "→ 生成发布压缩包与 SHA-256..."
ditto -c -k --sequesterRsrc --keepParent \
    "dist/Vermilion Bird.app" \
    "dist/Vermilion-Bird-macOS-arm64.zip"
(
    cd dist
    shasum -a 256 Vermilion-Bird-macOS-arm64.zip \
        > Vermilion-Bird-macOS-arm64.zip.sha256
)
unzip -tq dist/Vermilion-Bird-macOS-arm64.zip

echo ""
echo "=== 打包完成 ==="
echo "Python: $("$VENV_PYTHON" --version)"
du -sh "dist/Vermilion Bird.app" "dist/Vermilion-Bird-macOS-arm64.zip"
cat dist/Vermilion-Bird-macOS-arm64.zip.sha256
