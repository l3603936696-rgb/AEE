#!/usr/bin/env python3
"""XIA 后台管理工具"""
import os
import sys
import signal
import subprocess
import time
import socket

XIA_DIR = os.path.dirname(os.path.abspath(__file__))
PID_FILE = os.path.join(XIA_DIR, "data", "daemon.pid")
LOG_FILE = os.path.join(XIA_DIR, "logs", "daemon.log")
HTTP_PORT = 8765


def is_running():
    if not os.path.exists(PID_FILE):
        return False
    try:
        pid = int(open(PID_FILE).read().strip())
        # Windows 兼容方式检测进程
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    except (ProcessLookupError, ValueError, OSError):
        try:
            os.remove(PID_FILE)
        except:
            pass
        return False


def check_http():
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(("127.0.0.1", HTTP_PORT))
        sock.close()
        return result == 0
    except:
        return False


def start():
    if is_running():
        print("XIA daemon 已在运行")
        return

    print("启动 XIA daemon...")
    os.makedirs(os.path.dirname(PID_FILE), exist_ok=True)
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

    with open(LOG_FILE, "a") as f:
        f.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')} 手动启动 ---\n")

    proc = subprocess.Popen(
        [sys.executable, "-m", "src.daemon.daemon", "--http-port", str(HTTP_PORT)],
        cwd=XIA_DIR,
        stdout=open(LOG_FILE, "a"),
        stderr=subprocess.STDOUT
    )

    open(PID_FILE, "w").write(str(proc.pid))
    time.sleep(2)

    if is_running():
        print(f"[OK] XIA daemon 已启动 (PID={proc.pid})")
    else:
        print("[FAIL] 启动失败，查看日志:", LOG_FILE)


def stop():
    if not is_running():
        print("XIA daemon 未运行")
        return

    pid = int(open(PID_FILE).read().strip())
    print(f"停止 XIA daemon (PID={pid})...")

    try:
        import ctypes
        PROCESS_TERMINATE = 0x0001
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
        if handle:
            ctypes.windll.kernel32.TerminateProcess(handle, 0)
            ctypes.windll.kernel32.CloseHandle(handle)
        time.sleep(2)
        if not is_running():
            os.remove(PID_FILE)
            print("[OK] XIA daemon 已停止")
        else:
            print("[OK] XIA daemon 已强制停止")
    except Exception as e:
        print(f"停止时出错: {e}")


def restart():
    stop()
    time.sleep(1)
    start()


def status():
    if is_running():
        pid = open(PID_FILE).read().strip()
        http_ok = check_http()
        print(f"XIA daemon: 运行中 (PID={pid})")
        print(f"HTTP API: [OK] 可用" if http_ok else f"HTTP API: [X] 不可用")

        if os.path.exists(LOG_FILE):
            try:
                with open(LOG_FILE, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
                    if lines:
                        print(f"最近日志: {lines[-1].strip()}")
            except:
                pass
    else:
        print("XIA daemon: 未运行")


def log():
    if not os.path.exists(LOG_FILE):
        print("日志文件不存在")
        return

    lines = open(LOG_FILE).readlines()
    if not lines:
        print("日志为空")
        return

    # 显示最近 20 行
    print("=== 最近日志 ===")
    for line in lines[-20:]:
        print(line.rstrip())


def shell():
    print("\n=== XIA 交互模式 ===")
    print("输入消息与 XIA 对话，输入 /quit 退出\n")

    sys.path.insert(0, XIA_DIR)
    try:
        from channel import run_channel
        run_channel()
    except ImportError:
        print("无法导入 channel 模块，请手动运行: python -m channel")
    except KeyboardInterrupt:
        print("\n退出对话模式")


def main():
    os.system("cls" if os.name == "nt" else "clear")

    # Windows 终端设置 UTF-8
    if os.name == "nt":
        os.system("chcp 65001 >nul 2>&1")

    print("=" * 40)
    print("       XIA 后台管理工具")
    print("=" * 40)
    print()

    if len(sys.argv) > 1:
        cmd = sys.argv[1].lower()
        if cmd in ("start", "1"):
            start()
        elif cmd in ("stop", "2"):
            stop()
        elif cmd in ("restart", "3"):
            restart()
        elif cmd in ("status", "4"):
            status()
        elif cmd in ("log", "5"):
            log()
        elif cmd in ("shell", "6"):
            shell()
        else:
            print("未知命令")
    else:
        status()
        print()
        print("操作选项:")
        print("  1. 启动 XIA")
        print("  2. 停止 XIA")
        print("  3. 重启 XIA")
        print("  4. 查看状态")
        print("  5. 查看日志")
        print("  6. 进入对话模式")
        print("  q. 退出")
        print()

        choice = input("请选择: ").strip().lower()

        if choice == "1":
            start()
        elif choice == "2":
            stop()
        elif choice == "3":
            restart()
        elif choice == "4":
            status()
        elif choice == "5":
            log()
        elif choice == "6":
            shell()


if __name__ == "__main__":
    main()
