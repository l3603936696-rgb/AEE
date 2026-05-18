"""
Feedback Loop — 反馈回路（v1.0）

两层反馈：
    急性层：消力成功 → 对应子驱动力临时提升（靠 0.95/tick 自然衰减，自限性）
    慢性层：连续一致信号 → 参数表微量漂移（双向，需连续确认，总和守恒）

所有系数从 entity._feedback_params 读取。
"""

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

_SUB_DRIVES = ("social", "explore", "urgency")
_SUB_DRIVE_ATTRS = {
    "social": "approach_social",
    "explore": "approach_explore",
    "urgency": "approach_urgency",
}


def _get_dominant_sub_drive(entity: Any) -> str | None:
    vals = {k: getattr(entity, attr, 0.0) for k, attr in _SUB_DRIVE_ATTRS.items()}
    if not any(v > 0 for v in vals.values()):
        return None
    return max(vals, key=vals.get)


def compute_acute_feedback(
    quench_score: float,
    entity: Any,
) -> Dict[str, float]:
    """
    急性层：消力成功 → 产生该表达的子驱动力获得临时提升。

    返回 {entity_attr: delta}，调用方 apply。
    """
    if quench_score <= 0:
        return {}

    params = getattr(entity, "_feedback_params", {})
    scale = params.get("acute_boost_scale", 0.05)

    dominant = _get_dominant_sub_drive(entity)
    if not dominant:
        return {}

    return {_SUB_DRIVE_ATTRS[dominant]: quench_score * scale}


def update_chronic_tracker(
    quench_score: float,
    entity: Any,
) -> None:
    """
    慢性层：记录消力事件。连续一致信号达到阈值 → 参数表微量漂移。

    streak 机制：
        - 消力成功：dominant streak +1，其他衰减
        - 消力失败：全部衰减
        - streak >= threshold → 触发漂移 → streak 归零
    """
    params = getattr(entity, "_feedback_params", {})
    threshold = params.get("chronic_threshold", 5)
    signal_decay = params.get("chronic_signal_decay", 0.9)
    drift_rate = params.get("chronic_drift_rate", 0.002)
    min_quench = params.get("chronic_min_quench", 0.1)

    tracker = getattr(entity, "_chronic_feedback_tracker", None)
    if tracker is None:
        tracker = {k: 0.0 for k in _SUB_DRIVES}

    dominant = _get_dominant_sub_drive(entity)

    if quench_score >= min_quench and dominant:
        for key in _SUB_DRIVES:
            if key == dominant:
                tracker[key] = tracker.get(key, 0.0) + 1.0
            else:
                tracker[key] = tracker.get(key, 0.0) * signal_decay
    else:
        for key in _SUB_DRIVES:
            tracker[key] = tracker.get(key, 0.0) * signal_decay

    for key in _SUB_DRIVES:
        if tracker.get(key, 0.0) >= threshold:
            _apply_chronic_drift(entity, key, drift_rate, params)
            tracker[key] = 0.0
            logger.info(f"[FeedbackLoop] chronic drift: {key} +{drift_rate}")

    entity._chronic_feedback_tracker = tracker


def decay_chronic_tracker(entity: Any) -> None:
    """每 tick 调用：streak 自然衰减，防止零星信号跨长周期累积。"""
    params = getattr(entity, "_feedback_params", {})
    tick_decay = params.get("chronic_tick_decay", 0.98)

    tracker = getattr(entity, "_chronic_feedback_tracker", None)
    if tracker is None:
        return

    for key in _SUB_DRIVES:
        tracker[key] = tracker.get(key, 0.0) * tick_decay

    entity._chronic_feedback_tracker = tracker


def _apply_chronic_drift(
    entity: Any, dominant_key: str, drift_rate: float, params: dict,
) -> None:
    """参数表微量漂移：dominant 上调，其他等比下调，总和守恒。"""
    weights = getattr(entity, "_approach_synthesis_weights", None)
    if weights is None or dominant_key not in weights:
        return

    ceiling = params.get("weight_ceiling", 0.80)
    floor = params.get("weight_floor", 0.05)

    old_val = weights[dominant_key]
    new_val = min(ceiling, old_val + drift_rate)
    increase = new_val - old_val
    if increase <= 0:
        return

    others = {k: v for k, v in weights.items() if k != dominant_key}
    others_sum = sum(others.values())
    if others_sum <= 0:
        return

    for k in others:
        weights[k] = max(floor, others[k] - increase * (others[k] / others_sum))

    weights[dominant_key] = new_val

    total = sum(weights.values())
    if total > 0:
        for k in weights:
            weights[k] = round(weights[k] / total, 6)

    entity._approach_synthesis_weights = weights
