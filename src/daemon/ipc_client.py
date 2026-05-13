"""
IPC Client — 供 channel/chat.py 使用，连接 daemon

- Linux/macOS: Unix Domain Socket
- Windows: TCP Socket
"""

import socket
import sys
import time
from pathlib import Path
from typing import Optional

from .protocol import (
    IPCRequest,
    IPCResponse,
    make_chat_request,
    make_ping_request,
    make_llm_chat_request,
    SOCKET_FILENAME,
)


DATA_DIR = Path(__file__).parent.parent.parent / "data"
SOCKET_PATH = DATA_DIR / SOCKET_FILENAME
IPC_TCP_PORT = 8766  # 与 daemon.py 保持一致


class IPCError(Exception):
    """IPC 层错误"""
    pass


class IPCClient:
    """
    IPC 客户端。

    - Linux/macOS: Unix Domain Socket
    - Windows: TCP Socket
    """

    def __init__(self, timeout_s: float = 30.0) -> None:
        self._sock: Optional[socket.socket] = None
        self._timeout = timeout_s
        self._is_windows = sys.platform == "win32"
        self._connect()

    def _connect(self) -> None:
        """建立 socket 连接"""
        try:
            if self._is_windows:
                self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self._sock.settimeout(self._timeout)
                self._sock.connect(("127.0.0.1", IPC_TCP_PORT))
            else:
                # 先试 Unix socket，WSL 下可能失败 → fallback TCP
                try:
                    self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    self._sock.settimeout(self._timeout)
                    self._sock.connect(str(SOCKET_PATH))
                except (FileNotFoundError, OSError):
                    self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    self._sock.settimeout(self._timeout)
                    self._sock.connect(("127.0.0.1", IPC_TCP_PORT))
        except FileNotFoundError:
            raise IPCError(f"Daemon socket not found at {SOCKET_PATH}. Is the daemon running?")
        except ConnectionRefusedError:
            raise IPCError(f"Connection refused. Is the daemon running on port {IPC_TCP_PORT}?")
        except socket.error as e:
            raise IPCError(f"Failed to connect to daemon: {e}")

    def _send_raw(self, data: str) -> None:
        """发送 JSON 文本"""
        if self._sock is None:
            raise IPCError("Not connected")
        payload = data.encode("utf-8")
        self._sock.sendall(len(payload).to_bytes(4, "big"))
        self._sock.sendall(payload)

    def _recv_raw(self) -> str:
        """接收 JSON 文本（4 字节长度前缀）"""
        if self._sock is None:
            raise IPCError("Not connected")
        header = self._recv_exact(4)
        length = int.from_bytes(header, "big")
        body = self._recv_exact(length)
        return body.decode("utf-8")

    def _recv_exact(self, n: int) -> bytes:
        """精确接收 n 字节"""
        if self._sock is None:
            raise IPCError("Not connected")
        data = b""
        while len(data) < n:
            chunk = self._sock.recv(n - len(data))
            if not chunk:
                raise IPCError("Connection closed by daemon")
            data += chunk
        return data

    def _call(self, request: IPCRequest) -> IPCResponse:
        """发送请求并等待响应"""
        try:
            self._send_raw(request.to_json())
            raw = self._recv_raw()
            return IPCResponse.from_json(raw)
        except socket.timeout:
            raise IPCError(f"Request timed out after {self._timeout}s")
        except socket.error as e:
            raise IPCError(f"Socket error: {e}")

    # ---- Public API ----

    def chat(self, text: str, debug: bool = False) -> dict:
        """
        发送对话请求。

        返回：
            dict — daemon 返回的完整管线结果
        """
        req = make_chat_request(text, debug=debug)
        resp = self._call(req)
        if not resp.ok:
            raise IPCError(resp.error or "Unknown error from daemon")
        return resp.result

    def llm_chat(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str = "qwen2.5:3b",
        temperature: float = 0.8,
        max_tokens: int = 200,
    ) -> dict:
        """
        通过 daemon 内部 Ollama 调用 LLM。

        用于 action_system——daemon 内部网络命名空间与 Ollama 子进程一致，
        避免了沙盒进程无法访问 localhost:11434 的问题。

        返回：
            dict — {"text": "...", "model": "...", "generation_time_ms": N}
        """
        req = make_llm_chat_request(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        resp = self._call(req)
        if not resp.ok:
            raise IPCError(resp.error or "LLM call failed in daemon")
        return resp.result

    def ping(self) -> bool:
        """心跳检查 daemon 是否存活"""
        try:
            req = make_ping_request()
            resp = self._call(req)
            return resp.ok
        except IPCError:
            return False

    def close(self) -> None:
        """关闭连接"""
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    def __enter__(self) -> "IPCClient":
        return self

    def __exit__(self, *args) -> None:
        self.close()
