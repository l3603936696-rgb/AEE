"""
Signal Bridge — CovarianceTracker 相关性 → 参数漂移信号

将状态维度与预测误差的相关性翻译为具体参数的漂移方向和强度。
同时提供 emotional_weight 和 contradiction_pressure 工厂函数供 shattering 使用。
"""

from __future__ import annotations

from typing import Any, Callable, Dict

from .registry import get_driftable

# ============================================================================
# 维度 → 参数漂移方向映射
# ============================================================================
#
# 含义：当该维度与预测误差正相关时，参数应向此方向漂移。
# +1 = 维度高误差 → 参数增大，-1 = 维度高误差 → 参数减小。
#
# 例：loneliness 与 prediction_error 正相关 → 社交模型不准确
#     → trust_threshold 应增大（更难信任）
#     → rejection_sensitivity 应增大（更敏感）

DIMENSION_DRIFT_MAP: Dict[str, Dict[str, float]] = {
    "loneliness": {
        "personality.trust_threshold": +1.0,
        "personality.rejection_sensitivity": +1.0,
        "personality.introverted_bias": +0.5,
        "personality.social_risk_weight": +1.0,
    },
    "energy": {
        "personality.recovery_rate": -0.5,
        "llm.temperature": -0.3,
    },
    "fatigue": {
        "decision.survival_override_threshold": -0.5,
        "personality.recovery_rate": -0.3,
    },
    "info_gap": {
        "web_search.info_hunger_threshold": -0.5,
        "personality.novelty_reward": +0.5,
    },
    "danger_level": {
        "decision.survival_override_threshold": -0.8,
        "personality.social_risk_weight": +0.5,
    },
    "avoid_drive": {
        "personality.introverted_bias": +0.5,
        "personality.social_risk_weight": +0.5,
    },
    "approach_drive": {
        "personality.extroverted_bias": +0.3,
        "personality.novelty_reward": +0.3,
    },
    "boredom_despair": {
        "personality.novelty_reward": -0.3,
        "personality.recovery_rate": -0.3,
    },
    "curiosity": {
        "web_search.info_hunger_threshold": -0.3,
        "personality.novelty_reward": +0.5,
    },
}


def correlations_to_drift_signals(
    correlations: Dict[str, float],
    min_abs_correlation: float = 0.1,
) -> Dict[str, float]:
    """
    将 CovarianceTracker.get_correlations() 转换为参数漂移信号。

    参数：
        correlations: {dimension: pearson_r}
        min_abs_correlation: 忽略低于此阈值的相关性

    返回：
        {param_path: signal} 只包含在注册表中的参数。
    """
    signals: Dict[str, float] = {}

    for dim, corr in correlations.items():
        if abs(corr) < min_abs_correlation:
            continue

        mapping = DIMENSION_DRIFT_MAP.get(dim)
        if not mapping:
            continue

        for param_path, direction in mapping.items():
            if get_driftable(param_path) is None:
                continue
            signal = corr * direction
            signals[param_path] = signals.get(param_path, 0.0) + signal

    return signals


def dimensions_to_param_paths(dimensions: list) -> list:
    """
    将规律追踪的维度名列表映射为受影响的可漂移参数路径列表。
    用于崩塌后确定哪些参数应发生急剧漂移。
    """
    affected = set()
    for dim in dimensions:
        mapping = DIMENSION_DRIFT_MAP.get(dim, {})
        for param_path in mapping:
            if get_driftable(param_path) is not None:
                affected.add(param_path)
    return list(affected)


# ============================================================================
# Shattering 辅助：emotional_weight / contradiction_pressure 工厂
# ============================================================================

def make_emotion_weight_fn(entity_state: Dict[str, float]) -> Callable:
    """
    创建情绪权重函数，供 detect_and_process_shattering(get_emotion_fn=...) 使用。

    规律追踪的维度的当前驱动压力越高 → 情绪权重越大 → 崩塌冲击越强。
    返回范围 [0.2, 1.0]。
    """
    drive_pressures = {
        "loneliness": entity_state.get("loneliness", 0.0),
        "energy": max(0.0, 1.0 - entity_state.get("energy", 0.8)),
        "fatigue": entity_state.get("fatigue", 0.0),
        "info_gap": entity_state.get("info_gap", 0.0),
        "danger_level": entity_state.get("danger_level", 0.0),
        "approach_drive": entity_state.get("approach_drive", 0.0),
        "avoid_drive": entity_state.get("avoid_drive", 0.0),
        "unresolved": entity_state.get("unresolved", 0.0),
    }

    def fn(rule: Any) -> float:
        if isinstance(rule, dict):
            deltas = rule.get("expected_deltas", {})
        else:
            deltas = getattr(rule, "expected_deltas", {}) or {}

        if not deltas:
            return 0.3

        total = 0.0
        count = 0
        for dim in deltas:
            if dim in drive_pressures:
                total += drive_pressures[dim]
                count += 1

        if count == 0:
            return 0.3

        avg = total / count
        return 0.2 + avg * 0.8

    return fn


def make_contradiction_fn(
    old_conf_map: Dict[str, float],
    new_conf_map: Dict[str, float],
    normal_decay: float = 0.02,
) -> Callable:
    """
    创建矛盾压力函数，供 detect_and_process_shattering(get_contradiction_fn=...) 使用。

    置信度下降超过正常衰减的部分越大 → 矛盾压力越高。
    返回范围 [0.0, 1.0]。
    """
    def fn(rule_id: str) -> float:
        old_c = old_conf_map.get(rule_id, 0.5)
        new_c = new_conf_map.get(rule_id, old_c)
        drop = max(0.0, old_c - new_c)
        excess = max(0.0, drop - normal_decay)
        return min(1.0, excess / 0.3)

    return fn
