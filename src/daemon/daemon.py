"""
Daemon Server — XIA 长期记忆服务主进程

职责：
- 接收并处理来自 channel/chat.py 的 IPC 请求
- 运行 Tick Engine 推进后台状态
- 持久化 XIA 的跨对话状态

架构：
    DaemonServer
        ├── TickEngine    — 后台 tick 推进
        ├── IPCServer     — Unix Domain Socket 请求处理
        ??? HTTPServer    ? local HTTP API

启动：
    python3 -m src.daemon.daemon

Socket 文件：data/xia_daemon.sock
"""

import logging
import os
import signal
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from .ipc_client import SOCKET_PATH, IPCError
from .ipc_chat_handler import handle_chat_request
from .protocol import IPCRequest, IPCResponse
from .tick_engine import TickEngine
from .http_server import HTTPServer
from ..entity_zero_iteration import get_entity_state
from ..response_cache import ResponseCache


logger = logging.getLogger(__name__)

# 加载 .env（API keys — DeepSeek）
_ENV_FILE = Path(__file__).parent.parent.parent.parent / ".env"
if _ENV_FILE.is_file():
    with open(_ENV_FILE, encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _key, _val = _line.split("=", 1)
                os.environ.setdefault(_key.strip(), _val.strip())


# ============================================================================
# IPC 服务器
# ============================================================================

MAX_REQUEST_SIZE = 1024 * 1024  # 1MB
IPC_TCP_PORT = 8766  # Windows IPC 端口（Unix 用 socket 文件）


class IPCServer:
    """
    IPC 服务器。

    - Linux/macOS: Unix Domain Socket (data/xia_daemon.sock)
    - Windows: TCP Socket (127.0.0.1:8766)
    """

    def __init__(self, tick_engine: TickEngine, shutdown_callback, llm_callable=None, ipc_port: int = IPC_TCP_PORT, response_cache: Optional[ResponseCache] = None) -> None:
        self._tick_engine = tick_engine
        self._shutdown_callback = shutdown_callback
        self._llm_callable = llm_callable
        self._server_sock: Optional[socket.socket] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._is_windows = sys.platform == "win32"
        self._ipc_port = ipc_port
        self._listen_addr = f"127.0.0.1:{ipc_port}" if self._is_windows else str(SOCKET_PATH)
        self._response_cache = response_cache

    def start(self) -> None:
        """启动 IPC 服务器（在后台线程中运行）"""
        if self._running:
            return

        if self._is_windows:
            # Windows: TCP Socket
            self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 262144)
            self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 262144)
            self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._server_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self._server_sock.bind(("127.0.0.1", self._ipc_port))
        else:
            # Unix: Unix Domain Socket — WSL 下可能不支持，fallback 到 TCP
            try:
                if SOCKET_PATH.exists():
                    SOCKET_PATH.unlink()
                SOCKET_PATH.parent.mkdir(parents=True, exist_ok=True)
                self._server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self._server_sock.bind(str(SOCKET_PATH))
            except OSError:
                logger.warning(f"[IPCServer] AF_UNIX 不可用，fallback 到 TCP {self._ipc_port}")
                self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self._server_sock.bind(("127.0.0.1", self._ipc_port))
                self._listen_addr = f"127.0.0.1:{self._ipc_port}"

        self._server_sock.listen(5)
        self._running = True

        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()
        logger.info(f"[IPCServer] listening on {self._listen_addr}")

    def stop(self) -> None:
        """停止 IPC 服务器"""
        self._running = False
        if self._server_sock:
            try:
                self._server_sock.close()
            except Exception:
                pass
        if not self._is_windows and SOCKET_PATH.exists():
            try:
                SOCKET_PATH.unlink()
            except Exception:
                pass

    def _accept_loop(self) -> None:
        """接收连接的主循环"""
        while self._running:
            try:
                self._server_sock.settimeout(1.0)
                try:
                    client, _ = self._server_sock.accept()
                except socket.timeout:
                    continue

                threading.Thread(target=self._handle_client, args=(client,), daemon=True).start()
            except Exception as e:
                if self._running:
                    logger.error(f"[IPCServer] accept error: {e}")

    def _send_all(self, sock: socket.socket, data: bytes) -> None:
        """循环发送直到所有字节送达，处理 Windows send() 缓冲区填满的情况。"""
        total = len(data)
        sent = 0
        while sent < total:
            try:
                n = sock.send(data[sent:])
            except BrokenPipeError as e:
                raise IPCError(f"Connection broken while sending: {e}")
            if n == 0:
                raise IPCError("Socket returned 0 bytes during send")
            sent += n
        logger.debug(f"[IPCServer] _send_all: {total} bytes sent ({total - sent} retried)")

    def _handle_client(self, client: socket.socket) -> None:
        """处理单个客户端连接"""
        try:
            client.settimeout(120.0)
            # 接收请求长度（4字节 big-endian）
            header = self._recv_exact(client, 4)
            length = int.from_bytes(header, "big")
            if length > MAX_REQUEST_SIZE:
                self._send_error(client, "Request too large")
                return

            body = self._recv_exact(client, length)
            request = IPCRequest.from_json(body.decode("utf-8"))
            response_bytes = self._dispatch(request).encode("utf-8")
            self._send_all(client, len(response_bytes).to_bytes(4, "big"))
            self._send_all(client, response_bytes)
        except Exception as e:
            logger.error(f"[IPCServer] handle error: {e}")
        finally:
            try:
                client.close()
            except Exception:
                pass

    def _recv_exact(self, client: socket.socket, n: int) -> bytes:
        """精确接收 n 字节"""
        data = b""
        while len(data) < n:
            chunk = client.recv(n - len(data))
            if not chunk:
                raise IPCError("Connection closed")
            data += chunk
        return data

    def _send_error(self, client: socket.socket, message: str) -> None:
        """发送错误响应"""
        resp = IPCResponse(type="error", id="", ok=False, error=message)
        try:
            data = resp.to_json().encode("utf-8")
            self._send_all(client, len(data).to_bytes(4, "big"))
            self._send_all(client, data)
        except Exception:
            pass

    def _dispatch(self, request: IPCRequest) -> str:
        """根据请求类型分发处理"""
        try:
            if request.type == "chat":
                result = self._handle_chat(request)
                resp = IPCResponse.success(request.id, result, "chat_response")
            elif request.type == "status":
                result = self._handle_status()
                resp = IPCResponse.success(request.id, result, "status_response")
            elif request.type == "shutdown":
                result = {"message": "shutting down"}
                resp = IPCResponse.success(request.id, result, "shutdown_ack")
                threading.Thread(target=lambda: self._trigger_shutdown(), daemon=True).start()
            elif request.type == "ping":
                result = {"pong": True}
                resp = IPCResponse.success(request.id, result, "pong")
            elif request.type == "training_tick":
                result = self._handle_training_tick(request)
                resp = IPCResponse.success(request.id, result, "training_response")
            else:
                resp = IPCResponse.failure(request.id, f"Unknown request type: {request.type}", "error")
            return resp.to_json()
        except Exception as e:
            logger.error(f"[IPCServer] dispatch error: {e}")
            resp = IPCResponse.failure(request.id, str(e), "error")
            return resp.to_json()

    def _handle_chat(self, request: IPCRequest) -> dict:
        """Handle chat requests."""
        return handle_chat_request(
            request,
            self._llm_callable,
            self._response_cache,
            logger,
        )
    def _handle_status(self) -> dict:
        """处理状态查询请求"""
        status = self._tick_engine.get_status()
        status["pid"] = os.getpid()
        return status

    def _handle_training_tick(self, request: IPCRequest) -> dict:
        """在指定 override_state 下运行单次语言训练 tick，返回选词结果。"""
        override_state = request.payload.get("override_state", {})
        try:
            from ..language_training import run_language_training_tick
            entity = self._tick_engine.entity
            snapshot = {}
            return run_language_training_tick(entity, snapshot, override_state=override_state)
        except Exception as e:
            return {"error": str(e)}

    def _trigger_shutdown(self) -> None:
        """触发 daemon 关闭"""
        self._shutdown_callback()

    def _save_shutdown_event(self) -> None:
        """保存关机断档：时间戳 + 状态快照，供开机时计算离线漂移"""
        try:
            entity = self._tick_engine.entity
            if entity is None:
                logger.warning("[ShutdownEvent] No entity found, skipping")
                return
            entity.last_shutdown_time = time.time()
            entity.last_shutdown_tick = entity.tick
            entity.persist_to_file()
            logger.info(f"[ShutdownEvent] Saved shutdown at tick={entity.tick}, time={entity.last_shutdown_time}")
        except Exception as e:
            logger.warning(f"[ShutdownEvent] Failed to save shutdown event: {e}")


# ============================================================================
# HTTP API 服务器 (Windows 兼容)
# ============================================================================

# ============================================================================

def run_daemon(tick_interval: float = 30.0, http_port: int = 8765, ipc_port: int = 8766, train_only: bool = False) -> None:
    """
    启动 XIA 长期记忆服务。

    参数：
        tick_interval : 两次后台 tick 之间的间隔（秒）
    """
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    log_dir = Path(__file__).parent.parent.parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_dir / "daemon_live.log", encoding="utf-8"),
        ],
    )
    logger.info("=" * 48)
    logger.info("XIA Long-Term Memory Service")
    logger.info("=" * 48)

    # 加载持久化状态
    entity = get_entity_state()
    logger.info(
        f"Entity loaded: tick={entity.tick}, "
        f"energy={entity.energy:.3f}, "
        f"wm_rules={len(entity.wm_rules)}"
    )

    # 初始化 LLM 后端（DeepSeek API，带观测）
    from ..observability import create_wrapped_llm
    llm_callable = create_wrapped_llm("daemon_ipc")

    # 初始化组件
    shutdown_requested = threading.Event()
    response_cache = ResponseCache(capacity=3)
    ipc_server = IPCServer(tick_engine=None, shutdown_callback=shutdown_requested.set, llm_callable=llm_callable, ipc_port=ipc_port, response_cache=response_cache)
    tick_engine = TickEngine(tick_interval=tick_interval, entity_state=entity, ipc_server=ipc_server, llm_callable=llm_callable, train_only=train_only, response_cache=response_cache)
    ipc_server._tick_engine = tick_engine

    # 启动 IPC 服务器
    ipc_server.start()
    logger.info(f"IPC listening on {SOCKET_PATH}")

    # 启动 HTTP API 服务器（供 Windows 前端访问）
    http_server = HTTPServer(ipc_server=ipc_server, port=http_port)
    http_server.start()
    logger.info(f"HTTP API: http://127.0.0.1:{http_port} (local clients)")

    # 启动后台 Tick Engine
    tick_engine.start()

    # 注册信号处理
    def handle_signal(signum, frame):
        sig_name = signal.Signals(signum).name
        logger.info(f"Received {sig_name}, initiating shutdown...")
        shutdown_requested.set()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    logger.info("Daemon running. Press Ctrl+C or send SIGTERM to stop.")
    logger.info(f"Tick interval: {tick_interval}s")
    logger.info(f"Socket: {SOCKET_PATH}")

    # 主循环等待关闭信号
    try:
        while not shutdown_requested.is_set():
            shutdown_requested.wait(timeout=5)
    finally:
        logger.info("Shutting down...")
        # 保存关机断档
        try:
            entity.last_shutdown_time = time.time()
            entity.last_shutdown_tick = entity.tick
            entity.persist_to_file()
            logger.info(f"[ShutdownEvent] Saved shutdown at tick={entity.tick}")
        except Exception as e:
            logger.warning(f"[ShutdownEvent] Failed: {e}")
        tick_engine.stop()
        http_server.stop()
        ipc_server.stop()
        logger.info("Daemon stopped.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="XIA Long-Term Memory Service")
    parser.add_argument(
        "--tick-interval",
        type=float,
        default=30.0,
        help="后台 tick 间隔（秒），默认 30",
    )
    parser.add_argument(
        "--http-port",
        type=int,
        default=8765,
        help="HTTP API 端口（供 Windows 前端访问），默认 8765",
    )
    parser.add_argument(
        "--ipc-port",
        type=int,
        default=8766,
        help="IPC TCP 端口（Windows），默认 8766",
    )
    parser.add_argument(
        "--train-only",
        action="store_true",
        default=False,
        help="纯语言训练模式：关管线，虚拟状态随机游走，快速铺开词汇量",
    )
    args = parser.parse_args()

    run_daemon(tick_interval=args.tick_interval, http_port=args.http_port, ipc_port=args.ipc_port, train_only=args.train_only)
