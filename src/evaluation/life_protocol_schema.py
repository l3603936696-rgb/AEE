"""
Life Protocol Schema — dataclass + 辅助函数。

提取自 life_protocol.py。
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List


# ── 阈值常量 ────────────────────────────────────────────────────────────────
TH_ENTROPY_MIN = 0.05
TH_ENTROPY_MAX = 0.95
TH_COHERENCE_MIN = 0.20
TH_COHERENCE_MAX = 0.80
TH_STD_MIN = 0.03
TH_BIAS_VARIANCE = 0.01
TH_ATTRACTOR_RECOVERY = 0.6
TH_SHIFT_RATE_MAX = 0.80
TH_BIAS_DIFF = 0.05
TH_SELF_CONSTRAINT_COUNT = 5


@dataclass
class TickMetrics:
    tick: int
    action_type: str = ""
    action_coherence: float = 0.5
    entropy: float = 0.0
    structured_progress: float = 0.0
    loneliness: float = 0.3
    boredom: float = 0.3
    stress: float = 0.1
    unresolved: float = 0.2
    energy: float = 0.8
    long_term_bias: Dict[str, float] = field(default_factory=dict)
    behavior_signature: Dict[str, int] = field(default_factory=dict)
    identity_signal: float = 0.5
    prediction_error: float = 0.5
    phase: str = "normal"


# ── 辅助函数 ────────────────────────────────────────────────────────────────


def _entropy(history: List[float]) -> float:
    if len(history) < 3:
        return 0.0
    dims = ["boredom", "loneliness", "energy", "fatigue"]
    if isinstance(history[0], dict):
        total_var = 0.0
        count = 0
        for dim in dims:
            values = [s.get(dim, 0.5) for s in history if isinstance(s, dict)]
            if not values:
                continue
            mean = sum(values) / len(values)
            var = sum((v - mean) ** 2 for v in values) / len(values)
            total_var += var
            count += 1
        return min(total_var / max(count, 1) * 4, 1.0) if count else 0.0
    return 0.0


def _coherence(history: List[str]) -> float:
    if len(history) < 3:
        return 0.5
    transitions = sum(1 for i in range(len(history) - 1) if history[i] != history[i + 1])
    return 1.0 - transitions / (len(history) - 1)


def _structured_progress(state_history: List[Dict], action_history: List[str]) -> float:
    return _entropy(state_history) * _coherence(action_history)


def _cosine_similarity(a: Dict[str, float], b: Dict[str, float]) -> float:
    keys = set(a.keys()) | set(b.keys())
    dot = sum(a.get(k, 0.0) * b.get(k, 0.0) for k in keys)
    mag_a = math.sqrt(sum(a.get(k, 0.0) ** 2 for k in keys))
    mag_b = math.sqrt(sum(b.get(k, 0.0) ** 2 for k in keys))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return max(0.0, min(1.0, dot / (mag_a * mag_b)))


def _bias_variance(bias: Dict[str, float]) -> float:
    vals = list(bias.values())
    if not vals:
        return 0.0
    mean = sum(vals) / len(vals)
    return sum((v - mean) ** 2 for v in vals) / len(vals)


def _all_close_to_zero(bias: Dict[str, float], threshold: float = 0.05) -> bool:
    return all(abs(v) < threshold for v in bias.values())


def _single_dominant(bias: Dict[str, float]) -> bool:
    if not bias:
        return False
    vals = sorted(bias.values(), key=abs, reverse=True)
    if not vals:
        return False
    dominant = abs(vals[0])
    others = sum(abs(v) for v in vals[1:])
    return dominant > 0.1 and others < 0.05


def _cluster_count(bias: Dict[str, float]) -> int:
    return sum(1 for v in bias.values() if abs(v) > 0.05)
