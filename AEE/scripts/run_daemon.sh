#!/bin/bash
# ============================================================================
# XIA Long-Term Memory Service — 启动脚本
#
# 用法：
#   ./run_daemon.sh           # 前台启动
#   ./run_daemon.sh --start  # 后台启动
#   ./run_daemon.sh --stop   # 停止后台进程
#   ./run_daemon.sh --status # 查看运行状态
#   ./run_daemon.sh --restart # 重启
# ============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${SCRIPT_DIR}/logs"
DATA_DIR="${SCRIPT_DIR}/data"
PID_FILE="${SCRIPT_DIR}/data/daemon.pid"
DAEMON_MODULE="AEE.src.daemon.daemon"
ENV_FILE="${SCRIPT_DIR}/.env"

# 加载 .env（如果存在）
if [ -f "${ENV_FILE}" ]; then
    set -a  # 自动 export 所有变量
    source "${ENV_FILE}"
    set +a
fi

mkdir -p "${LOG_DIR}" "${DATA_DIR}"

# --------------------------------------------------------------------------
# 操作函数
# --------------------------------------------------------------------------

start_daemon() {
    if is_running; then
        echo "XIA daemon 已在运行 (PID=$(cat "${PID_FILE}"))"
        return 0
    fi

    echo "启动 XIA daemon..."
    cd "${SCRIPT_DIR}"
    nohup python3 -m "${DAEMON_MODULE}" \
        --http-port 8765 \
        >> "${LOG_DIR}/daemon.log" 2>&1 &
    local pid=$!

    echo "${pid}" > "${PID_FILE}"

    sleep 2

    if is_running; then
        echo "✓ XIA daemon 已启动 (PID=${pid})"
        echo "  Socket: ${DATA_DIR}/xia_daemon.sock"
        echo "  HTTP API: http://127.0.0.1:8765 (Windows 前端)"
        echo "  日志: ${LOG_DIR}/daemon.log"
        echo ""
        echo "  启动对话窗口: python3 -m channel"
        echo "  查看状态: ./run_daemon.sh --status"
    else
        echo "✗ 启动失败，查看日志: ${LOG_DIR}/daemon.log"
        rm -f "${PID_FILE}"
        return 1
    fi
}

stop_daemon() {
    if ! is_running; then
        echo "XIA daemon 未运行"
        return 0
    fi

    local pid=$(cat "${PID_FILE}")
    echo "停止 XIA daemon (PID=${pid})..."

    kill -TERM "${pid}" 2>/dev/null || true

    # 等待进程退出
    local count=0
    while is_running && [ ${count} -lt 10 ]; do
        sleep 1
        count=$((count + 1))
    done

    if is_running; then
        echo "强制终止..."
        kill -9 "${pid}" 2>/dev/null || true
        sleep 1
    fi

    rm -f "${PID_FILE}"
    echo "✓ XIA daemon 已停止"
}

restart_daemon() {
    stop_daemon
    sleep 1
    start_daemon
}

status_daemon() {
    if is_running; then
        local pid=$(cat "${PID_FILE}")
        echo "XIA daemon: 运行中 (PID=${pid})"
        echo "  Socket: ${DATA_DIR}/xia_daemon.sock"
        if [ -f "${LOG_DIR}/daemon.log" ]; then
            local last_line=$(tail -n 1 "${LOG_DIR}/daemon.log" 2>/dev/null || echo "")
            echo "  最近日志: ${last_line}"
        fi
    else
        echo "XIA daemon: 未运行"
        echo "  启动: ./run_daemon.sh"
    fi
}

is_running() {
    if [ ! -f "${PID_FILE}" ]; then
        return 1
    fi
    local pid=$(cat "${PID_FILE}")
    if [ -z "${pid}" ] || [ ! -d "/proc/${pid}" ]; then
        rm -f "${PID_FILE}"
        return 1
    fi
    return 0
}

# --------------------------------------------------------------------------
# 主逻辑
# --------------------------------------------------------------------------

case "${1:-}" in
    --start|-s|start)
        start_daemon
        ;;
    --stop|-k|stop)
        stop_daemon
        ;;
    --restart|-r|restart)
        restart_daemon
        ;;
    --status|-t|status)
        status_daemon
        ;;
    --help|-h|help|"")
        echo "XIA Long-Term Memory Service"
        echo ""
        echo "用法: $0 [命令]"
        echo ""
        echo "命令："
        echo "  --start    启动 daemon（后台）"
        echo "  --stop     停止 daemon"
        echo "  --restart  重启 daemon"
        echo "  --status   查看运行状态"
        echo "  --help     显示本帮助"
        echo ""
        echo "直接运行脚本等同于 --start"
        echo ""
        echo "启动后，XIA 在后台持续运行。"
        echo "你不在的时候她继续呼吸。"
        ;;
    *)
        echo "未知命令: $1"
        echo "运行 '$0 --help' 查看帮助"
        exit 1
        ;;
esac
