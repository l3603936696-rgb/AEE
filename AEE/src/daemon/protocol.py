"""
IPC Protocol — 进程间通信协议定义

协议：Unix Domain Socket + JSON

Socket 文件：data/xia_daemon.sock

请求格式：
{
    "type": "chat" | "status" | "shutdown" | "ping",
    "id": "<uuid>",           # 请求 ID，用于匹配响应
    "payload": { ... }        # 类型相关
}

响应格式：
{
    "type": "chat_response" | "status_response" | "shutdown_ack" | "pong",
    "id": "<uuid>",           # 与请求 ID 一致
    "ok": true | false,
    "result": { ... } | null,
    "error": "<message>" | null,
}


Chat 请求 payload：
{
    "text": "<user_input>",
    "debug": false            # 是否返回完整 trace
}

Chat 响应 result：
{
    "response": { "text": "...", "confidence": 0.x, "generation_time_ms": N },
    "decision": { "action_type": "...", ... },
    "state_snapshot": { "energy": 0.x, ... },
    "tick": N,
    "total_ms": N,
    "trace": [...]            # debug=true 时才填入
}

Status 响应 result：
{
    "pid": N,
    "uptime_s": N,
    "current_tick": N,
    "energy": 0.x,
    "loneliness": 0.x,
    "fatigue": 0.x,
    "last_interaction": "<ISO timestamp>",
    "tick_interval_s": N,
    "ticks_since_start": N,
    "ollama_alive": true | false,
}

LLM Chat 请求 payload：
{
    "system_prompt": "<system_prompt>",
    "user_prompt": "<user_prompt>",
    "model": "<model_name>",
    "temperature": 0.8,
    "max_tokens": 200
}

LLM Chat 响应 result：
{
    "text": "<response_text>",
    "model": "<model>",
    "generation_time_ms": N
}
"""

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Literal, Optional
import json


# ============================================================================
# 协议常量
# ============================================================================

SOCKET_FILENAME = "xia_daemon.sock"
PROTOCOL_VERSION = 1


# ============================================================================
# 请求/响应数据结构
# ============================================================================

@dataclass
class IPCRequest:
    type: Literal["chat", "status", "shutdown", "ping", "llm_chat"]
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(
            {"type": self.type, "id": self.id, "payload": self.payload},
            ensure_ascii=False,
        )

    @classmethod
    def from_json(cls, raw: str) -> "IPCRequest":
        data = json.loads(raw)
        return cls(
            type=data["type"],
            id=data.get("id", str(uuid.uuid4())),
            payload=data.get("payload", {}),
        )


@dataclass
class IPCResponse:
    type: str
    id: str
    ok: bool
    result: Any = None
    error: Optional[str] = None

    def to_json(self) -> str:
        return json.dumps(
            {
                "type": self.type,
                "id": self.id,
                "ok": self.ok,
                "result": self.result,
                "error": self.error,
            },
            ensure_ascii=False,
        )

    @classmethod
    def from_json(cls, raw: str) -> "IPCResponse":
        data = json.loads(raw)
        return cls(
            type=data["type"],
            id=data.get("id", ""),
            ok=data.get("ok", False),
            result=data.get("result"),
            error=data.get("error"),
        )

    @classmethod
    def success(cls, request_id: str, result: Any, response_type: str) -> "IPCResponse":
        return cls(type=response_type, id=request_id, ok=True, result=result)

    @classmethod
    def failure(cls, request_id: str, error: str, response_type: str) -> "IPCResponse":
        return cls(type=response_type, id=request_id, ok=False, error=error)


# ============================================================================
# 协议辅助函数
# ============================================================================

def make_chat_request(text: str, debug: bool = False) -> IPCRequest:
    return IPCRequest(type="chat", payload={"text": text, "debug": debug})


def make_status_request() -> IPCRequest:
    return IPCRequest(type="status")


def make_shutdown_request() -> IPCRequest:
    return IPCRequest(type="shutdown")


def make_ping_request() -> IPCRequest:
    return IPCRequest(type="ping")


def make_llm_chat_request(
    system_prompt: str,
    user_prompt: str,
    model: str = "qwen2.5:3b",
    temperature: float = 0.8,
    max_tokens: int = 200,
) -> IPCRequest:
    return IPCRequest(
        type="llm_chat",
        payload={
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
    )
