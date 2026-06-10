#!/bin/bash
# XIA Daemon 后台运行 + 自动重启
# 用法: bash daemon_watchdog.sh [start|stop|status]
# 日志: logs/daemon_watchdog.log

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$SCRIPT_DIR"

PID_FILE="../data/daemon_watchdog.pid"
LOG_FILE="../logs/daemon_watchdog.log"
DAEMON_LOG="../logs/daemon.log"

start_daemon() {
    if [ -f "$PID_FILE" ] && kill -0 $(cat "$PID_FILE") 2>/dev/null; then
        echo "daemon_watchdog 已在运行 (PID=$(cat $PID_FILE))"
        return 1
    fi

    echo "[$(date)] 启动 watchdog..." >> "$LOG_FILE"

    # 后台循环：daemon 退出后等 3 秒重启
    (
        while true; do
            echo "[$(date)] 启动 daemon (train-only)" >> "$LOG_FILE"
            python3 -m AEE.src.daemon.daemon \
                --tick-interval 3 \
                --train-only \
                >> "$DAEMON_LOG" 2>&1
            EXIT_CODE=$?
            echo "[$(date)] daemon 退出 (code=$EXIT_CODE)，3 秒后重启..." >> "$LOG_FILE"
            sleep 3
        done
    ) &

    WATCHDOG_PID=$!
    echo $WATCHDOG_PID > "$PID_FILE"
    echo "✓ watchdog 已启动 (PID=$WATCHDOG_PID)"
    echo "  日志: $LOG_FILE"
    echo "  daemon 日志: $DAEMON_LOG"
}

stop_daemon() {
    if [ ! -f "$PID_FILE" ]; then
        echo "watchdog 未运行"
        return 1
    fi
    PID=$(cat "$PID_FILE")
    # 杀 watchdog 进程组
    kill -TERM -$(ps -o pgid= -p $PID 2>/dev/null | tr -d ' ') 2>/dev/null
    kill -TERM $PID 2>/dev/null
    # 杀 daemon 进程
    pkill -f "AEE.src.daemon.daemon" 2>/dev/null
    rm -f "$PID_FILE"
    echo "[$(date)] watchdog 已停止" >> "$LOG_FILE"
    echo "✓ watchdog 已停止"
}

status_daemon() {
    if [ -f "$PID_FILE" ] && kill -0 $(cat "$PID_FILE") 2>/dev/null; then
        PID=$(cat "$PID_FILE")
        echo "watchdog: 运行中 (PID=$PID)"
        # 检查 daemon 是否活着
        if pgrep -f "AEE.src.daemon.daemon" > /dev/null; then
            echo "daemon: 运行中"
            echo "最近表达:"
            grep 'TrainOnly' "$DAEMON_LOG" 2>/dev/null | tail -3
        else
            echo "daemon: 未运行 (watchdog 会重启)"
        fi
    else
        echo "watchdog: 未运行"
    fi
}

case "${1:-start}" in
    start)   start_daemon ;;
    stop)    stop_daemon ;;
    status)  status_daemon ;;
    restart) stop_daemon; sleep 2; start_daemon ;;
    *)       echo "用法: $0 {start|stop|status|restart}" ;;
esac
