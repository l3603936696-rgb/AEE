"""
State Pattern Memory Helpers — 核心数学工具函数。

包含：余弦相似度、EMA 更新、符号锻造、bootstrap 初始化。
"""

import math
from typing import Dict, List

from .state_pattern_memory_schema import (
    _DIMS,
    _DIM_HIGH_LABELS,
    EMA_ALPHA,
    PATTERN_MIN_HITS,
    _BOOTSTRAP_PATTERNS,
)


def _cosine_similarity(a: Dict[str, float], b: Dict[str, float]) -> float:
    """5D drive 空间余弦相似度。"""
    try:
        av = tuple(float(a.get(d, 0.0)) for d in _DIMS)
        bv = tuple(float(b.get(d, 0.0)) for d in _DIMS)
        dot = sum(x * y for x, y in zip(av, bv))
        mag = math.sqrt(sum(x * x for x in av)) * math.sqrt(sum(x * x for x in bv))
        return dot / mag if mag > 1e-9 else 0.0
    except Exception:
        return 0.0


def _ema_update(center: Dict[str, float], new_vec: Dict[str, float]) -> Dict[str, float]:
    """指数移动平均更新质心。"""
    return {
        d: center.get(d, 0.0) * (1.0 - EMA_ALPHA) + float(new_vec.get(d, 0.0)) * EMA_ALPHA
        for d in _DIMS
    }


def _forge_symbol(center: Dict[str, float]) -> str:
    """
    从 drive 质心的主导维度锻造内部符号。
    取激活最强的 top-2 维度的标签，生成类似 "∅-好奇孤寂" 的符号。
    激活值低于 0.2 的维度不参与命名（避免生成无意义标签）。
    """
    ranked = sorted(
        [(d, float(center.get(d, 0.0))) for d in _DIMS],
        key=lambda x: x[1],
        reverse=True,
    )
    top = [_DIM_HIGH_LABELS[d] for d, v in ranked[:2] if v > 0.2]
    label = "".join(top) if top else "混沌"
    return f"∅-{label}"


def _bootstrap_spm(spm: "StatePatternMemory", current_tick: int) -> "StatePatternMemory":
    """
    当 SPM 没有任何质心时，用预定义的种子区域初始化。

    每个种子区域的 hit_count = PATTERN_MIN_HITS，使 check_and_forge
    在当前 tick 立即为其锻造内部符号——不等待慢慢积累。

    这样第一个 tick 起，理解链路就有真实符号可用了。
    """
    from .state_pattern_memory_schema import InternalPattern
    for i, center in enumerate(_BOOTSTRAP_PATTERNS):
        spm._patterns.append(InternalPattern(
            center          = dict(center),
            hit_count       = PATTERN_MIN_HITS,
            first_seen_tick = current_tick - len(_BOOTSTRAP_PATTERNS) + i,
            last_seen_tick  = current_tick,
        ))
    return spm
