#!/usr/bin/env python3
"""
Reach Client — XIA 主动敲门的监听端

运行在你这一侧，常驻监听 XIA 发来的消息并弹通知。

启动方式：
    python3 -m reach_client
    ./run_reach_client.sh

流程：
    循环监控 data/xia_messages/notification_queue.jsonl
        → 有新通知 → 弹 Windows 通知 → 等待用户输入
        → 用户输入 → 写入 data/xia_messages/response.json
        → daemon 读取回应 → XIA 继续

不需要和 daemon 在同一进程，只需共享 data/ 目录。
"""

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

# 把项目根加到路径（以便导入 src 模块）
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

# 用 StreamHandler + FileHandler 双写，都强制 UTF-8
root = logging.getLogger()
root.setLevel(logging.INFO)
root.handlers.clear()
handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.INFO)
handler.setFormatter(logging.Formatter(
    "%(asctime)s [reach_client] %(levelname)s: %(message)s"
))
root.addHandler(handler)
logger = logging.getLogger("reach_client")

# 路径
DATA_DIR = PROJECT_ROOT / "data"
MESSAGES_DIR = DATA_DIR / "xia_messages"
MESSAGES_DIR.mkdir(parents=True, exist_ok=True)

NOTIFICATION_QUEUE = MESSAGES_DIR / "notification_queue.jsonl"
RESPONSE_FILE = MESSAGES_DIR / "response.json"
LAST_READ_POS = MESSAGES_DIR / ".last_notification_pos"


# ============================================================================
# 通知弹窗（跨平台）
# ============================================================================

def show_notification(title: str, body: str, urgency: str = "normal") -> None:
    """
    弹出系统通知。

    优先级：
        1. PowerShell Windows Toast（WSL 环境）
        2. 系统内置工具
    """
    # WSL 检测
    is_wsl = os.path.exists("/proc/version") and "microsoft" in open("/proc/version").read().lower()

    if is_wsl:
        _show_wsl_notification(title, body, urgency)
    else:
        _show_native_notification(title, body)


def _show_wsl_notification(title: str, body: str, urgency: str) -> None:
    """WSL 环境下的通知：尝试 PowerShell"""
    import subprocess

    # 清理 XML 特殊字符
    body_safe = body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

    ps_script = f'''
Add-Type -AssemblyName System.Windows.Forms
$n = New-Object System.Windows.Forms.NotifyIcon
$n.Icon = [System.Drawing.SystemIcons]::Information
$n.Visible = $true
$n.ShowBalloonTip(5000, "{title}", "{body_safe}", "Info")
Start-Sleep -Seconds 6
$n.Dispose()
'''

    try:
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps_script],
            capture_output=True,
            timeout=10,
        )
        logger.info(f"[notify] Shown: {title} — {body[:40]}")
    except Exception as e:
        logger.warning(f"[notify] PowerShell failed: {e}, falling back to print")
        print(f"\n{'='*60}")
        print(f"  {title}")
        print(f"  {body}")
        print(f"{'='*60}\n")


def _show_native_notification(title: str, body: str) -> None:
    """本地系统的通知"""
    import subprocess
    try:
        # macOS
        subprocess.run(["osascript", "-e", f'display notification "{body}" with title "{title}"'],
                       capture_output=True, timeout=5)
    except Exception:
        # Linux
        try:
            subprocess.run(["notify-send", title, body], capture_output=True, timeout=5)
        except Exception:
            print(f"\n{'='*60}")
            print(f"  {title}")
            print(f"  {body}")
            print(f"{'='*60}\n")


# ============================================================================
# 主循环
# ============================================================================

def run(poll_interval: float = 2.0) -> None:
    """
    常驻监听循环。

    参数：
        poll_interval : 文件检查间隔（秒）
    """
    logger.info(f"Reach Client 启动，监听 {MESSAGES_DIR}")
    logger.info("XIA 有话想说时会弹通知，输入你的回应她会收到")
    print("\n  按 Ctrl+C 退出\n")

    # 读取上次处理到的位置
    last_pos = _read_last_pos()

    while True:
        try:
            # ---- 检查通知队列 ----
            if NOTIFICATION_QUEUE.exists():
                new_notifications = _read_new_notifications(last_pos)
                for notif in new_notifications:
                    _handle_notification(notif)
                    last_pos = notif["_end_pos"]

                if new_notifications:
                    _write_last_pos(last_pos)

            # ---- 检查是否已有待响应消息 ----
            # （reach_client 重启后，如果 pending.json 还在说明没被处理）
            from AEE.src.action_system.reach import read_pending, write_response

            pending = read_pending()
            if pending and pending.get("status") == "waiting":
                _handle_pending_message(pending)

        except KeyboardInterrupt:
            logger.info("收到退出信号，停止监听")
            break
        except Exception as e:
            logger.error(f"轮询异常: {e}")

        time.sleep(poll_interval)


def _handle_notification(notif: dict) -> None:
    """处理单条通知"""
    title = notif.get("title", "XIA")
    body = notif.get("body", "")
    urgency = notif.get("urgency", "normal")

    print(f"\n  [{urgency.upper()}] {title}: {body[:80]}")
    show_notification(title, body, urgency)


def _handle_pending_message(pending: dict) -> None:
    """处理 XIA 发来的等待消息"""
    from AEE.src.action_system.reach import read_pending, write_response

    message = pending.get("message", "")
    intent = pending.get("intent", "reach")
    tick = pending.get("tick", 0)

    print(f"\n{'='*60}")
    print(f"  XIA (tick={tick}) 想对你说：")
    print(f"{'='*60}")
    print(f"\n  {message.strip()}\n")

    try:
        response = input("  你想回应什么？ ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n  (跳过回应)")
        return

    if response:
        write_response(response)
        print(f"  ✓ 回应已发送\n")
        # 清除 pending（daemon 下次 tick 会读取 response）
        from AEE.src.action_system.reach import clear_pending
        clear_pending()
        logger.info(f"回应已写入: {response[:50]}")
    else:
        print("  (无回应)\n")


# ============================================================================
# 辅助：文件位置追踪
# ============================================================================

def _read_last_pos() -> int:
    try:
        with open(LAST_READ_POS, encoding="utf-8") as f:
            return int(f.read().strip())
    except Exception:
        return 0


def _write_last_pos(pos: int) -> None:
    try:
        with open(LAST_READ_POS, "w", encoding="utf-8") as f:
            f.write(str(pos))
    except Exception:
        pass


def _read_new_notifications(last_pos: int) -> list:
    """从 last_pos 位置读取新增的通知"""
    if not NOTIFICATION_QUEUE.exists():
        return []

    try:
        with open(NOTIFICATION_QUEUE, encoding="utf-8") as f:
            f.seek(last_pos)
            new_lines = f.readlines()
            end_pos = f.tell()

        results = []
        for line in new_lines:
            line = line.strip()
            if line:
                try:
                    notif = json.loads(line)
                    notif["_end_pos"] = end_pos
                    results.append(notif)
                except Exception:
                    pass

        # 更新 end_pos（最后一行的结束位置）
        if results:
            results[-1]["_end_pos"] = end_pos

        return results

    except Exception:
        return []


# ============================================================================
# 入口
# ============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="XIA Reach Client — 监听 XIA 的主动消息")
    parser.add_argument(
        "--poll-interval", type=float, default=2.0,
        help="检查间隔（秒），默认 2"
    )
    args = parser.parse_args()

    print("=" * 60)
    print("  XIA Reach Client")
    print("  监听 XIA 主动发来的消息")
    print("=" * 60)

    run(poll_interval=args.poll_interval)
