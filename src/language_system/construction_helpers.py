"""
Construction Helpers — internal helpers for ConstructionLearner.

Extracted from construction_grammar.py to keep the main class below 400 lines.
"""

import random
from typing import Any, Dict, List, Optional

from .construction_schema import (
    ExpressionInstance,
    Construction,
    _BASELINE_EFFICIENCY,
    _MAX_FILLERS_PER_SLOT,
    _MIN_STRENGTH,
    _MAX_CONSTRUCTIONS,
)
from .construction_utils import _infer_anchor_pos

import logging
logger = logging.getLogger(__name__)


# ─── Scoring helpers ────────────────────────────────────────────────────────

def make_construction_score_fn(
    strength: float, affinity: float, drive: float, action_score: float,
) -> callable:
    """Build score_fn for construction candidate ranking."""
    return lambda s: strength * 0.35 + affinity * 0.25 + drive * 0.25 + action_score * 0.15


def make_recursive_score_fn(
    strength: float, affinity: float, drive: float, action_score: float,
) -> float:
    """Score for recursive (compound) construction candidates."""
    return (strength * 0.25 + affinity * 0.15 + drive * 0.20 + action_score * 0.10) * 0.85


# ─── _gap_probe_mutate helpers ─────────────────────────────────────────────

_GAP_MUTATIONS = [
    lambda s, a: s.replace("{anchor}", f"好{{{a}}}啊"),
    lambda s, a: s.replace("{anchor}", f"{{{a}}}得不行"),
    lambda s, a: s.replace("{anchor}", f"{{{a}}}是真的"),
    lambda s, a: s.replace("{anchor}", f"{{{a}}}来着"),
]


def apply_gap_mutate(source_tpl: str, anchor: str) -> Optional[str]:
    """Apply a random mutation to a template string. Returns new template or None."""
    mutate_fn = random.choice(_GAP_MUTATIONS)
    new_tpl = mutate_fn(source_tpl, anchor)
    if new_tpl == source_tpl or "{anchor}" not in new_tpl:
        return None
    return new_tpl


# ─── _update_construction ──────────────────────────────────────────────────

def update_construction_slot(
    cx: Construction,
    inst: ExpressionInstance,
) -> None:
    """Update slot filler affinities from an expression instance (positive/negative)."""
    for i, word in enumerate(inst.fillers):
        if i not in cx.slot_fillers:
            cx.slot_fillers[i] = {}
        fillers = cx.slot_fillers[i]

        old = fillers.get(word, 0.0)
        if inst.efficiency >= _BASELINE_EFFICIENCY:
            fillers[word] = old * 0.7 + inst.efficiency * 0.3
        else:
            decay = 0.10 * (1.0 - inst.efficiency / max(_BASELINE_EFFICIENCY, 0.001))
            fillers[word] = max(0.0, old * (1.0 - decay))

        if len(fillers) > _MAX_FILLERS_PER_SLOT:
            weakest = min(fillers, key=fillers.get)
            del fillers[weakest]


def update_construction_drive_profile(
    cx: Construction,
    inst: ExpressionInstance,
) -> None:
    """Update drive profile from an expression instance (positive/negative)."""
    n = cx.use_count + 1
    alpha = 1.0 / max(n, 1)
    for dim, val in inst.drive_state.items():
        old_val = cx.drive_profile.get(dim, 0.5)
        if inst.efficiency >= _BASELINE_EFFICIENCY:
            weight = min(1.0, inst.efficiency * 3.0)
            cx.drive_profile[dim] = old_val * (1 - alpha * weight) + val * alpha * weight
        else:
            neg_weight = min(1.0, (1.0 - inst.efficiency / max(_BASELINE_EFFICIENCY, 0.001)) * 0.5)
            cx.drive_profile[dim] = old_val * (1 - alpha * neg_weight) + 0.5 * alpha * neg_weight


def update_construction_action(
    cx: Construction,
    inst: ExpressionInstance,
) -> None:
    """Record action context on a construction."""
    _inst_action = getattr(inst, "action_context", "") or ""
    if _inst_action and _inst_action in ("explore", "seek", "avoid", "resolve", "rest"):
        if _inst_action not in cx.action_profile:
            cx.action_profile[_inst_action] = 0
        cx.action_profile[_inst_action] += 1


def update_construction(
    cx: Construction,
    inst: ExpressionInstance,
) -> None:
    """Update a construction from an expression instance (slot fillers + drive profile)."""
    update_construction_slot(cx, inst)
    update_construction_drive_profile(cx, inst)
    cx.use_count += 1
    update_construction_action(cx, inst)


# ─── _prune ────────────────────────────────────────────────────────────────

def prune_weak_constructions(
    constructions: Dict[str, Construction],
    current_tick: int,
) -> None:
    """Remove weak constructions below MIN_STRENGTH with >5 uses, and overflow."""
    to_remove = []
    for schema, cx in constructions.items():
        if cx.strength < _MIN_STRENGTH and cx.use_count > 5:
            to_remove.append(schema)

    for schema in to_remove:
        logger.info(f"[CxG] Pruned weak construction: '{schema}'")
        del constructions[schema]

    if len(constructions) > _MAX_CONSTRUCTIONS:
        sorted_cx = sorted(constructions.items(), key=lambda x: x[1].strength)
        for schema, _ in sorted_cx[:len(sorted_cx) - _MAX_CONSTRUCTIONS]:
            logger.info(f"[CxG] Pruned overflow construction: '{schema}'")
            del constructions[schema]


# ─── _gap_probe_mutate (full) ──────────────────────────────────────────────

def gap_probe_mutate(
    anchor: str,
    drive_state: Dict[str, float],
    register_fn: callable,
) -> Optional[Dict]:
    """
    Probe the template gap and mutate an existing pattern.
    Returns compose_sentence-compatible template dict or None.
    """
    try:
        from ..language_system.sentence_composer import PATTERNS
    except Exception:
        return None

    if not PATTERNS:
        return None

    candidates = []
    for pat in PATTERNS:
        tpl = pat.get("template", "")
        if "{anchor}" not in tpl and "{anchor2}" not in tpl:
            continue
        len_score = max(0.0, 1.0 - abs(len(tpl) - 8) / 20.0)
        candidates.append((len_score, tpl))

    if not candidates:
        return None

    candidates.sort(key=lambda x: x[0], reverse=True)
    _, source_tpl = candidates[0]

    new_tpl = apply_gap_mutate(source_tpl, anchor)
    if not new_tpl:
        return None

    register_fn(new_tpl, drive_state)
    anchor_pos = _infer_anchor_pos(new_tpl)
    return {
        "template": new_tpl,
        "score_fn": lambda s, _sc=0.25: _sc,
        "use_connector": False,
        "anchor_pos": anchor_pos,
        "_from_cxg": True,
        "_gap_probed": True,
    }


# ─── get_stats ─────────────────────────────────────────────────────────────

def get_construction_stats(constructions: Dict[str, Construction]) -> Dict[str, Any]:
    """Return construction library summary for debugging/display."""
    if not constructions:
        return {"count": 0, "schemas": []}
    return {
        "count": len(constructions),
        "schemas": [
            {
                "schema": cx.schema,
                "strength": round(cx.strength, 3),
                "use_count": cx.use_count,
                "slot_count": len(cx.slot_fillers),
                "filler_count": sum(len(f) for f in cx.slot_fillers.values()),
            }
            for cx in sorted(
                constructions.values(),
                key=lambda c: c.strength, reverse=True,
            )[:10]
        ],
    }
