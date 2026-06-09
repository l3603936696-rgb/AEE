"""
Observability Registry Schema — dataclasses, constants, meta logger.

提取自 observability/registry.py。
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_OBS_DIR = Path(__file__).parent.parent.parent / "data" / "observability"
_OBS_DIR.mkdir(parents=True, exist_ok=True)
_REGISTRY_PATH = _OBS_DIR / "_registry.json"
_META_LOG = _OBS_DIR / "_meta.log"

_PERSIST_COOLDOWN_SEC = 5.0

_LLM_FALLBACK_KEYWORDS = frozenset({
    "timeout", "not set", "balance", "402", "quota", "rate limit",
    "insufficient quota", "429",
})

_LLM_FAIL_KEYWORDS = frozenset({
    "401", "403", "auth", "unauthorized", "forbidden",
    "500", "502", "503", "server error", "internal server",
})


@dataclass
class ModuleRecord:
    calls: int = 0
    successes: int = 0
    failures: int = 0
    first_tick: int = 0
    last_tick: int = 0
    last_call_time: float = 0.0
    avg_duration_ms: float = 0.0
    total_duration_ms: float = 0.0
    last_duration_ms: float = 0.0
    last_error_type: str = ""
    last_error_summary: str = ""
    failure_sequence: int = 0
    consecutive_failures: int = 0
    health: str = "never_executed"
    category: str = "unknown"
    last_success_time: float = 0.0
    last_failure_time: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ModuleRecord":
        known = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)


@dataclass
class LLMCallRecord:
    calls: int = 0
    successes: int = 0
    fallbacks: int = 0
    failures: int = 0
    last_tick: int = 0
    last_call_time: float = 0.0
    avg_duration_ms: float = 0.0
    total_duration_ms: float = 0.0
    last_duration_ms: float = 0.0
    last_error_summary: str = ""
    consecutive_fallbacks: int = 0
    consecutive_failures: int = 0
    current_mode: str = "unknown"
    provider: str = "deepseek"
    health: str = "never_executed"
    category: str = "llm"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LLMCallRecord":
        known = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)


_meta_lock = threading.Lock()
_meta_log_errors: List[str] = []
_meta_log_last_flush = 0.0


def _meta_log(msg: str) -> None:
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    line = f"[{ts}] OBSERVER_INTERNAL: {msg}\n"
    _meta_log_errors.append(line)
    now = time.time()
    global _meta_log_last_flush
    if now - _meta_log_last_flush > _persist_cooldown() or len(_meta_log_errors) > 100:
        _flush_meta_log()
        _meta_log_last_flush = now


def _persist_cooldown() -> float:
    return _PERSIST_COOLDOWN_SEC


def _flush_meta_log() -> None:
    if not _meta_log_errors:
        return
    try:
        with open(_META_LOG, "a", encoding="utf-8") as f:
            f.writelines(_meta_log_errors)
        _meta_log_errors.clear()
    except Exception:
        pass
