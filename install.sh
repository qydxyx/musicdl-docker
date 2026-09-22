#!/usr/bin/env bash
# ── One-line installer for musicdl-web binary ──
set -euo pipefail

REPO="${MUSICDL_REPO:-CharlesPikachu/musicdl}"
INSTALL_DIR="${INSTALL_DIR:-$HOME/.local/bin}"

OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
ARCH="$(uname -m)"

case "$OS" in
    darwin) PLATFORM="macos" ;;
    linux)  PLATFORM="linux" ;;
    *)      echo "❌ 暂不支持的操作系统: $OS" >&2; exit 1 ;;
esac

case "$ARCH" in
    x86_64|amd64)  ARCH="x86_64" ;;
    arm64|aarch64) ARCH="aarch64" ;;
    *)      echo "❌ 暂不支持的 CPU 架构: $ARCH" >&2; exit 1 ;;
esac

ASSET="musicdl-web-${PLATFORM}-${ARCH}.tar.gz"
DOWNLOAD_URL="https://github.com/${REPO}/releases/latest/download/${ASSET}"

echo "======================================================"
echo "  🎵 musicdl-web 二进制一键安装器"
echo "  💻 系统平台: ${PLATFORM} (${ARCH})"
echo "  📦 下载源:   ${DOWNLOAD_URL}"
echo "======================================================"
echo ""

mkdir -p "$INSTALL_DIR"
TEMP_FILE="$(mktemp /tmp/musicdl-web-XXXXXX.tar.gz)"

echo "⬇️  正在下载预编译二进制包..."
if curl -fSL "$DOWNLOAD_URL" -o "$TEMP_FILE"; then
    echo "📦 正在解压至 $INSTALL_DIR ..."
    tar -xzf "$TEMP_FILE" -C "$INSTALL_DIR"
    chmod +x "$INSTALL_DIR/musicdl-web"
    rm -f "$TEMP_FILE"

    echo ""
    echo "🎉 安装完成！可执行文件路径: $INSTALL_DIR/musicdl-web"
    echo ""
    echo "💡 快速启动命令:"
    echo "   $INSTALL_DIR/musicdl-web"
    echo ""
    echo "🌐 然后在浏览器中打开: http://127.0.0.1:8080"
    echo "======================================================"
else
    rm -f "$TEMP_FILE"
    echo "❌ 下载失败。可能尚未发布对应平台的 Release 包，或者网络受限。" >&2
    echo "👉 您仍可以使用源码一键脚本运行: git clone ... && ./run.sh" >&2
    exit 1
fi
