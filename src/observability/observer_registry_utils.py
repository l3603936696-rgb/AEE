"""
Observability Registry Utils — classify_llm_result, record helpers, observe decorators.

提取自 observability/registry.py。
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Optional

from .observer_registry_schema import (
    _LLM_FAIL_KEYWORDS,
    _LLM_FALLBACK_KEYWORDS,
    _meta_log,
)
from .observer_registry import get_registry


def classify_llm_result(text: Optional[str], error: Optional[str]) -> tuple[str, str]:
    """
    分析 LLM 调用结果，返回 (result_type, reason)。

    result_type:
        "success" : 正常返回
        "fallback": 预期降级（如无 key、超时）
        "failure" : 真正错误
    """
    if text is not None and error is None:
        return "success", ""
    if error is None:
        return "success", ""
    err_lower = error.lower()
    for kw in _LLM_FAIL_KEYWORDS:
        if kw in err_lower:
            return "failure", error[:100]
    for kw in _LLM_FALLBACK_KEYWORDS:
        if kw in err_lower:
            return "fallback", error[:100]
    return "failure", error[:100]


def record_failure(name: str, exc: Exception, category: str = "unknown") -> None:
    """便捷函数：记录一次静默失败。"""
    try:
        get_registry().record_failure(name, exc, category)
    except Exception:
        _meta_log(f"record_failure failed for {name}: {exc}")


def record_success(name: str, category: str = "unknown", duration_ms: float = 0.0) -> None:
    """便捷函数：记录一次成功执行（补心跳）。"""
    try:
        get_registry().record_call(name, category=category, success=True, duration_ms=duration_ms)
    except Exception as exc:
        _meta_log(f"record_success failed for {name}: {exc}")


@contextmanager
def observe_block(name: str, category: str = "unknown"):
    """
    上下文管理器：将 try/except 包装为观测块，成功失败都记录。

    用法：
        with observe_block("s06c:cxg_candidates"):
            result = some_function()

    效果：
        - 成功（无异常）→ record_success(name)
        - 抛出异常 → record_failure(name, exc) → 异常向上传播
        - 自身出错记到 _meta.log
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
            get_registry().record_call(
                name=name, category=category, success=ok,
                duration_ms=dur_ms, error_type=exc_type, error_summary=exc_val,
            )
        except Exception as inner:
            _meta_log(f"observe_block record_call failed for {name}: {inner}")


def observe(name: str, category: str = "unknown"):
    """
    观测装饰器：自动记录函数调用/成功/耗时。

    用法：
        @observe("my_module", category="language")
        def my_func():
            ...
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
                        name=name, category=category, success=ok,
                        duration_ms=dur, error_type=exc_type, error_summary=exc_val,
                    )
                except Exception as inner:
                    _meta_log(f"Observer.record_call failed: {inner}")
        wrapper.__name__ = func.__name__
        wrapper.__doc__ = func.__doc__
        return wrapper
    return decorator
