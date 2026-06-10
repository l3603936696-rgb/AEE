"""
compute_connection Helpers — extracted from compute_connection.py.

Public APIs: compute_connection_depth_ex, compute_loneliness_target_ex.
Private helpers: _compute_experience_bias_ex, _cosine_similarity, _interpolate.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional


# =============================================================================
# Shared Helpers
# =============================================================================

def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _get_param(p: Any, key: str, default: float) -> float:
    if p is None:
        return default
    if hasattr(p, "get"):
        v = p.get(key)
        if v is not None:
            return float(v)
    return default


def _somatic_delta_to_factor(somatic_tone_delta: float) -> float:
    """
    Map somatic_tone delta to connection_depth factor.
    Piecewise linear interpolation: [-1.0,-0.1]->-0.5, [-0.1,0.1]->0.5, [0.1,1.0]->1.0.
    Returns [-0.5, 1.0].
    """
    x_anchors = [-1.0, -0.1, 0.1, 1.0]
    y_anchors = [-0.5, -0.5, 0.5, 1.0]

    if somatic_tone_delta <= x_anchors[0]:
        return y_anchors[0]
    if somatic_tone_delta >= x_anchors[-1]:
        return y_anchors[-1]

    for i in range(len(x_anchors) - 1):
        if x_anchors[i] <= somatic_tone_delta <= x_anchors[i + 1]:
            t = (somatic_tone_delta - x_anchors[i]) / (x_anchors[i + 1] - x_anchors[i])
            return y_anchors[i] + t * (y_anchors[i + 1] - y_anchors[i])
    return 0.5


def _cosine_similarity(a: tuple, b: tuple) -> float:
    """Cosine similarity between two 3D vectors."""
    dot = a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
    norm_a = math.sqrt(a[0] ** 2 + a[1] ** 2 + a[2] ** 2) + 1e-9
    norm_b = math.sqrt(b[0] ** 2 + b[1] ** 2 + b[2] ** 2) + 1e-9
    return dot / (norm_a * norm_b)


def _build_context_vector(
    prediction_error: float,
    somatic_tone_delta: float,
    tension_level: float,
) -> tuple:
    """Build 3D context vector from current state."""
    somatic_factor = _somatic_delta_to_factor(somatic_tone_delta)
    return (
        1.0 - prediction_error,
        somatic_factor,
        1.0 - tension_level,
    )


def _interpolate(x: float, x_anchors: list, y_anchors: list) -> float:
    """Linear table lookup interpolation."""
    if not x_anchors or len(x_anchors) < 2:
        return 0.0
    if x <= x_anchors[0]:
        return y_anchors[0]
    if x >= x_anchors[-1]:
        return y_anchors[-1]
    for i in range(len(x_anchors) - 1):
        if x_anchors[i] <= x <= x_anchors[i + 1]:
            t = (x - x_anchors[i]) / (x_anchors[i + 1] - x_anchors[i])
            return y_anchors[i] + t * (y_anchors[i + 1] - y_anchors[i])
    return y_anchors[-1]


# =============================================================================
# Extended version: compute_connection_depth_ex
# =============================================================================

def _compute_base_connection_depth(
    prediction_error: float,
    somatic_tone_delta: float,
    tension_level: float,
    param_snapshot: Any,
) -> float:
    """Base connection_depth formula (v3.0 + v3.5a weights)."""
    w_pred    = _get_param(param_snapshot, "connection.w_prediction", 1.0)
    w_som     = _get_param(param_snapshot, "connection.w_somatic",    1.0)
    w_tension = _get_param(param_snapshot, "connection.w_tension",   1.0)

    somatic_factor = _somatic_delta_to_factor(somatic_tone_delta)

    numerator = (
        w_pred    * (1.0 - prediction_error) +
        w_som     * somatic_factor +
        w_tension * (1.0 - tension_level)
    )
    denominator = w_pred + w_som + w_tension
    return numerator / denominator


def _compute_experience_bias_ex(
    prediction_error: float,
    somatic_tone_delta: float,
    tension_level: float,
    memory_context: List[Dict[str, Any]],
    param_snapshot: Any,
) -> tuple[float, Dict[str, Any]]:
    """Detailed experience bias (for observation layer)."""
    if not memory_context:
        return 0.0, {
            "positive_similarity": 0.0,
            "negative_similarity": 0.0,
            "bias": 0.0,
            "positive_episodes_count": 0,
            "negative_episodes_count": 0,
        }

    positive_threshold = _get_param(param_snapshot, "connection.positive_threshold", 0.10)
    negative_threshold = _get_param(param_snapshot, "connection.negative_threshold", 0.10)
    positive_strength  = _get_param(param_snapshot, "connection.positive_bias_strength", 0.05)
    negative_strength = _get_param(param_snapshot, "connection.negative_bias_strength", 0.02)

    current_vec = _build_context_vector(prediction_error, somatic_tone_delta, tension_level)

    positive_bias = 0.0
    max_pos_sim = 0.0
    pos_count = 0
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
            max_pos_sim = max(max_pos_sim, sim)
            positive_bias = max(positive_bias, sim * positive_strength)
            pos_count += 1

    negative_bias = 0.0
    max_neg_sim = 0.0
    neg_count = 0
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
            max_neg_sim = max(max_neg_sim, sim)
            negative_bias = max(negative_bias, sim * negative_strength)
            neg_count += 1

    bias = positive_bias - negative_bias
    return bias, {
        "positive_similarity": max_pos_sim,
        "negative_similarity": max_neg_sim,
        "bias": bias,
        "positive_episodes_count": pos_count,
        "negative_episodes_count": neg_count,
    }


def _apply_coherence_modulation(
    connection_depth: float,
    coherence: float,
    loneliness: float,
    param_snapshot: Any,
) -> tuple[float, str, float]:
    """
    Coherence modulation (v3.5c).
    High coherence (>threshold) → amplify; low → attenuate.
    Negative connection_depth + high loneliness → negative damping.
    Returns (effective_depth, mode, factor).
    """
    high_thresh   = _get_param(param_snapshot, "connection.coherence_high_threshold", 0.70)
    low_thresh    = _get_param(param_snapshot, "connection.coherence_low_threshold",  0.30)
    amplify       = _get_param(param_snapshot, "connection.coherence_amplify",      1.30)
    attenuate     = _get_param(param_snapshot, "connection.coherence_attenuate",    0.50)
    damping_floor = _get_param(param_snapshot, "connection.negative_damping_floor", 0.70)
    damping_scale = _get_param(param_snapshot, "connection.damping_scale",          0.30)

    cd = connection_depth
    mode = "none"
    factor = 1.0

    if coherence > high_thresh:
        cd = cd * amplify
        mode = "amplify"
        factor = amplify
    elif coherence < low_thresh:
        cd = cd * attenuate
        mode = "attenuate"
        factor = attenuate

    damping_applied = 1.0
    if cd < 0:
        damping_applied = 1.0 - (loneliness * damping_scale)
        damping_applied = max(damping_applied, damping_floor)
        cd = cd * damping_applied

    return max(-1.0, min(1.0, cd)), mode, factor


def compute_connection_depth_ex(
    prediction_error: float,
    somatic_tone_delta: float,
    tension_level: float,
    memory_context: Optional[List[Dict[str, Any]]],
    recent_deltas: Any,
    loneliness: float,
    param_snapshot: Any,
    coherence_meta: float = 0.5,
) -> tuple[float, Dict[str, float], Dict[str, Any]]:
    """
    Full connection_depth with all intermediates (for observation layer).
    Returns (effective_depth, signature, intermediates).
    """
    if memory_context is None:
        memory_context = []

    w_pred    = _get_param(param_snapshot, "connection.w_prediction", 1.0)
    w_som     = _get_param(param_snapshot, "connection.w_somatic",    1.0)
    w_tension = _get_param(param_snapshot, "connection.w_tension",   1.0)

    somatic_factor = _somatic_delta_to_factor(somatic_tone_delta)
    base_depth = _compute_base_connection_depth(
        prediction_error, somatic_tone_delta, tension_level, param_snapshot
    )

    signature = {
        "prediction": 1.0 - prediction_error,
        "somatic":   somatic_factor,
        "tension":   1.0 - tension_level,
    }

    experience_bias, experience_detail = _compute_experience_bias_ex(
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

    damping_active = connection_depth_effective < 0
    damping_factor = 1.0
    if damping_active:
        damping_scale = _get_param(param_snapshot, "connection.damping_scale", 0.30)
        damping_floor = _get_param(param_snapshot, "connection.negative_damping_floor", 0.70)
        damping_factor = max(damping_floor, 1.0 - (loneliness * damping_scale))

    intermediates = {
        "base_connection_depth": base_depth,
        "w_prediction": w_pred,
        "w_somatic": w_som,
        "w_tension": w_tension,
        "somatic_factor": somatic_factor,
        "prediction_factor": 1.0 - prediction_error,
        "tension_factor": 1.0 - tension_level,
        "experience_bias": experience_bias,
        "depth_after_bias": depth_after_bias,
        "coherence_raw": coherence,
        "coherence_mode": coherence_mode,
        "coherence_factor": coherence_factor,
        "damping_active": damping_active,
        "damping_factor": damping_factor,
        "loneliness_at_time": loneliness,
        "factor_overlap_with_loneliness": {
            "prediction": False,
            "somatic": True,
            "tension": True,
        },
        "experience_detail": experience_detail,
    }

    return connection_depth_effective, signature, intermediates


# =============================================================================
# Extended version: compute_loneliness_target_ex
# =============================================================================

def compute_loneliness_target_ex(
    loneliness_core: float,
    loneliness_surface: float,
    connection_depth_effective: float,
    silence_duration: float,
    social_input_present: bool,
    active_exploration: bool = False,
    param_snapshot: Any = None,
) -> tuple[float, float, Dict[str, Any]]:
    """
    Dual-channel loneliness target (v11.4).
    Returns (core_target, surface_target, intermediates).
    """
    rise_rate_core     = _get_param(param_snapshot, "connection.loneliness_core_rise_rate", 0.003)
    rise_rate_surface = _get_param(param_snapshot, "connection.loneliness_surface_rise_rate", 0.012)
    surface_burn_rate = _get_param(param_snapshot, "connection.loneliness_surface_burn_rate", 0.05)
    rebound_threshold = _get_param(param_snapshot, "connection.loneliness_rebound_threshold", 0.5)
    rebound_spike     = _get_param(param_snapshot, "connection.loneliness_rebound_spike", 0.12)
    rebound_refill    = _get_param(param_snapshot, "connection.loneliness_rebound_refill", 0.3)

    core = loneliness_core
    surface = loneliness_surface
    events = []

    # Channel 1: true loneliness
    if social_input_present:
        relief = core * 0.4
        core = max(0.0, core - relief)
        events.append(f"core_relief={relief:.3f}")
    else:
        core = min(1.0, core + (1.0 - core) * rise_rate_core)

    # Channel 2: surface loneliness (compensation layer)
    if social_input_present:
        surface = 0.0
        events.append("surface_reset")
    elif active_exploration:
        surface = max(0.0, surface - surface_burn_rate)
        events.append(f"surface_burn={surface_burn_rate}")
    else:
        surface = min(1.0, surface + (1.0 - surface) * rise_rate_surface)

    # Channel 3: rebound detection
    if surface < 0.05 and core > rebound_threshold:
        rebound_amount = core * rebound_spike
        core = min(1.0, core + rebound_amount)
        surface = core * rebound_refill
        events.append(f"REBOUND: core+{rebound_amount:.3f} surface_refill={surface:.3f}")

    intermediates = {
        "mode": "dual_channel_v11.4",
        "core_target": round(core, 4),
        "surface_target": round(surface, 4),
        "aggregate": round(min(1.0, core + surface), 4),
        "social_input": social_input_present,
        "active_exploration": active_exploration,
        "rebound_triggered": surface < 0.05 and core > rebound_threshold,
        "events": events,
    }

    return core, surface, intermediates
