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
        └── HTTPServer    — HTTP API（供 Windows 前端访问）

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
from .protocol import IPCRequest, IPCResponse
from .tick_engine import TickEngine
from ..entity_zero_iteration import run_pipeline, get_entity_state
from ..llm import create_llm_callable


logger = logging.getLogger(__name__)

# 加载 .env（API keys — DeepSeek）
_ENV_FILE = Path(__file__).parent.parent.parent / ".env"
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

    def __init__(self, tick_engine: TickEngine, llm_callable=None, ipc_port: int = IPC_TCP_PORT) -> None:
        self._tick_engine = tick_engine
        self._llm_callable = llm_callable
        self._server_sock: Optional[socket.socket] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._is_windows = sys.platform == "win32"
        self._ipc_port = ipc_port
        self._listen_addr = f"127.0.0.1:{ipc_port}" if self._is_windows else str(SOCKET_PATH)

    def start(self) -> None:
        """启动 IPC 服务器（在后台线程中运行）"""
        if self._running:
            return

        if self._is_windows:
            # Windows: TCP Socket
            self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
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
            response = self._dispatch(request)
            client.sendall(len(response).to_bytes(4, "big"))
            client.sendall(response.encode("utf-8"))
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
            client.sendall(len(data).to_bytes(4, "big"))
            client.sendall(data)
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
        """处理对话请求"""
        text = request.payload.get("text", "")
        debug = request.payload.get("debug", False)

        entity = get_entity_state()
        result = run_pipeline(
            raw_input=text,
            entity_state=entity,
            debug=debug,
            llm_callable=self._llm_callable,
        )
        return {
            "response": result.get("response", {}),
            "decision": result.get("decision", {}),
            "state_snapshot": result.get("state_snapshot", {}),
            "tick": result.get("tick", entity.tick),
            "total_ms": result.get("total_ms", 0),
            "trace": result.get("trace", []) if debug else [],
        }

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
        time.sleep(0.5)
        self._tick_engine.stop()
        self.stop()
        logger.info("[Daemon] shutdown complete")


# ============================================================================
# HTTP API 服务器 (Windows 兼容)
# ============================================================================

class HTTPServer:
    """
    HTTP API 服务器，供 Windows 上的 Electron 前端访问。

    监听 127.0.0.1:8765，将 HTTP 请求转发到 IPCServer 处理。
    """

    def __init__(self, ipc_server: IPCServer, port: int = 8765) -> None:
        import http.server
        import socketserver

        self._ipc_server = ipc_server
        self._port = port
        self._running = False
        self._thread: Optional[threading.Thread] = None

        class Handler(http.server.BaseHTTPRequestHandler):
            _ipc_server = ipc_server

            def do_POST(self):
                content_length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(content_length)

                try:
                    import json
                    data = json.loads(body.decode('utf-8'))
                    request_type = data.get('type', '')
                    payload = data.get('payload', {})

                    # 构建 IPCRequest
                    from .protocol import IPCRequest
                    req = IPCRequest(type=request_type, id='', payload=payload)
                    result = self._ipc_server._dispatch(req)

                    # 解析响应
                    resp = IPCResponse.from_json(result)

                    self.send_response(200 if resp.ok else 500)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(result.encode('utf-8'))
                except Exception as e:
                    self.send_response(500)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    import json
                    self.wfile.write(json.dumps({'ok': False, 'error': str(e)}).encode('utf-8'))

            def do_GET(self):
                if self.path == '/status':
                    try:
                        status = self._ipc_server._handle_status()
                        import json
                        self.send_response(200)
                        self.send_header('Content-Type', 'application/json')
                        self.end_headers()
                        self.wfile.write(json.dumps(status).encode('utf-8'))
                    except Exception as e:
                        self.send_response(500)
                        self.end_headers()
                        self.wfile.write(str(e).encode('utf-8'))
                elif self.path == '/diary':
                    try:
                        from ..inner_diary import read_diary_entries
                        entries = read_diary_entries(limit=50)
                        data = [e.to_dict() for e in entries]
                        import json
                        self.send_response(200)
                        self.send_header('Content-Type', 'application/json')
                        self.end_headers()
                        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
                    except Exception as e:
                        self.send_response(500)
                        self.end_headers()
                        self.wfile.write(str(e).encode('utf-8'))
                elif self.path.startswith('/logs'):
                    try:
                        import json
                        from urllib.parse import urlparse, parse_qs
                        parsed = urlparse(self.path)
                        params = parse_qs(parsed.query)
                        filename = params.get('file', ['daemon_live.log'])[0]
                        limit = int(params.get('limit', ['200'])[0])
                        from pathlib import Path
                        logs_dir = Path(__file__).parent.parent.parent / "logs"
                        target = (logs_dir / filename).resolve()
                        if not str(target).startswith(str(logs_dir.resolve())):
                            self.send_response(403)
                            self.end_headers()
                            return
                        if target.exists():
                            lines = target.read_text(encoding='utf-8', errors='replace').splitlines()
                            recent = lines[-limit:]
                            self.send_response(200)
                            self.send_header('Content-Type', 'application/json')
                            self.end_headers()
                            self.wfile.write(json.dumps({
                                "file": filename,
                                "total_lines": len(lines),
                                "lines": recent,
                            }, ensure_ascii=False).encode('utf-8'))
                        else:
                            self.send_response(404)
                            self.send_header('Content-Type', 'application/json')
                            self.end_headers()
                            self.wfile.write(json.dumps({"error": "file not found"}).encode('utf-8'))
                    except Exception as e:
                        self.send_response(500)
                        self.end_headers()
                        self.wfile.write(str(e).encode('utf-8'))
                elif self.path == '/vocab':
                    try:
                        import json
                        entity = self._ipc_server._tick_engine.entity
                        unlocked = list(getattr(entity, "_unlocked_vocabulary", []))
                        cluster_weights = dict(getattr(entity, "_cluster_weights", {}))
                        quenching_raw = getattr(entity, "_quenching_data", {})
                        efficiency = {}
                        if isinstance(quenching_raw, dict):
                            records = quenching_raw.get("records", [])
                            for r in records[-200:]:
                                w = r.get("expression", "")
                                e = r.get("efficiency", 0.0)
                                if w:
                                    if w not in efficiency:
                                        efficiency[w] = []
                                    efficiency[w].append(e)
                        word_stats = {
                            w: round(sum(v) / len(v), 3)
                            for w, v in efficiency.items() if v
                        }
                        tl_data = getattr(entity, "_template_learner_data", {})
                        learned_weights = tl_data.get("learned_weights", {}) if isinstance(tl_data, dict) else {}
                        runtime_templates = [
                            {"template": t.get("template", ""), "born_tick": t.get("born_tick", -1)}
                            for t in (tl_data.get("runtime_templates", []) if isinstance(tl_data, dict) else [])
                        ]
                        self.send_response(200)
                        self.send_header('Content-Type', 'application/json')
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.end_headers()
                        self.wfile.write(json.dumps({
                            "unlocked": unlocked,
                            "cluster_weights": cluster_weights,
                            "word_efficiency": word_stats,
                            "learned_template_count": len(learned_weights),
                            "runtime_templates": runtime_templates,
                        }, ensure_ascii=False).encode('utf-8'))
                    except Exception as e:
                        self.send_response(500)
                        self.end_headers()
                        self.wfile.write(str(e).encode('utf-8'))
                else:
                    self.send_response(404)
                    self.end_headers()

            def log_message(self, format, *args):
                logger.info(f"[HTTP] {args[0]}")

        self._Handler = Handler
        self._socketserver = socketserver

    def start(self) -> None:
        """启动 HTTP 服务器（后台线程）"""
        if self._running:
            return

        self._socketserver.TCPServer.allow_reuse_address = True
        self._httpd = self._socketserver.TCPServer(('127.0.0.1', self._port), self._Handler)
        self._running = True

        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info(f"[HTTP API] listening on http://127.0.0.1:{self._port}")

    def _run(self) -> None:
        """运行服务器"""
        while self._running:
            self._httpd.handle_request()

    def stop(self) -> None:
        """停止 HTTP 服务器"""
        self._running = False
        try:
            self._httpd.shutdown()
        except Exception:
            pass


# ============================================================================
# Daemon 主入口
# ============================================================================

def run_daemon(tick_interval: float = 30.0, http_port: int = 8765, ipc_port: int = 8766, train_only: bool = False) -> None:
    """
    启动 XIA 长期记忆服务。

    参数：
        tick_interval : 两次后台 tick 之间的间隔（秒）
    """
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    log_dir = Path(__file__).parent.parent.parent / "logs"
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

    # 初始化 LLM 后端（DeepSeek API）
    llm_callable = create_llm_callable()

    # 初始化组件
    ipc_server = IPCServer(tick_engine=None, llm_callable=llm_callable, ipc_port=ipc_port)
    tick_engine = TickEngine(tick_interval=tick_interval, entity_state=entity, ipc_server=ipc_server, llm_callable=llm_callable, train_only=train_only)
    ipc_server._tick_engine = tick_engine

    # 启动 IPC 服务器
    ipc_server.start()
    logger.info(f"IPC listening on {SOCKET_PATH}")

    # 启动 HTTP API 服务器（供 Windows 前端访问）
    http_server = HTTPServer(ipc_server=ipc_server, port=http_port)
    http_server.start()
    logger.info(f"HTTP API: http://127.0.0.1:{http_port} (for Windows frontend)")

    # 启动后台 Tick Engine
    tick_engine.start()

    # 注册信号处理
    shutdown_requested = threading.Event()

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
