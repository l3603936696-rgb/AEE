"""HTTP API server for local daemon clients."""

from __future__ import annotations

import logging
import threading
from typing import Optional

from .protocol import IPCResponse

logger = logging.getLogger(__name__)
HTTP_REQUEST_POLL_INTERVAL_S = 0.5
HTTP_STOP_JOIN_TIMEOUT_S = 1.0


class HTTPServer:
    """
    HTTP API server for local clients.

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
                        logs_dir = Path(__file__).parent.parent.parent.parent / "logs"
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
        self._httpd.timeout = HTTP_REQUEST_POLL_INTERVAL_S
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
            self._thread.join(timeout=HTTP_STOP_JOIN_TIMEOUT_S)
            self._httpd.server_close()
        except Exception:
            pass


# ============================================================================
# Daemon 主入口
