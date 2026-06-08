"""
LLM Wrapper — LLM 调用的观测包装层

用 `create_wrapped_llm()` 替换原始的 `create_llm_callable()`，
自动记录每次调用的成功/降级/失败、耗时、错误摘要。
所有 LLM 调用点接入后，可以从注册表统一查看每个调用点的实时状态。

用法：
    from ..observability import create_wrapped_llm
    llm = create_wrapped_llm("reflection_layer")
    text, err = llm(system_prompt=..., user_prompt=...)
"""

from __future__ import annotations

import time
from typing import Any, Callable, Optional, Tuple

from .registry import classify_llm_result, get_registry


def create_wrapped_llm(
    name: str,
    provider: str = "deepseek",
) -> Callable[..., Tuple[Optional[str], Optional[str]]]:
    """
    创建带观测的 LLM callable 包装器。

    参数：
        name    : 调用点名称，用于注册表记录
        provider: 提供商名称（显示用）

    返回：
        一个 callable，签名与 DeepSeekProvider.__call__ 相同：
            (system_prompt, user_prompt, temperature, max_tokens, timeout_ms)
            → (text, error)
        每次调用自动记录到注册表。
    """
    def wrapped(
        system_prompt: str = "",
        user_prompt: str = "",
        temperature: float = 0.8,
        max_tokens: int = 400,
        timeout_ms: float = 30000.0,
    ) -> Tuple[Optional[str], Optional[str]]:
        reg = get_registry()
        start = time.perf_counter()

        # 创建实际 provider
        try:
            from ..llm.providers import DeepSeekProvider
            provider_obj = DeepSeekProvider()
        except Exception as exc:
            # provider 创建失败 → 记录失败
            dur_ms = (time.perf_counter() - start) * 1000.0
            reg.record_llm_call(
                name=name,
                success=False,
                fallback=False,
                duration_ms=dur_ms,
                error_summary=f"provider init failed: {exc}",
                provider=provider,
            )
            return None, f"provider init failed: {exc}"

        # 执行调用
        try:
            text, error = provider_obj(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout_ms=timeout_ms,
            )
        except Exception as exc:
            dur_ms = (time.perf_counter() - start) * 1000.0
            reg.record_llm_call(
                name=name,
                success=False,
                fallback=False,
                duration_ms=dur_ms,
                error_summary=f"call exception: {exc}",
                provider=provider,
            )
            return None, f"call exception: {exc}"

        # 分析结果
        dur_ms = (time.perf_counter() - start) * 1000.0
        result_type, reason = classify_llm_result(text, error)

        if result_type == "success":
            reg.record_llm_call(
                name=name,
                success=True,
                fallback=False,
                duration_ms=dur_ms,
                provider=provider,
            )
        elif result_type == "fallback":
            reg.record_llm_call(
                name=name,
                success=False,
                fallback=True,
                duration_ms=dur_ms,
                error_summary=reason,
                provider=provider,
            )
        else:
            reg.record_llm_call(
                name=name,
                success=False,
                fallback=False,
                duration_ms=dur_ms,
                error_summary=reason,
                provider=provider,
            )

        return text, error

    wrapped.__name__ = f"wrapped_llm_{name}"
    wrapped._obs_name = name  # 供调试用
    return wrapped


def create_wrapped_llm_chain(
    name: str,
    providers: Optional[list] = None,
) -> Callable[..., Tuple[Optional[str], Optional[str]]]:
    """
    创建带观测的 LLM chain callable。

    按顺序尝试各 provider，成功则停，失败继续下一个。
    记录最终结果（成功/降级/失败）。
    """
    if providers is None:
        providers = ["deepseek"]

    def wrapped(
        system_prompt: str = "",
        user_prompt: str = "",
        temperature: float = 0.8,
        max_tokens: int = 400,
        timeout_ms: float = 30000.0,
    ) -> Tuple[Optional[str], Optional[str]]:
        reg = get_registry()
        start = time.perf_counter()
        last_error = ""
        used_provider = ""

        for prov_name in providers:
            try:
                if prov_name == "deepseek":
                    from ..llm.providers import DeepSeekProvider
                    provider_obj = DeepSeekProvider()
                else:
                    continue
            except Exception as exc:
                last_error = f"{prov_name} init failed: {exc}"
                continue

            used_provider = prov_name
            try:
                text, error = provider_obj(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout_ms=timeout_ms,
                )
            except Exception as exc:
                last_error = f"{prov_name} call failed: {exc}"
                continue

            # 分析结果
            dur_ms = (time.perf_counter() - start) * 1000.0
            result_type, reason = classify_llm_result(text, error)

            if result_type == "success":
                reg.record_llm_call(
                    name=name,
                    success=True,
                    fallback=False,
                    duration_ms=dur_ms,
                    provider=used_provider,
                )
                return text, error

            last_error = reason

        # 所有 provider 都失败
        dur_ms = (time.perf_counter() - start) * 1000.0
        # 如果所有失败都是降级（如都超时），标记为 fallback
        all_fallback = all(
            classify_llm_result(None, last_error)[0] == "fallback"
            for _ in providers
        )
        reg.record_llm_call(
            name=name,
            success=False,
            fallback=all_fallback,
            duration_ms=dur_ms,
            error_summary=last_error,
            provider=" -> ".join(providers),
        )
        return None, last_error

    wrapped.__name__ = f"wrapped_llm_chain_{name}"
    return wrapped
