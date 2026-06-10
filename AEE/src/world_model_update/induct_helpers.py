"""
Induct Helpers — helper functions for world_model_update/induct.py.

Pure utility functions with no external dependencies (only stdlib).
"""

from typing import Any, Dict, List, Optional


def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _extract_state(state: Any) -> Dict[str, float]:
    """Safely extract state vector, keeping only whitelisted fields."""
    if not isinstance(state, dict):
        return {}
    return {
        k: _safe_float(v)
        for k, v in state.items()
    }


def _salient_fields(
    deltas: Dict[str, float],
    fields: List[str],
    ratio: float,
) -> List[str]:
    """
    Significance pruning: keep only |delta| >= ratio * max|delta|.

    Rationale: expected_deltas accumulates fields indefinitely through EMA,
    leading to over-constrained predictions. Pruning keeps rules compact
    and verifiable.
    """
    mags = [(f, abs(deltas.get(f, 0.0))) for f in fields]
    max_mag = max((m for _, m in mags), default=0.0)
    floor = max_mag * ratio
    kept = [f for f, m in mags if m >= floor]
    return kept if kept else list(fields)


def _generate_trigger(action_type: str, context_label: str) -> str:
    """Auto-generate trigger field."""
    action = action_type.strip().lower()
    ctx = context_label.strip().lower()
    return f"action_{action}_in_{ctx}"


def _generate_expect_from_deltas(
    deltas: Dict[str, float],
    fields: List[str],
) -> str:
    """Generate expect string from expected changes."""
    parts = []
    for f in fields:
        d = deltas.get(f, 0.0)
        if abs(d) < 0.005:
            parts.append(f"{f}_stable")
        elif d > 0:
            parts.append(f"{f}_increase")
        else:
            parts.append(f"{f}_decrease")
    return "+".join(parts) if parts else "stable"


def _generate_content_from_deltas(
    action_type: str,
    context_label: str,
    deltas: Dict[str, float],
    fields: List[str],
) -> str:
    """Generate content description from expected changes."""
    action = action_type.strip()
    ctx = context_label.strip()
    field_descs = []
    for f in fields:
        d = deltas.get(f, 0.0)
        if d > 0:
            field_descs.append(f"{f}↑{d:.3f}")
        elif d < 0:
            field_descs.append(f"{f}↓{abs(d):.3f}")
        else:
            field_descs.append(f"{f}→0")
    return f"{ctx}时{action}→{','.join(field_descs)}"


def _infer_context_label(
    pre_state: Dict[str, float],
    context_dimensions: List[str],
) -> str:
    """Infer context label from pre_state for trigger generation."""
    parts = []
    for dim in context_dimensions:
        val = pre_state.get(dim, 0.5)
        direction = "高" if val >= 0.5 else "低"
        parts.append(f"{dim}{direction}")
    return "_".join(parts)


def _get_prediction_error_map(snap) -> Optional[Dict[str, float]]:
    """Safely extract prediction_error_map from a Snap."""
    pe_map = getattr(snap, "prediction_error_map", None)
    if pe_map and isinstance(pe_map, dict):
        return {str(k): float(v) for k, v in pe_map.items()}

    if isinstance(snap, dict):
        pe_map = snap.get("prediction_error_map")
        if pe_map and isinstance(pe_map, dict):
            return {str(k): float(v) for k, v in pe_map.items()}

    return None
