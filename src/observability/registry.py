"""
Observability Registry — 中央模块注册表

单例，记录所有被观测模块的调用/成功/异常/耗时数据。
持久化到 data/observability/_registry.json（独立于 entity_core.json）。

健康标签判定：
    never_executed : calls == 0
    active         : calls > 0 and last_tick >= current_tick - 1
    dormant        : 0 < calls < 5 and last_tick < current_tick - 1
    sleeping      : calls >= 5 and last_tick < current_tick - 20
    persistent_fail: consecutive_failures >= 5
"""

from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ============================================================================
# 数据目录
# ============================================================================

_OBS_DIR = Path(__file__).parent.parent.parent / "data" / "observability"
_OBS_DIR.mkdir(parents=True, exist_ok=True)
_REGISTRY_PATH = _OBS_DIR / "_registry.json"
_META_LOG = _OBS_DIR / "_meta.log"

# 持久化节流：两次写入间隔至少这么多秒
_PERSIST_COOLDOWN_SEC = 5.0

# LLM 降级关键词（匹配 error 字符串）
_LLM_FALLBACK_KEYWORDS = frozenset({
    "timeout",
    "not set",
    "balance",
    "402",
    "quota",
    "rate limit",
    "insufficient quota",
    "429",
})

# LLM 非降级错误关键词（真正失败，非降级）
_LLM_FAIL_KEYWORDS = frozenset({
    "401",
    "403",
    "auth",
    "unauthorized",
    "forbidden",
    "500",
    "502",
    "503",
    "server error",
    "internal server",
})


# ============================================================================
# 数据结构
# ============================================================================

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
    current_mode: str = "unknown"  # "llm" | "fallback" | "unknown"
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


# ============================================================================
# Meta logger — 防静默黑洞
# ============================================================================

_meta_lock = threading.Lock()
_meta_log_errors: List[str] = []
_meta_log_last_flush = 0.0


def _meta_log(msg: str) -> None:
    """向 meta.log 写入观测层自身的错误。"""
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


# ============================================================================
# 注册表单例
# ============================================================================

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
    """
    中央模块注册表。

    线程安全。读/写 JSON 文件，低频持久化（最多每 PERSIST_COOLDOWN_SEC 秒一次）。
    """

    def __init__(self) -> None:
        self._modules: Dict[str, ModuleRecord] = {}
        self._llm_calls: Dict[str, LLMCallRecord] = {}
        self._tick: int = 0
        self._session_start: float = time.time()
        self._last_persist: float = 0.0
        self._persist_lock = threading.Lock()
        self._load()

    # -------------------------------------------------------------------------
    # 持久化
    # -------------------------------------------------------------------------

    def _load(self) -> None:
        if not _REGISTRY_PATH.exists():
            return
        try:
            with open(_REGISTRY_PATH, encoding="utf-8") as f:
                data = json.load(f)
            self._modules = {
                k: ModuleRecord.from_dict(v) for k, v in data.get("modules", {}).items()
            }
            self._llm_calls = {
                k: LLMCallRecord.from_dict(v) for k, v in data.get("llm_calls", {}).items()
            }
            self._tick = int(data.get("last_known_tick", 0))
            self._session_start = float(data.get("session_start", time.time()))
        except Exception as e:
            _meta_log(f"Failed to load registry: {e}. Starting fresh.")

    def persist(self) -> None:
        """低频写入（内部防抖）。"""
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
        """强制写入（供外部调用）。"""
        with self._persist_lock:
            self._last_persist = 0.0
        self._write()
        _flush_meta_log()

    # -------------------------------------------------------------------------
    # Tick 同步
    # -------------------------------------------------------------------------

    def set_tick(self, tick: int) -> None:
        self._tick = tick

    def get_tick(self) -> int:
        return self._tick

    # -------------------------------------------------------------------------
    # 模块调用记录
    # -------------------------------------------------------------------------

    def record_call(
        self,
        name: str,
        category: str = "unknown",
        success: bool = True,
        duration_ms: float = 0.0,
        error_type: str = "",
        error_summary: str = "",
    ) -> None:
        """记录一次模块调用。"""
        now = time.time()
        if name not in self._modules:
            self._modules[name] = ModuleRecord(
                category=category,
                first_tick=self._tick,
                health="never_executed",
            )
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

        # 健康标签
        rec.health = self._compute_health(rec)

        self.persist()

    def record_failure(
        self,
        name: str,
        exc: Exception,
        category: str = "unknown",
    ) -> None:
        """记录一次静默失败（被 try/except 吞掉的异常）。"""
        self.record_call(
            name=name,
            category=category,
            success=False,
            duration_ms=0.0,
            error_type=type(exc).__name__,
            error_summary=str(exc)[:200],
        )

    def _compute_health(self, rec: ModuleRecord) -> str:
        if rec.calls == 0:
            return "never_executed"
        # 全失败（无论次数多少）都不得标 active
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

    # -------------------------------------------------------------------------
    # LLM 调用记录
    # -------------------------------------------------------------------------

    def record_llm_call(
        self,
        name: str,
        success: bool,
        fallback: bool = False,
        duration_ms: float = 0.0,
        error_summary: str = "",
        provider: str = "deepseek",
    ) -> None:
        """记录一次 LLM 调用。"""
        now = time.time()
        if name not in self._llm_calls:
            self._llm_calls[name] = LLMCallRecord(
                category="llm",
                provider=provider,
                health="never_executed",
            )
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

        # 健康标签
        if rec.calls == 0:
            rec.health = "never_executed"
        # 全失败（无论次数多少）都不得标 active/dormant/sleeping
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

    # -------------------------------------------------------------------------
    # 查询
    # -------------------------------------------------------------------------

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
        """清空注册表（测试用）。"""
        with self._persist_lock:
            self._modules.clear()
            self._llm_calls.clear()
            self._tick = 0
            self._session_start = time.time()
            self._last_persist = 0.0  # 强制下次 persist 真正写入
        try:
            if _REGISTRY_PATH.exists():
                _REGISTRY_PATH.unlink()
        except Exception:
            pass


# ============================================================================
# LLM 降级检测
# ============================================================================

def classify_llm_result(
    text: Optional[str],
    error: Optional[str],
) -> tuple[str, str]:
    """
    分析 LLM 调用结果，返回 (result_type, reason)。

    result_type:
        "success"  : 正常返回
        "fallback" : 预期降级（如无 key、超时）
        "failure"  : 真正错误

    reason: 简短原因字符串。
    """
    if text is not None and error is None:
        return "success", ""
    if error is None:
        return "success", ""

    err_lower = error.lower()

    # 优先检查真正失败（非降级）
    for kw in _LLM_FAIL_KEYWORDS:
        if kw in err_lower:
            return "failure", error[:100]

    # 检查降级关键词
    for kw in _LLM_FALLBACK_KEYWORDS:
        if kw in err_lower:
            return "fallback", error[:100]

    # 默认归为失败
    return "failure", error[:100]


# ============================================================================
# 便捷工具
# ============================================================================

def record_failure(
    name: str,
    exc: Exception,
    category: str = "unknown",
) -> None:
    """
    便捷函数：记录一次静默失败（被 try/except 吞掉的异常）。
    等价于 get_registry().record_failure(name, exc, category)。
    """
    try:
        get_registry().record_failure(name, exc, category)
    except Exception:
        _meta_log(f"record_failure failed for {name}: {exc}")


def record_success(
    name: str,
    category: str = "unknown",
    duration_ms: float = 0.0,
) -> None:
    """
    便捷函数：记录一次成功执行（补心跳，打断 consecutive_failures）。
    等价于 get_registry().record_call(name, category=category, success=True, duration_ms=duration_ms)。
    """
    try:
        get_registry().record_call(name, category=category, success=True, duration_ms=duration_ms)
    except Exception as exc:
        _meta_log(f"record_success failed for {name}: {exc}")


# ============================================================================
# 上下文管理器：observe_block
# ============================================================================
from contextlib import contextmanager


@contextmanager
def observe_block(name: str, category: str = "unknown"):
    """
    上下文管理器：将 try/except 包装为观测块，成功失败都记录。

    用法：
        with observe_block("s06c:cxg_candidates"):
            result = some_function()

    效果：
        - 成功执行（无异常）→ record_success(name) → consecutive_failures 清零
        - 抛出异常 → record_failure(name, exc) → consecutive_failures 递增
        - 异常向上传播，不被吞掉
        - 自身出错记到 _meta.log

    优势：比 try/except+record_failure 多覆盖成功路径，避免假警报。
    """
    start = time.perf_counter()
    exc_type = ""
    exc_val = ""
    ok = True
    try:
        yield
    except Exception as exc:
        ok = False
        exc_type = type(exc).__name__
        exc_val = str(exc)
        raise
    finally:
        dur_ms = (time.perf_counter() - start) * 1000.0
        try:
            reg = get_registry()
            reg.record_call(
                name=name,
                category=category,
                success=ok,
                duration_ms=dur_ms,
                error_type=exc_type,
                error_summary=exc_val,
            )
        except Exception as inner:
            _meta_log(f"observe_block record_call failed for {name}: {inner}")


def observe(
    name: str,
    category: str = "unknown",
):
    """
    观测装饰器：自动记录函数调用/成功/耗时。

    用法：
        @observe("my_module", category="language")
        def my_func():
            ...

    会记录：
        - 每次调用（calls++）
        - 成功（successes++）或异常（failures++）
        - 耗时（last_duration_ms / avg_duration_ms）
        - 最近一次错误类型和摘要
        - 连续失败计数
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            reg = get_registry()
            start = time.perf_counter()
            exc_type = ""
            exc_val = ""
            ok = True
            try:
                return func(*args, **kwargs)
            except Exception as exc:
                ok = False
                exc_type = type(exc).__name__
                exc_val = str(exc)
                raise
            finally:
                dur = (time.perf_counter() - start) * 1000.0
                try:
                    reg.record_call(
                        name=name,
                        category=category,
                        success=ok,
                        duration_ms=dur,
                        error_type=exc_type,
                        error_summary=exc_val,
                    )
                except Exception as inner:
                    _meta_log(f"Observer.record_call failed: {inner}")

        wrapper.__name__ = func.__name__
        wrapper.__doc__ = func.__doc__
        return wrapper
    return decorator


# ============================================================================
# 测试入口
# ============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("ObserverRegistry — 单元测试")
    print("=" * 60)

    # 用独立实例，避免被旧文件污染
    import src.observability.registry as _reg_mod
    # Patch cooldown=0 so every record_call flushes immediately (clean test isolation)
    _orig_cooldown = _reg_mod._PERSIST_COOLDOWN_SEC
    _reg_mod._PERSIST_COOLDOWN_SEC = 0.0
    reg = _reg_mod.ObserverRegistry()
    reg.reset()  # reset() 也清_last_persist=0，配合cooldown=0保证立即写入
    _reg_mod._registry = reg

    # 基本调用记录
    reg.set_tick(1)
    reg.record_call("test_module", category="language", success=True, duration_ms=5.0)
    reg.record_call("test_module", category="language", success=True, duration_ms=10.0)
    reg.record_failure("test_module", RuntimeError("test error"), category="language")

    reg.set_tick(2)
    r = reg.get_module("test_module")
    assert r is not None, "module should exist"
    assert r.calls == 3, f"expected 3 calls, got {r.calls}"
    assert r.successes == 2, f"expected 2 successes, got {r.successes}"
    assert r.failures == 1, f"expected 1 failure, got {r.failures}"
    assert r.consecutive_failures == 1, f"expected 1, got {r.consecutive_failures}"
    assert r.avg_duration_ms == 5.0, f"expected 5.0, got {r.avg_duration_ms}"
    print(f"  [OK] 模块记录: calls={r.calls} ok={r.successes} fail={r.failures}")

    # 健康标签（混合成功/失败 → active）
    # 注意：必须通过 get_registry() 更新模块级 tick，这样 _compute_health 才能读到正确值
    get_registry().set_tick(3)
    r.health = reg._compute_health(r)
    assert r.health == "active", f"expected active, got {r.health}"
    print(f"  [OK] 健康标签(混合→active): {r.health}")

    # 全失败时无论次数都 → persistent_fail（修复 bug）
    reg.record_failure("test_fail_only", RuntimeError("always fail"), category="test")
    get_registry().set_tick(5)
    reg.get_module("test_fail_only").health = reg._compute_health(reg.get_module("test_fail_only"))
    assert reg.get_module("test_fail_only").health == "persistent_fail", f"all-fail should be persistent_fail, got {reg.get_module('test_fail_only').health}"
    print(f"  [OK] 健康标签(全失败→persistent_fail): {reg.get_module('test_fail_only').health}")

    # tick=11, last_tick=5 → dormant (since 11-5=6 >= 5)
    reg._tick = 11
    r.health = reg._compute_health(r)
    assert r.health == "dormant", f"expected dormant, got {r.health}"
    print(f"  [OK] 健康标签(dormant): {r.health}")

    # LLM 调用记录
    reg.set_tick(5)
    reg.record_llm_call("reflection_layer", success=False, fallback=True, duration_ms=0.0)
    reg.record_llm_call("reflection_layer", success=False, fallback=True, duration_ms=0.0)
    reg.record_llm_call("reflection_layer", success=True, duration_ms=200.0)

    reg.set_tick(6)
    llm = reg.get_llm_call("reflection_layer")
    assert llm is not None
    assert llm.calls == 3
    assert llm.fallbacks == 2
    assert llm.successes == 1
    assert llm.current_mode == "llm"
    print(f"  [OK] LLM记录: calls={llm.calls} ok={llm.successes} fb={llm.fallbacks}")

    # LLM 降级检测
    ok, reason = classify_llm_result("hello", None)
    assert ok == "success"
    ok, reason = classify_llm_result(None, "DeepSeek timeout (30000ms)")
    assert ok == "fallback"
    ok, reason = classify_llm_result(None, "DeepSeek API key not set")
    assert ok == "fallback"
    ok, reason = classify_llm_result(None, "DeepSeek HTTP 401: auth error")
    assert ok == "failure"
    ok, reason = classify_llm_result(None, "DeepSeek HTTP 500: server error")
    assert ok == "failure"
    ok, reason = classify_llm_result(None, "balance exceeded")
    assert ok == "fallback"
    print(f"  [OK] LLM降级检测全部通过")

    # 持久化
    reg.flush()
    reg2 = get_registry()
    assert "test_module" in reg2._modules
    print(f"  [OK] 持久化/恢复通过")

    # 摘要
    summary = reg.get_summary()
    print(f"  [OK] 摘要: {summary}")

    reg.reset()
    print()
    print("=" * 60)
    print("全部测试通过 [OK]")
    print("=" * 60)
