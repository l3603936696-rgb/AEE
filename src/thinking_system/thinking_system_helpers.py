"""
Thinking System Helpers — extracted from thinking_system.py.

Core algorithms: dimension extraction, focal rule selection, suggestion inference,
somatic modulation, attention-to-drive mapping.
"""

import random
from typing import Any, Dict, List, Optional, Set


# =============================================================================
# Generic Rule Utilities
# =============================================================================

def _conf(rule: dict) -> float:
    return float(rule.get("confidence") or rule.get("confidence_score") or rule.get("weight") or 0.5)


def _rid(rule: dict) -> str:
    return str(rule.get("id") or rule.get("rule_id") or rule.get("pattern") or str(rule))


def _rules(wm: Optional[dict]) -> List[dict]:
    if not wm or not isinstance(wm, dict):
        return []
    raw = wm.get("matched_rules")
    if isinstance(raw, dict):
        raw = raw.get("rules", [])
    return raw if isinstance(raw, list) else []


def _dominant(dv: dict) -> Optional[str]:
    valid = {k: v for k, v in dv.items() if v and v > 0}
    return max(valid, key=valid.get) if valid else None


# =============================================================================
# Dimension Extraction
# =============================================================================

def _rule_dimensions(rule: dict) -> set:
    """
    Extract dimension set from a rule.

    Prefer expected_deltas keys (precise). Fall back to ASCII text extraction
    only when expected_deltas is absent.
    """
    deltas = rule.get("expected_deltas")
    if isinstance(deltas, dict) and deltas:
        return set(deltas.keys())
    if isinstance(deltas, list) and deltas:
        return {d for d in deltas if isinstance(d, str)}

    dims: Set[str] = set()
    for key in ("content", "context"):
        text = str(rule.get(key, "")).lower()
        for w in text.replace("_", " ").split():
            w = w.strip().strip(".,!?")
            if w and len(w) > 2 and w.isascii():
                dims.add(w)
    return dims


# =============================================================================
# Active Dimension Calculation
# =============================================================================

_DRIVE_STATE_WEIGHTS = {
    "curiosity":             {"approach_drive": 0.4, "info_gap": 0.4, "unresolved": 0.2},
    "info_hunger":           {"info_gap": 0.6, "unresolved": 0.4},
    "obsolescence_anxiety":   {"boredom": 0.5, "boredom_despair": 0.3, "boredom_futility": 0.2},
    "loneliness_drive":      {"loneliness": 0.5, "loneliness_core": 0.3, "loneliness_surface": 0.2},
    "fatigue_avoid":         {"fatigue": 0.4, "stress": 0.3, "energy": 0.3},
}


def _active_dimensions(dv: dict, state: Optional[dict]) -> Set[str]:
    """
    Calculate currently active internal dimensions from drive vector.

    logic:
        - dominant drive contributes most
        - weight vectors from each drive superpose
        - high-value dimensions in state snapshot get extra weight
    """
    if not dv:
        return set()

    active: Dict[str, float] = {}
    for drive, strength in dv.items():
        if strength <= 0:
            continue
        weights = _DRIVE_STATE_WEIGHTS.get(drive, {})
        for dim, w in weights.items():
            active[dim] = active.get(dim, 0.0) + strength * w

    if state:
        for dim, val in state.items():
            try:
                v = max(0.0, min(1.0, float(val)))
                if v > 0.6:
                    active[dim] = active.get(dim, 0.0) + (v - 0.5) * 0.5
            except (TypeError, ValueError):
                pass

    if not active:
        return set()
    max_val = max(active.values()) if active else 1.0
    return {dim for dim, val in active.items() if val >= max_val * 0.3}


# =============================================================================
# Focal Rule Selection
# =============================================================================

MATERIAL_ATTENTION_SCALE: float = 0.5


def _select_focal_rules(
    rules: List[dict],
    active_dims: set,
    params: dict,
    input_context: Optional[Dict[str, Any]] = None,
) -> List[dict]:
    """
    Select rules with highest overlap to active dimensions.

    relevance = |rule_dims ∩ active_dims| / |rule_dims|
    Low-confidence rules have higher urgency. Same relevance shuffled randomly.
    """
    if not rules or not active_dims:
        return _fallback_select(rules, params)

    best_sim = float((input_context or {}).get("best_similarity", 0.0))

    scored: List[tuple] = []
    for r in rules:
        rule_dims = _rule_dimensions(r)
        overlap = len(rule_dims & active_dims)
        total = len(rule_dims) if rule_dims else 1
        relevance = overlap / total if total > 0 else 0.0

        conf = _conf(r)
        urgency = max(0.0, (0.4 - conf) / 0.4) if conf < 0.4 else 0.0
        material_boost = best_sim * relevance * MATERIAL_ATTENTION_SCALE

        score = relevance + urgency * 0.5 + material_boost
        scored.append((r, score, conf, relevance))

    scored.sort(key=lambda x: x[1], reverse=True)

    result: List[dict] = []
    seen_ids: Set[str] = set()
    for r, score, conf, rel in scored:
        rid = _rid(r)
        if rid in seen_ids:
            continue
        result.append(r)
        seen_ids.add(rid)
        if len(result) >= params["max_thinking_steps"]:
            break

    return result


def _fallback_select(rules: List[dict], params: dict) -> List[dict]:
    """Random selection when no active dimension info."""
    if not rules:
        return []
    pool = rules[:]
    result = []
    for _ in range(min(params["max_thinking_steps"], len(pool))):
        if not pool:
            break
        r = random.choice(pool)
        result.append(r)
        pool = [x for x in pool if _rid(x) != _rid(r)]
    return result


# =============================================================================
# Suggestion Generation
# =============================================================================

_SENSITIVE_DIMS_UP = {"approach_drive", "joy", "excitement", "serenity", "energy",
                       "info_gap", "unresolved", "boredom"}
_SENSITIVE_DIMS_DOWN = {"avoid_drive", "fatigue", "stress", "loneliness",
                         "loneliness_core", "loneliness_surface",
                         "sadness", "fear", "anger", "anxiety"}


def _infer_action_type(rule: dict, state: Optional[dict], dv: Optional[dict] = None) -> Optional[str]:
    """
    Continuously compete action types from rule deltas + drives + state.

    All signals contribute weighted votes to a single pool (explore/rest/comfort/seek).
    Final argmax wins. No dominant winner → return None.
    """
    votes: Dict[str, float] = {"explore": 0.0, "rest": 0.0, "comfort": 0.0, "seek": 0.0}

    deltas = rule.get("expected_deltas")
    if deltas and isinstance(deltas, dict):
        for dim, delta in deltas.items():
            try:
                d = float(delta)
            except (TypeError, ValueError):
                continue
            state_val = 0.5
            if state:
                try:
                    state_val = float(state.get(dim, 0.5))
                except (TypeError, ValueError):
                    pass
            if d > 0:
                votes["explore"] += d * (1.0 - state_val * 0.5)
            elif d < 0:
                votes["rest"] += abs(d) * state_val

    if dv:
        _drive_votes = {
            "loneliness_drive":    "comfort",
            "fatigue_avoid":       "rest",
            "obsolescence_anxiety": "seek",
            "curiosity":           "explore",
            "info_hunger":         "seek",
        }
        for drive, action in _drive_votes.items():
            strength = float(dv.get(drive, 0.0))
            votes[action] = votes.get(action, 0.0) + strength * 0.3

    if state:
        for dim, val in state.items():
            try:
                v = float(val)
            except (TypeError, ValueError):
                continue
            if v > 0.5:
                excess = (v - 0.5) * 0.2
                if dim in _SENSITIVE_DIMS_DOWN:
                    votes["rest"] += excess
                elif dim in _SENSITIVE_DIMS_UP:
                    votes["explore"] += excess

    if not any(v > 0.0 for v in votes.values()):
        return None

    best_action = max(votes, key=votes.get)
    best_score = votes[best_action]
    second_score = max((v for a, v in votes.items() if a != best_action), default=0.0)

    if best_score <= 0.0 or best_score < second_score * 1.2:
        return None

    return best_action


def _build_reason(action: str, rule: dict) -> str:
    """Generate suggestion reason from semantic base + rule deltas."""
    try:
        essence = get_action_essence(action)
        deltas = rule.get("expected_deltas", {})
        if deltas and isinstance(deltas, dict):
            parts = []
            for dim, d in deltas.items():
                try:
                    parts.append(interpret_delta(dim, float(d)))
                except (TypeError, ValueError):
                    pass
            if parts:
                return f"{essence}——预期效果：{'，'.join(parts[:2])}"
        return essence
    except Exception:
        _fallback = {
            "explore": "这个方向有发展空间，值得探索",
            "rest": "当前负荷较重，需要缓冲和恢复",
            "seek": "信息缺口明显，需要先搞清楚情况",
            "comfort": "情感需求突出，需要社交连接",
        }
        return _fallback.get(action, "基于当前状态判断")


_DRIVE_ACTION_PAIR = {
    "explore":  ["curiosity", "info_hunger"],
    "seek":     ["info_hunger", "curiosity"],
    "comfort":  ["loneliness_drive"],
    "rest":     ["fatigue_avoid"],
}


def _build_suggestions(
    focal_rules: List[dict],
    dv: dict,
    state: Optional[dict],
    params: dict,
    somatic_signals: Optional[dict],
    attention_weights: Optional[Dict[str, float]],
) -> List[Dict[str, Any]]:
    """Generate suggestions from focal rules + drive field."""
    result: List[Dict[str, Any]] = []

    approach_boost, avoid_boost = _somatic_modulation(somatic_signals)
    drive_attn = _attention_to_drive_boost(attention_weights)

    for rule in focal_rules:
        if len(result) >= params["max_suggestions"]:
            break

        action_type = _infer_action_type(rule, state, dv)
        if not action_type:
            continue

        matched_drives = _DRIVE_ACTION_PAIR.get(action_type, [])
        drive_strength = max(dv.get(d, 0.0) for d in matched_drives) if matched_drives else 0.0

        if drive_strength < params["thinking_activation_threshold"]:
            continue

        base_priority = drive_strength

        if action_type in ("explore", "seek", "comfort"):
            base_priority *= approach_boost
        elif action_type == "rest":
            base_priority *= avoid_boost

        if drive_attn:
            attn_boost = max((drive_attn.get(d, 0.0) for d in matched_drives), default=0.0)
            base_priority *= (1.0 + attn_boost)

        reason = _build_reason(action_type, rule)

        result.append({
            "action": action_type,
            "reason": reason,
            "priority": round(min(1.0, max(0.05, base_priority)), 3),
            "_from_rule": _rid(rule),
        })

    result.sort(key=lambda x: x["priority"], reverse=True)
    return result


# =============================================================================
# Somatic & Attention Modulation
# =============================================================================

def _somatic_modulation(somatic_signals: Optional[dict]) -> tuple:
    """Somatic tone → approach/avoid boost."""
    if not somatic_signals:
        return 1.0, 1.0
    tone = float(somatic_signals.get("tone", 0.0))
    intensity = float(somatic_signals.get("intensity", 0.0))
    scale = 0.5 + intensity * 0.5
    approach_boost = 1.0 + tone * 0.5 * scale
    avoid_boost = 1.0 - tone * 0.5 * scale
    return max(0.3, approach_boost), max(0.3, avoid_boost)


def _attention_to_drive_boost(attention_weights: Optional[Dict[str, float]]) -> Dict[str, float]:
    """
    Convert covariance tracker dimension weights to drive boosts.

    Each drive's boost = max attention weight across its related dimensions.
    """
    if not attention_weights:
        return {}

    boost: Dict[str, float] = {}
    for drive, weights in _DRIVE_STATE_WEIGHTS.items():
        max_w = 0.0
        for dim in weights:
            w = attention_weights.get(dim, 0.0)
            if w > max_w:
                max_w = w
        if max_w > 0.05:
            boost[drive] = round(max_w * 0.5, 4)
    return boost
