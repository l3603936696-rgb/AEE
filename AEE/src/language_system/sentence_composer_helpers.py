"""Sentence Composer Helpers — standalone math helpers for sentence composition."""

from typing import Callable, List
import math
import random

PROBE_DIMS = (
    "fatigue", "joy", "energy", "somatic_tone", "avoid_drive", "approach_drive",
    "loneliness", "curiosity", "social_satiation", "info_gap", "unresolved",
    "fatigue_rising", "energy_rising", "loneliness_rising",
    "joy_rising", "curiosity_rising", "somatic_tone_rising",
)


def _template_theoretical_max(score_fn: Callable) -> float:
    """
    两遍探针：估计 score_fn 在 [0,1]^n 上的理论最大值。
    """
    zero = {d: 0.0 for d in PROBE_DIMS}
    base = float(score_fn(zero))
    best = dict(zero)
    for d in PROBE_DIMS:
        e = dict(zero)
        e[d] = 1.0
        coeff = float(score_fn(e)) - base
        best[d] = max(0.0, min(1.0, best[d] + max(0.0, coeff) / max(abs(coeff), 1e-9)))
    return float(score_fn(best))


def _precompute_template_scales(templates: List) -> None:
    """为每个模板预存封顶除数 _score_divisor = max(理论最大, 1.0)。"""
    for p in templates:
        fn = p.get("score_fn")
        try:
            tmax = _template_theoretical_max(fn) if fn is not None else 1.0
        except Exception:
            tmax = 1.0
        p["_score_divisor"] = max(tmax, 1.0)


def _softmax_sample(scores: List[float], temperature: float = 0.4) -> int:
    """Softmax 概率采样。"""
    if not scores:
        return 0
    max_s = max(scores)
    weights = [math.exp((s - max_s) / max(temperature, 0.01)) for s in scores]
    total = sum(weights)
    if total < 1e-9:
        return 0
    probs = [w / total for w in weights]
    return random.choices(range(len(scores)), weights=probs, k=1)[0]
