"""
Observability Registry — Central module registration.

Re-exports from schema + class + utils modules.
Self-test in __main__.
"""

from __future__ import annotations

from .observer_registry_schema import (
    _OBS_DIR,
    _REGISTRY_PATH,
    _META_LOG,
    _PERSIST_COOLDOWN_SEC,
)
from .observer_registry import ObserverRegistry, get_registry, _registry_lock, _registry
from .observer_registry_utils import (
    classify_llm_result,
    record_failure,
    record_success,
    observe_block,
    observe,
)
from .observer_registry_schema import ModuleRecord, LLMCallRecord
from .observer_registry import ObserverRegistry, get_registry, _registry_lock, _registry
from .observer_registry_utils import (
    classify_llm_result,
    record_failure,
    record_success,
    observe_block,
    observe,
)

__all__ = [
    "ModuleRecord",
    "LLMCallRecord",
    "ObserverRegistry",
    "get_registry",
    "classify_llm_result",
    "record_failure",
    "record_success",
    "observe_block",
    "observe",
    "_LLM_FALLBACK_KEYWORDS",
    "_LLM_FAIL_KEYWORDS",
    "_REGISTRY_PATH",
    "_META_LOG",
]


if __name__ == "__main__":
    print("=" * 60)
    print("ObserverRegistry — 单元测试")
    print("=" * 60)

    import AEE.src.observability.registry as _reg_mod
    _orig_cooldown = _reg_mod._PERSIST_COOLDOWN_SEC
    _reg_mod._PERSIST_COOLDOWN_SEC = 0.0
    reg = _reg_mod.ObserverRegistry()
    reg.reset()
    _reg_mod._registry = reg

    reg.set_tick(1)
    reg.record_call("test_module", category="language", success=True, duration_ms=5.0)
    reg.record_call("test_module", category="language", success=True, duration_ms=10.0)
    reg.record_failure("test_module", RuntimeError("test error"), category="language")

    reg.set_tick(2)
    r = reg.get_module("test_module")
    assert r is not None
    assert r.calls == 3, f"expected 3, got {r.calls}"
    assert r.successes == 2, f"expected 2, got {r.successes}"
    assert r.failures == 1, f"expected 1, got {r.failures}"
    assert r.consecutive_failures == 1
    assert r.avg_duration_ms == 5.0
    print(f"  [OK] 模块记录: calls={r.calls} ok={r.successes} fail={r.failures}")

    get_registry().set_tick(3)
    r.health = reg._compute_health(r)
    assert r.health == "active"
    print(f"  [OK] 健康标签(混合->active): {r.health}")

    reg.record_failure("test_fail_only", RuntimeError("always fail"), category="test")
    get_registry().set_tick(5)
    reg.get_module("test_fail_only").health = reg._compute_health(reg.get_module("test_fail_only"))
    assert reg.get_module("test_fail_only").health == "persistent_fail"
    print(f"  [OK] 健康标签(全失败->persistent_fail): {reg.get_module('test_fail_only').health}")

    reg._tick = 11
    r.health = reg._compute_health(r)
    assert r.health == "dormant"
    print(f"  [OK] 健康标签(dormant): {r.health}")

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

    ok, reason = _reg_mod.classify_llm_result("hello", None)
    assert ok == "success"
    ok, reason = _reg_mod.classify_llm_result(None, "DeepSeek timeout (30000ms)")
    assert ok == "fallback"
    ok, reason = _reg_mod.classify_llm_result(None, "DeepSeek API key not set")
    assert ok == "fallback"
    ok, reason = _reg_mod.classify_llm_result(None, "DeepSeek HTTP 401: auth error")
    assert ok == "failure"
    ok, reason = _reg_mod.classify_llm_result(None, "DeepSeek HTTP 500: server error")
    assert ok == "failure"
    ok, reason = _reg_mod.classify_llm_result(None, "balance exceeded")
    assert ok == "fallback"
    print(f"  [OK] LLM降级检测全部通过")

    reg.flush()
    reg2 = get_registry()
    assert "test_module" in reg2._modules
    print(f"  [OK] 持久化/恢复通过")

    summary = reg.get_summary()
    print(f"  [OK] 摘要: {summary}")

    reg.reset()
    _reg_mod._PERSIST_COOLDOWN_SEC = _orig_cooldown

    print()
    print("=" * 60)
    print("全部测试通过 [OK]")
    print("=" * 60)
