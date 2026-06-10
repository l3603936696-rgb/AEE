"""
Update Engine Helpers — extracted from update_engine.py.

Keeps update_engine.py below 400 lines.
"""

import time as _time
from typing import Any, Dict, List, Optional


# =============================================================================
# Generic Helpers
# =============================================================================

def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _clamp(val: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, val))


def _param(p: Any, key: str, default: float) -> float:
    if p is None:
        return default
    if hasattr(p, "get"):
        v = p.get(key)
        if v is not None:
            return float(v)
    return default


# =============================================================================
# Action Type Classification
# =============================================================================

def _is_avoid_action(decision: Optional[Dict[str, Any]]) -> bool:
    if decision is None:
        return False
    action_type = str(decision.get("action_type", "")).strip().lower()
    return action_type in ("idle", "drift", "shallow_social", "avoid")


def _is_positive_action(decision: Optional[Dict[str, Any]]) -> bool:
    if decision is None:
        return False
    action_type = str(decision.get("action_type", "")).strip().lower()
    return action_type in ("explore", "resolve", "seek", "comfort")


# =============================================================================
# Pending Surprises Management
# =============================================================================

def process_pending_surprises(
    pending_surprises: list,
    wm_rules: List[Any],
    current_state: Optional[Dict[str, Any]] = None,
    param_snapshot: Any = None,
) -> tuple:
    """
    Process pending_surprises queue (max 1 per tick).

    Returns:
        (updated_list, resolved_flag, should_remove, episode_to_write)
    """
    if not pending_surprises:
        return [], False, False, None

    from ..world_model_update.resolve import attempt_resolve

    surprise = pending_surprises[0]
    resolved, should_remove, episode = attempt_resolve(
        surprise=surprise,
        wm_rules=wm_rules,
        current_state=current_state,
        param_snapshot=param_snapshot,
    )

    if resolved:
        return pending_surprises[1:], True, False, None
    elif should_remove:
        return pending_surprises[1:], False, True, episode
    else:
        return pending_surprises[1:] + [surprise], False, False, None


# =============================================================================
# Relief Debt
# =============================================================================

def update_relief_debt(
    current_relief_debt: float,
    decision: Optional[Dict[str, Any]],
    state: Dict[str, float],
    p: Dict[str, float],
) -> float:
    """
    Comfort debt evolution (independent from compute ledger).

    Debt: pressure state (boredom + unresolved > threshold) + avoid action
    Repay: face problem (seek / resolve / explore)
    """
    try:
        pressure_threshold = p["pressure_threshold"]
        accum_rate = p["accum_rate"]
        reduce_rate = p["reduce_rate"]

        boredom = state.get("boredom", 0.0)
        unresolved = state.get("unresolved", 0.0)
        pressure = boredom + unresolved

        if pressure > pressure_threshold and _is_avoid_action(decision):
            relief_debt = current_relief_debt + accum_rate
        elif _is_positive_action(decision):
            relief_debt = current_relief_debt - reduce_rate
        else:
            relief_debt = current_relief_debt

        return max(0.0, relief_debt)
    except Exception:
        return current_relief_debt


# =============================================================================
# State-Field Step Helpers (called by update_state)
# =============================================================================

from ..world_model_update.defaults import get_param
from .info_queue import INFO_DIGEST_TO_GAP_RATIO, EXPLORE_IMMEDIATE_GAP_REDUCTION


def _step_loneliness(
    current_state: Dict[str, Any],
    current_loneliness: float,
    injected: set,
    metabolic_seconds: float,
) -> float:
    """Step 4a: loneliness update (v4.0 causal version)."""
    loneliness_override = current_state.get("_loneliness_target_override")
    if loneliness_override is not None:
        return float(loneliness_override)

    has_user_input = (
        current_state.get("raw_input") is not None
        and str(current_state.get("raw_input", "")).strip() != ""
    )
    if has_user_input:
        return _clamp(current_loneliness - 0.1)
    else:
        return _clamp(current_loneliness + 0.01 * metabolic_seconds / 60.0)


def _step_unresolved(
    is_rest: bool,
    current_unresolved: float,
    metabolic_seconds: float,
) -> float:
    """Step 4b: unresolved (rest digests it)."""
    if is_rest:
        unresolved_delta = -0.10 * metabolic_seconds / 60.0
    else:
        unresolved_delta = 0.0
    return _clamp(current_unresolved + unresolved_delta)


def _step_boredom(
    action_type: str,
    current_boredom: float,
    decision: Any,
    metabolic_seconds: float,
) -> float:
    """Step 4c: boredom (exploration reduces, idle increases)."""
    try:
        boredom_natural = 0.002 * metabolic_seconds / 60.0
        if action_type in ("explore", "resolve", "seek", "comfort",
                           "browse", "search", "reach", "write"):
            boredom_delta = -0.06
        elif action_type == "idle" or _is_avoid_action(decision):
            boredom_delta = 0.03
        else:
            boredom_delta = 0.0
        return _clamp(current_boredom + boredom_delta + boredom_natural)
    except Exception:
        return current_boredom


def _step_boredom_futility(
    new_state: Dict[str, Any],
    param_snapshot: Any,
    metabolic_seconds: float,
) -> float:
    """Step 4d: boredom_futility (dopamine闭环)."""
    try:
        current_boredom_futility = _safe_float(new_state.get("boredom_futility"), 0.0)
        dopamine_tone = _safe_float(new_state.get("dopamine_tone"), 0.5)
        stress_val = _safe_float(new_state.get("stress"), 0.0)
        somatic_tone = _safe_float(new_state.get("somatic_tone"), 0.0)

        from .dopamine_tone import compute_boredom_futility_delta
        futility_delta = compute_boredom_futility_delta(
            current_boredom_futility=current_boredom_futility,
            dopamine_tone=dopamine_tone,
            stress=stress_val,
            somatic_tone=somatic_tone,
            idle_seconds=metabolic_seconds,
            param_snapshot=param_snapshot,
        )
        new_boredom_futility = min(1.0, max(0.0, current_boredom_futility + futility_delta))

        oxytocin_tone = _safe_float(new_state.get("oxytocin_tone"), 0.5)
        oxytocin_k = _param(param_snapshot, "boredom_futility.oxytocin_k", 0.005)
        oxytocin_benefit = max(0.0, oxytocin_tone - 0.5) * 2 * oxytocin_k * metabolic_seconds / 60.0
        return max(0.0, new_boredom_futility - oxytocin_benefit)
    except Exception:
        return _safe_float(new_state.get("boredom_futility"), 0.0)


def _step_fatigue(
    action_type: str,
    is_rest: bool,
    is_comfort: bool,
    current_fatigue: float,
    info_queue,
    param_snapshot: Any,
    metabolic_seconds: float,
) -> float:
    """Step 4e: fatigue (exploration accumulates, rest/comfort recovers)."""
    try:
        fatigue_base = current_fatigue
        if action_type in ("explore", "seek"):
            fatigue_delta = 0.04 * metabolic_seconds / 60.0
        elif is_rest:
            queue_backlog = info_queue.get_total_queue_occupancy()
            fatigue_delta = -0.06 * metabolic_seconds / 60.0 * (1.0 + queue_backlog)
        elif is_comfort:
            fatigue_delta = -0.02 * metabolic_seconds / 60.0
        else:
            fatigue_delta = 0.0
        _fatigue_passive = _param(param_snapshot, "fatigue.passive_decay", 0.003) * metabolic_seconds / 60.0
        return _clamp(fatigue_base + fatigue_delta - _fatigue_passive)
    except Exception:
        return current_fatigue


def _step_info_gap(
    action_type: str,
    info_gap: float,
    info_queue,
    metabolic_seconds: float,
) -> float:
    """Step 4f: info_gap (natural accumulation, explore/rest digests)."""
    try:
        info_gap_natural = 0.002 * metabolic_seconds / 60.0
        info_digested = info_queue.get_last_info_processed()
        info_gap_digest = info_digested * INFO_DIGEST_TO_GAP_RATIO
        _is_explore = float(action_type == "explore")
        info_gap_explore = _is_explore * EXPLORE_IMMEDIATE_GAP_REDUCTION
        info_gap_delta = info_gap_natural - info_gap_digest - info_gap_explore
        return _clamp(info_gap + info_gap_delta)
    except Exception:
        return info_gap
