#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$APP_DIR/.venv"
PORT="${PORT:-8080}"
PID_FILE="$APP_DIR/data/musicdl-web.pid"
mkdir -p "$APP_DIR/data" "$APP_DIR/downloads"

find_python() {
    if command -v uv &>/dev/null; then
        echo "uv"
        return
    fi
    for py in python3.12 python3.11 python3.10 python3; do
        if command -v "$py" &>/dev/null; then
            local ver
            ver=$("$py" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "0.0")
            if "$py" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>/dev/null; then
                echo "$py"
                return
            fi
        fi
    done
    echo "❌ 错误: 未检测到 Python 3.10+ 环境，请先安装 Python 3.10、3.11 或 uv" >&2
    exit 1
}

start_app() {
    PYTHON_EXEC=$(find_python)

    if [ "$PYTHON_EXEC" = "uv" ]; then
        if [ ! -d "$VENV_DIR" ]; then
            echo "⚡ 使用 uv 极速初始化虚拟环境..."
            uv venv "$VENV_DIR" --python 3.11 2>/dev/null || uv venv "$VENV_DIR"
        fi
        echo "📦 检查并同步 Python 依赖..."
        uv pip install --python "$VENV_DIR/bin/python" -r "$APP_DIR/requirements.txt" -q
        RUNNER="$VENV_DIR/bin/python"
    else
        if [ ! -d "$VENV_DIR" ]; then
            echo "🔧 使用 $PYTHON_EXEC 创建虚拟环境..."
            "$PYTHON_EXEC" -m venv "$VENV_DIR"
        fi
        echo "📦 安装/更新依赖项..."
        "$VENV_DIR/bin/pip" install -q -r "$APP_DIR/requirements.txt"
        RUNNER="$VENV_DIR/bin/python"
    fi

    echo ""
    echo "🎵 musicdl Web UI 正在启动..."
    echo "🌐 地址: http://127.0.0.1:${PORT}"
    echo ""

    # Open browser on macOS or Linux desktop
    if [ "$(uname)" = "Darwin" ]; then
        (sleep 1.5 && open "http://127.0.0.1:${PORT}" 2>/dev/null || true) &
    elif command -v xdg-open &>/dev/null; then
        (sleep 1.5 && xdg-open "http://127.0.0.1:${PORT}" 2>/dev/null || true) &
    fi

    # Run application
    exec "$RUNNER" -m backend.app
}

stop_app() {
    echo "🛑 正在停止 musicdl-web 服务..."
    pkill -f "backend.app" 2>/dev/null && echo "✅ 服务已停止" || echo "⚠️ 未发现正在运行的 backend.app 进程"
}

status_app() {
    if pgrep -f "backend.app" >/dev/null; then
        echo "🟢 musicdl-web 正在运行中 (端口: ${PORT})"
    else
        echo "⚪ musicdl-web 未运行"
    fi
}

case "${1:-start}" in
    start)
        start_app
        ;;
    stop)
        stop_app
        ;;
    status)
        status_app
        ;;
    restart)
        stop_app
        sleep 1
        start_app
        ;;
    *)
        echo "用法: $0 {start|stop|restart|status}"
        exit 1
        ;;
esac
