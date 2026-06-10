"""
Interpretation Competition — v1.0 (explanation competition mechanism)

Thin entry point. Implementation in submodules:
    interpretation_schema.py  — dataclass definitions
    interpretation_compute.py — scoring & candidate building
"""

import logging
import math
from typing import Dict, List, Optional

from .interpretation_schema import (
    ExperienceCandidate,
    CompetitionResult,
    _COMPETITION_EPS,
    _BASE_EXPERIENCE_CONFIDENCE,
)
from .interpretation_compute import (
    compute_competitive_score,
    _softmax_weights,
    build_candidates_from_stereotype,
    MAX_CANDIDATES,
)

logger = logging.getLogger(__name__)

TENSION_THRESHOLD: float = 1.15
CONFIDENCE_DECAY_RATE: float = 0.001


def run_interpretation_competition(
    input_text: str,
    state_snapshot: Dict[str, float],
    stereotype_context=None,
    spm_resonance: Optional[Dict[str, float]] = None,
    spm_data: Optional[Dict] = None,
) -> CompetitionResult:
    resonance = spm_resonance or {}
    patterns = spm_data.get("patterns", []) if spm_data else []
    named_patterns = [p for p in patterns if p.get("symbol")]

    candidates = build_candidates_from_stereotype(
        input_text=input_text,
        stereotype_context=stereotype_context,
        spm_resonance=resonance,
        named_patterns=named_patterns,
    )

    if not candidates:
        return CompetitionResult(
            winner=None,
            tension_level=0.0,
            tension_type="none",
            candidates=[],
            top_scores=(0.0, 0.0),
        )

    for c in candidates:
        c.competitive_score = compute_competitive_score(c, state_snapshot)

    candidates.sort(key=lambda c: c.competitive_score, reverse=True)

    top_scores = (
        candidates[0].competitive_score,
        candidates[1].competitive_score if len(candidates) > 1 else 0.0,
    )

    s1, s2 = top_scores

    if s1 < _COMPETITION_EPS:
        return CompetitionResult(
            winner=None,
            tension_level=0.0,
            tension_type="none",
            candidates=candidates,
            top_scores=top_scores,
        )

    ratio = s1 / max(s2, _COMPETITION_EPS)

    tension_level = max(0.0, 1.0 - math.log(ratio) / math.log(TENSION_THRESHOLD))
    tension_level = max(0.0, min(1.0, tension_level))

    scores = [c.competitive_score for c in candidates]
    weights = _softmax_weights(scores, temperature=0.3)
    winner_weight = weights[0]

    attractor_w = max(0.0, winner_weight - 0.3) / 0.7
    suspended_w = 1.0 - attractor_w

    suspended_score = tension_level * (1.0 - attractor_w)
    attractor_score = (1.0 - tension_level) * attractor_w + 0.5 * (1.0 - tension_level) * (1.0 - attractor_w)
    tension_type = "suspended" if suspended_score > attractor_score else "attractor"

    winner = candidates[0] if attractor_score > suspended_score else None

    return CompetitionResult(
        winner=winner,
        tension_level=tension_level,
        tension_type=tension_type,
        candidates=candidates,
        top_scores=top_scores,
    )


def run_interpretation_stage(ctx, entity) -> None:
    """
    Pipeline stage: interpretation competition.

    Reads from ctx:
        ctx.raw_input
        ctx.state_snapshot
        ctx._stereotype_context
        ctx._spm_resonance

    Writes to ctx:
        ctx._interpretation_result : CompetitionResult
        ctx._tension_level        : float
    """
    input_text = str(ctx.raw_input or "")
    state_snapshot = ctx.state_snapshot or {}
    stereotype_context = getattr(ctx, "_stereotype_context", None)
    spm_resonance = getattr(ctx, "_spm_resonance", None)
    spm_data = getattr(entity, "_state_pattern_data", {})

    result = run_interpretation_competition(
        input_text=input_text,
        state_snapshot=state_snapshot,
        stereotype_context=stereotype_context,
        spm_resonance=spm_resonance,
        spm_data=spm_data,
    )

    ctx._interpretation_result = result
    ctx._tension_level = result.tension_level if result else 0.0

    entity._last_interpretation_result = result
    entity._last_tension_level = result.tension_level if result else 0.0


def compute_prelinguistic_tension(
    spm_resonance: Optional[Dict[str, float]],
    activated_drive: Optional[Dict[str, float]],
) -> tuple:
    """
    Compute pre-linguistic tension from drive activation and SPM resonance.

    This is the core of "pre-linguistic perturbation":
        drive activation -> internal symbol resonance -> direct tension -> permeates language output

    Differs from interpretation competition tension:
        1. Resonance distribution equilibrium (multiple symbols -> suspension)
        2. Distance between activated drive and existing symbols (novel experience)

    Returns: (tension_level, tension_type)
        tension_level : [0, 1]
        tension_type  : "resonance_dispersion" | "novelty_tension" | "none"
    """
    if not spm_resonance:
        return 0.0, "none"

    resonance_values = list(spm_resonance.values())
    active_values = [v for v in resonance_values if v > 0.01]

    if len(active_values) < 1:
        return 0.0, "none"

    n = len(active_values)
    if n == 1:
        dispersion = 0.0
    else:
        mean = sum(active_values) / n
        variance = sum((v - mean) ** 2 for v in active_values) / n
        std = variance ** 0.5
        dispersion = min(1.0, std / 0.25)

    novelty = 0.0
    if activated_drive and active_values:
        best_symbol = max(spm_resonance, key=spm_resonance.get)
        best_resonance = spm_resonance.get(best_symbol, 0.0)
        novelty = 1.0 - best_resonance

    tension_dispersion = dispersion * 0.6
    tension_novelty = novelty * 0.4
    tension = tension_dispersion + tension_novelty
    tension = min(1.0, max(0.0, tension))

    if tension < 0.05:
        return 0.0, "none"

    if dispersion > novelty:
        return tension, "resonance_dispersion"
    else:
        return tension, "novelty_tension"


_HESITATION_MARKERS = frozenset({
    "……", "嗯", "啊", "呢", "吧",
    "也许", "好像", "大概", "可能", "不知道",
    "似乎", "或许", "说不上来",
})
_EXPLORATION_MARKERS = frozenset({
    "不知道", "也许", "试试", "不清楚", "可能吧",
    "嗯……", "我说不上来", "好像是这样",
})
_CERTAINTY_MARKERS = frozenset({
    "一定", "肯定", "必须", "绝对", "毫无疑问",
    "就是", "当然", "明显", "显然",
})


def apply_prelinguistic_tension(
    scored_candidates: List[tuple],
    tension_level: float,
    tension_type: str,
) -> List[tuple]:
    """
    Inject pre-linguistic tension into candidate word scores.

    resonance_dispersion (suspension tension):
        - Hesitation markers get bonus
        - Short phrases get bonus

    novelty_tension:
        - Exploratory vocabulary gets bonus ("不知道" "也许" "试试")
        - Certainty expressions get penalty
    """
    if tension_level < 0.05 or tension_type == "none":
        return scored_candidates

    adjusted: List[tuple] = []
    for word, score in scored_candidates:
        bonus = 0.0

        if tension_type == "resonance_dispersion":
            if any(m in word for m in _HESITATION_MARKERS):
                bonus += tension_level * 0.12
            if any(m in word for m in _CERTAINTY_MARKERS):
                bonus -= tension_level * 0.08
            if len(word) <= 3:
                bonus += tension_level * 0.04

        elif tension_type == "novelty_tension":
            if any(m in word for m in _EXPLORATION_MARKERS):
                bonus += tension_level * 0.15
            if any(m in word for m in _CERTAINTY_MARKERS):
                bonus -= tension_level * 0.12

        new_score = max(0.0, min(1.0, score + bonus))
        adjusted.append((word, new_score))

    return adjusted


def apply_tension_to_candidates(
    scored_candidates: List[tuple],
    tension_level: float,
    tension_type: str,
) -> List[tuple]:
    """
    Inject interpretation tension into candidate word scores.

    When tension_type == "suspended":
        - Fuzzy/hesitation expressions get bonus
        - High-certainty expressions get penalty
        - Short phrases get bonus

    When tension_type == "attractor":
        - No special modulation (let semantic scores dominate)

    Args:
        scored_candidates: [(word, score), ...]
        tension_level    : [0, 1]
        tension_type     : "suspended" | "attractor" | "none"

    Returns: adjusted [(word, new_score), ...]
    """
    if tension_type != "suspended" or tension_level < 0.05:
        return scored_candidates

    adjusted: List[tuple] = []
    for word, score in scored_candidates:
        bonus = 0.0

        if any(m in word for m in _HESITATION_MARKERS):
            bonus += tension_level * 0.15

        if any(m in word for m in _CERTAINTY_MARKERS):
            bonus -= tension_level * 0.10

        if len(word) <= 3:
            bonus += tension_level * 0.05

        if len(word) >= 10:
            bonus -= tension_level * 0.08

        new_score = max(0.0, min(1.0, score + bonus))
        adjusted.append((word, new_score))

    return adjusted


__all__ = [
    "ExperienceCandidate",
    "CompetitionResult",
    "TENSION_THRESHOLD",
    "MAX_CANDIDATES",
    "CONFIDENCE_DECAY_RATE",
    "compute_competitive_score",
    "run_interpretation_competition",
    "run_interpretation_stage",
    "compute_prelinguistic_tension",
    "apply_prelinguistic_tension",
    "apply_tension_to_candidates",
]
