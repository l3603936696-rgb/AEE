"""Sentence Composer Helpers — standalone math helpers for sentence composition."""

from typing import Callable, Dict, List

PROBE_DIMS = (
    "fatigue", "joy", "energy", "somatic_tone", "avoid_drive", "approach_drive",
    "loneliness", "curiosity", "social_satiation", "info_gap", "unresolved",
    "fatigue_rising", "energy_rising", "loneliness_rising",
    "joy_rising", "curiosity_rising", "somatic_tone_rising",
)

def _template_theoretical_max(score_fn: Callable) -> float:
    """
    两遍探针：估计 score_fn 在 [0,1]^n 上的理论最大值。
    ① 单维探针定每维系数正负：coeff_d = f(e_d) - f(全0)。
    ② 把所有正系数维置 1、其余置 0，求 f(best_vec)。
    对线性 score_fn 与 max()-of-非负组合（单调不减）均给出**精确**最大值。
    """
    _zero = {d: 0.0 for d in _PROBE_DIMS}
    base = float(score_fn(_zero))
    _best = dict(_zero)
    for d in _PROBE_DIMS:
        _e = dict(_zero)
        _e[d] = 1.0
        coeff = float(score_fn(_e)) - base
        _best[d] = max(0.0, min(1.0, _best[d] + max(0.0, coeff) / max(abs(coeff), 1e-9)))
    return float(score_fn(_best))


def _precompute_template_scales(templates: List[Dict]) -> None:
    """为每个模板预存封顶除数 _score_divisor = max(理论最大, 1.0)。
    只削高（量纲>1.0 的家族压回 [0,1]），不抬低（≤1.0 的恒等通过）。"""
    for p in templates:
        fn = p.get("score_fn")
        try:
            tmax = _template_theoretical_max(fn) if fn is not None else 1.0
        except Exception:
            tmax = 1.0
        p["_score_divisor"] = max(tmax, 1.0)


_precompute_template_scales(PATTERNS)


# ============================================================================
# 核心函数
# ============================================================================

def _softmax_sample(scores: List[float], temperature: float = 0.4) -> int:
    """
    softmax 概率采样。
    temperature 越高越发散，越低越集中。
    返回选中模板的索引。
    """
    if not scores:
        return 0
    max_s = max(scores)
    weights = [math.exp((s - max_s) / max(temperature, 0.01)) for s in scores]
    total = sum(weights)
    if total < 1e-9:
        return 0
    probs = [w / total for w in weights]
    return random.choices(range(len(scores)), weights=probs, k=1)[0]


