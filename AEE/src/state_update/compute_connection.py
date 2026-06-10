"""
compute_connection.py — connection_depth 计算引擎（v3.0 + v3.5a/b/c）

核心接口：
    compute_connection_depth(
        prediction_error, somatic_tone_delta, tension_level,
        memory_context, recent_deltas, loneliness, param_snapshot,
    ) -> (connection_depth_effective, connection_signature)

    compute_loneliness_target(
        loneliness, connection_depth_effective, silence_duration,
        social_input_present, param_snapshot,
    ) -> target_loneliness

子模块：
    compute_connection_helpers.py — 工具函数 + extended versions
    compute_coherence.py           — coherence 计算
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .compute_connection_helpers import (
    _safe_float, _get_param, _somatic_delta_to_factor,
    _cosine_similarity, _build_context_vector,
    _interpolate,
    _compute_base_connection_depth,
    _compute_experience_bias_ex,
    _apply_coherence_modulation,
    compute_connection_depth_ex,
    compute_loneliness_target_ex,
)


# =============================================================================
# v3.5b: Experience Bias (simple version)
# =============================================================================

def _compute_experience_bias(
    prediction_error: float,
    somatic_tone_delta: float,
    tension_level: float,
    memory_context: List[Dict[str, Any]],
    param_snapshot: Any,
) -> float:
    """
    Retrieve similar historical experiences from memory_context and compute offset.

    Positive offset (loneliness significantly decreased) → connection_depth increases.
    Negative offset (loneliness significantly increased) → connection_depth decreases.
    """
    if not memory_context:
        return 0.0

    positive_threshold = _get_param(param_snapshot, "connection.positive_threshold", 0.10)
    negative_threshold = _get_param(param_snapshot, "connection.negative_threshold", 0.10)
    positive_strength = _get_param(param_snapshot, "connection.positive_bias_strength", 0.05)
    negative_strength = _get_param(param_snapshot, "connection.negative_bias_strength", 0.02)

    current_vec = _build_context_vector(prediction_error, somatic_tone_delta, tension_level)

    positive_bias = 0.0
    for ep in memory_context:
        change = _safe_float(ep.get("loneliness_change"), 0.0)
        if change < -positive_threshold:
            sig = ep.get("signature", {})
            if not sig:
                continue
            ep_vec = (
                _safe_float(sig.get("prediction"), 0.5),
                _safe_float(sig.get("somatic"), 0.0),
                _safe_float(sig.get("tension"), 0.5),
            )
            sim = _cosine_similarity(current_vec, ep_vec)
            positive_bias = max(positive_bias, sim * positive_strength)

    negative_bias = 0.0
    for ep in memory_context:
        change = _safe_float(ep.get("loneliness_change"), 0.0)
        if change > negative_threshold:
            sig = ep.get("signature", {})
            if not sig:
                continue
            ep_vec = (
                _safe_float(sig.get("prediction"), 0.5),
                _safe_float(sig.get("somatic"), 0.0),
                _safe_float(sig.get("tension"), 0.5),
            )
            sim = _cosine_similarity(current_vec, ep_vec)
            negative_bias = max(negative_bias, sim * negative_strength)

    return positive_bias - negative_bias


# =============================================================================
# Main Entry Points
# =============================================================================

def compute_connection_depth(
    prediction_error: float,
    somatic_tone_delta: float,
    tension_level: float,
    memory_context: Optional[List[Dict[str, Any]]],
    recent_deltas: Any,
    loneliness: float,
    param_snapshot: Any,
) -> tuple[float, Dict[str, float]]:
    """
    Compute connection_depth (v3.0 + v3.5a/b/c).

    Returns:
        (connection_depth_effective, connection_signature)
        connection_depth_effective ∈ [-1, 1]
    """
    if memory_context is None:
        memory_context = []

    base_depth = _compute_base_connection_depth(
        prediction_error, somatic_tone_delta, tension_level, param_snapshot
    )

    somatic_factor = _somatic_delta_to_factor(somatic_tone_delta)

    signature = {
        "prediction": 1.0 - prediction_error,
        "somatic":   somatic_factor,
        "tension":   1.0 - tension_level,
    }

    experience_bias = _compute_experience_bias(
        prediction_error, somatic_tone_delta, tension_level,
        memory_context, param_snapshot
    )

    depth_after_bias = base_depth + experience_bias

    from .compute_coherence import compute_final_coherence
    coherence = compute_final_coherence(recent_deltas)

    connection_depth_effective, coherence_mode, coherence_factor = _apply_coherence_modulation(
        connection_depth=depth_after_bias,
        coherence=coherence,
        loneliness=loneliness,
        param_snapshot=param_snapshot,
    )

    return connection_depth_effective, signature


def compute_loneliness_target(
    loneliness: float,
    connection_depth_effective: float,
    silence_duration: float,
    social_input_present: bool,
    param_snapshot: Any,
) -> float:
    """
    Compute loneliness target (v4.0: strict causal semantics).

    Physical definition:
        loneliness = resource deprivation variable
        - Increases: silence duration accumulation
        - Decreases: real external other input
        - No natural decay without causal source (autonomy preservation)

    Returns:
        target loneliness ∈ [0, 1]
    """
    if social_input_present:
        return 0.0

    rise_rate = _get_param(param_snapshot, "connection.loneliness_rise_rate", 0.01)
    target = loneliness + (1.0 - loneliness) * rise_rate
    return max(0.0, min(1.0, target))
