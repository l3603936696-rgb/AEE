"""
Observability Registry — ObserverRegistry class + singleton.

提取自 observability/registry.py。
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Dict, Optional

from .observer_registry_schema import (
    _REGISTRY_PATH,
    _PERSIST_COOLDOWN_SEC,
    _meta_log,
    _persist_cooldown,
    _flush_meta_log,
    ModuleRecord,
    LLMCallRecord,
)

_registry_lock = threading.Lock()
_registry: Optional["ObserverRegistry"] = None


def get_registry() -> "ObserverRegistry":
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = ObserverRegistry()
    return _registry


class ObserverRegistry:
    """中央模块注册表。线程安全，低频持久化。"""

    def __init__(self) -> None:
        self._modules: Dict[str, ModuleRecord] = {}
        self._llm_calls: Dict[str, LLMCallRecord] = {}
        self._tick: int = 0
        self._session_start: float = time.time()
        self._last_persist: float = 0.0
        self._persist_lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        if not _REGISTRY_PATH.exists():
            return
        try:
            with open(_REGISTRY_PATH, encoding="utf-8") as f:
                data = json.load(f)
            self._modules = {k: ModuleRecord.from_dict(v) for k, v in data.get("modules", {}).items()}
            self._llm_calls = {k: LLMCallRecord.from_dict(v) for k, v in data.get("llm_calls", {}).items()}
            self._tick = int(data.get("last_known_tick", 0))
            self._session_start = float(data.get("session_start", time.time()))
        except Exception as e:
            _meta_log(f"Failed to load registry: {e}. Starting fresh.")

    def persist(self) -> None:
        now = time.time()
        with self._persist_lock:
            if now - self._last_persist < _PERSIST_COOLDOWN_SEC:
                return
            self._last_persist = now
        self._write()

    def _write(self) -> None:
        try:
            tmp = _REGISTRY_PATH.with_name(f"._registry.{os.getpid()}.tmp")
            data = {
                "modules": {k: v.to_dict() for k, v in self._modules.items()},
                "llm_calls": {k: v.to_dict() for k, v in self._llm_calls.items()},
                "last_known_tick": self._tick,
                "session_start": self._session_start,
            }
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2, default=str)
            tmp.replace(_REGISTRY_PATH)
        except Exception as e:
            _meta_log(f"Failed to persist registry: {e}")

    def flush(self) -> None:
        with self._persist_lock:
            self._last_persist = 0.0
        self._write()
        _flush_meta_log()

    def set_tick(self, tick: int) -> None:
        self._tick = tick

    def get_tick(self) -> int:
        return self._tick

    def record_call(self, name: str, category: str = "unknown", success: bool = True,
                   duration_ms: float = 0.0, error_type: str = "",
                   error_summary: str = "") -> None:
        now = time.time()
        if name not in self._modules:
            self._modules[name] = ModuleRecord(category=category, first_tick=self._tick, health="never_executed")
        rec = self._modules[name]
        rec.calls += 1
        rec.last_tick = self._tick
        rec.last_call_time = now
        if duration_ms >= 0:
            rec.last_duration_ms = duration_ms
            rec.total_duration_ms += duration_ms
            rec.avg_duration_ms = rec.total_duration_ms / rec.calls
        if success:
            rec.successes += 1
            rec.consecutive_failures = 0
            rec.failure_sequence = 0
            rec.last_success_time = now
        else:
            rec.failures += 1
            rec.consecutive_failures += 1
            rec.last_error_type = error_type
            rec.last_error_summary = (error_summary or "")[:200]
            rec.last_failure_time = now
        rec.health = self._compute_health(rec)
        self.persist()

    def record_failure(self, name: str, exc: Exception, category: str = "unknown") -> None:
        self.record_call(name=name, category=category, success=False, duration_ms=0.0,
                         error_type=type(exc).__name__, error_summary=str(exc)[:200])

    def _compute_health(self, rec: ModuleRecord) -> str:
        if rec.calls == 0:
            return "never_executed"
        if rec.successes == 0 and rec.calls > 0:
            return "persistent_fail"
        if rec.consecutive_failures >= 5:
            return "persistent_fail"
        if self._tick <= 0:
            return "unknown"
        if rec.last_tick >= self._tick - 1:
            return "active"
        if rec.calls < 5:
            return "dormant"
        return "sleeping"

    def record_llm_call(self, name: str, success: bool, fallback: bool = False,
                        duration_ms: float = 0.0, error_summary: str = "",
                        provider: str = "deepseek") -> None:
        now = time.time()
        if name not in self._llm_calls:
            self._llm_calls[name] = LLMCallRecord(category="llm", provider=provider, health="never_executed")
        rec = self._llm_calls[name]
        rec.calls += 1
        rec.last_tick = self._tick
        rec.last_call_time = now
        rec.provider = provider
        if duration_ms >= 0:
            rec.last_duration_ms = duration_ms
            rec.total_duration_ms += duration_ms
            rec.avg_duration_ms = rec.total_duration_ms / rec.calls
        if success:
            rec.successes += 1
            rec.consecutive_failures = 0
            rec.consecutive_fallbacks = 0
            rec.current_mode = "llm"
        elif fallback:
            rec.fallbacks += 1
            rec.consecutive_fallbacks += 1
            rec.consecutive_failures = 0
            rec.current_mode = "fallback"
        else:
            rec.failures += 1
            rec.consecutive_failures += 1
            rec.consecutive_fallbacks = 0
            rec.current_mode = "failed"
            rec.last_error_summary = (error_summary or "")[:200]
        if rec.calls == 0:
            rec.health = "never_executed"
        elif rec.successes == 0 and rec.calls > 0:
            rec.health = "persistent_fail"
        elif rec.consecutive_failures >= 5:
            rec.health = "persistent_fail"
        elif self._tick > 0 and rec.last_tick >= self._tick - 1:
            rec.health = "active"
        elif rec.calls < 3:
            rec.health = "dormant"
        else:
            rec.health = "sleeping"
        self.persist()

    def get_module(self, name: str) -> Optional[ModuleRecord]:
        return self._modules.get(name)

    def get_llm_call(self, name: str) -> Optional[LLMCallRecord]:
        return self._llm_calls.get(name)

    def all_modules(self) -> Dict[str, ModuleRecord]:
        return dict(self._modules)

    def all_llm_calls(self) -> Dict[str, LLMCallRecord]:
        return dict(self._llm_calls)

    def get_summary(self) -> Dict[str, Any]:
        mod_active = sum(1 for r in self._modules.values() if r.health == "active")
        mod_dormant = sum(1 for r in self._modules.values() if r.health in ("dormant", "sleeping"))
        mod_never = sum(1 for r in self._modules.values() if r.health == "never_executed")
        mod_fail = sum(1 for r in self._modules.values() if r.health == "persistent_fail")
        llm_total = sum(r.calls for r in self._llm_calls.values())
        llm_success = sum(r.successes for r in self._llm_calls.values())
        llm_fallback = sum(r.fallbacks for r in self._llm_calls.values())
        llm_fail = sum(r.failures for r in self._llm_calls.values())
        return {
            "tick": self._tick,
            "session_start": self._session_start,
            "module_counts": {
                "total_tracked": len(self._modules),
                "active": mod_active,
                "dormant_sleeping": mod_dormant,
                "never_executed": mod_never,
                "persistent_fail": mod_fail,
            },
            "llm_summary": {
                "total_calls": llm_total,
                "successes": llm_success,
                "fallbacks": llm_fallback,
                "failures": llm_fail,
                "success_rate": round(llm_success / llm_total, 3) if llm_total > 0 else None,
            },
        }

    def reset(self) -> None:
        with self._persist_lock:
            self._modules.clear()
            self._llm_calls.clear()
            self._tick = 0
            self._session_start = time.time()
            self._last_persist = 0.0
        try:
            if _REGISTRY_PATH.exists():
                _REGISTRY_PATH.unlink()
        except Exception:
            pass
