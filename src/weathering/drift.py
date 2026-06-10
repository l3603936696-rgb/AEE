"""参数漂移 — 常规风化漂移 + 崩塌后急剧漂移。"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .registry import (
    get_driftable,
    list_all,
    TIER_DRIFT_RATES,
    DriftableParam,
)
from .baseline import get_store
from ..observability import DriftEvent, emit_event

logger = logging.getLogger(__name__)


def apply_normal_drift(
    param_path: str,
    current_value: float,
    signal: float,
    tick: int,
) -> float:
    """
    常规风化漂移（每 tick 调用）。

    参数：
        param_path:    参数路径
        current_value: 当前参数值
        signal:        漂移信号，正=向上漂移，负=向下。
        tick:          当前 tick

    返回：
        漂移后的新参数值。
    """
    meta = get_driftable(param_path)
    if meta is None:
        return current_value

    if abs(signal) < 1e-9:
        return current_value

    store = get_store()

    base_rate = TIER_DRIFT_RATES.get(meta.tier, TIER_DRIFT_RATES[2])
    drift_amount = base_rate * signal

    if drift_amount < 0:
        drift_amount *= meta.asymmetry

    spring = store.compute_spring_force(param_path, current_value)
    drift_amount += spring * base_rate

    new_value = current_value + drift_amount
    new_value = max(meta.min_value, min(meta.max_value, new_value))

    baseline = store.update_baseline(param_path, new_value)

    if abs(new_value - current_value) > 1e-8:
        emit_event(DriftEvent(
            tick=tick,
            param_path=param_path,
            old_value=round(current_value, 8),
            new_value=round(new_value, 8),
            drift_source="weathering",
            signal_strength=round(signal, 6),
            baseline=round(baseline, 6),
        ))

    return new_value


def apply_acute_drift(
    param_path: str,
    current_value: float,
    drift_amount: float,
    tick: int,
    source: str = "shattering",
) -> float:
    """
    急剧漂移（崩塌后调用）。

    不受 base_rate 限制，直接偏移指定量。
    仍受 min/max 边界约束。

    参数：
        param_path:   参数路径
        current_value: 当前值
        drift_amount:  漂移量（正或负，由崩塌方向决定）
        tick:          当前 tick
        source:        漂移来源标记

    返回：
        漂移后的新参数值。
    """
    meta = get_driftable(param_path)
    if meta is None:
        return current_value

    store = get_store()

    new_value = current_value + drift_amount
    new_value = max(meta.min_value, min(meta.max_value, new_value))

    baseline = store.get_baseline(param_path)

    if abs(new_value - current_value) > 1e-8:
        emit_event(DriftEvent(
            tick=tick,
            param_path=param_path,
            old_value=round(current_value, 8),
            new_value=round(new_value, 8),
            drift_source=source,
            signal_strength=round(drift_amount, 6),
            baseline=round(baseline, 6),
        ))

    return new_value


def apply_drift_cycle(
    current_params: Dict[str, float],
    drift_signals: Dict[str, float],
    tick: int,
) -> Dict[str, float]:
    """
    批量常规漂移入口（每 N tick 调用一次）。

    参数：
        current_params: {param_path: current_value}，当前参数值。
        drift_signals:  {param_path: signal}，每个参数的漂移信号。
        tick:           当前 tick

    返回：
        {param_path: new_value} — 漂移后的参数值。
    """
    result = {}
    for param in list_all():
        path = param.path
        current = current_params.get(path)
        if current is None:
            continue
        signal = drift_signals.get(path, 0.0)
        result[path] = apply_normal_drift(path, current, signal, tick)

    get_store().save()

    return result
