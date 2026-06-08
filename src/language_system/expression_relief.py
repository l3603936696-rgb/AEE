"""
Expression Relief — 前向消力计算（v1.0）

核心思路：
    语言表达的消力效果在说话时即可计算，不依赖事后状态测量。
    消力量 = accuracy × novelty × structure_score × 当前张力强度

    三个输入信号：
        accuracy        — 表达与当前状态的匹配度（somatic_dictionary rough_match）
        novelty         — 新鲜度，直接使用 repetition_discount（0~1）
        structure_score — 结构性 = connector_structure_score × length_shape_score

    boredom_delta    = -relief × boredom    × BOREDOM_RELIEF_GAIN
    unresolved_delta = -relief × unresolved × structure_score × UNRESOLVED_RELIEF_GAIN

v1 约束：
    - 不接 proposition_frame（diagnostics 预留 null 字段供 v2 填入）
    - loneliness 不受影响（自言自语不替代真实关系回应）
    - delta 独立于旧 quenching efficiency 路径，在 quenching.record() 之后施加
"""

import logging
import math
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ─── 增益常量（可由 param_snapshot 覆盖）─────────────────────────────────────
_BOREDOM_RELIEF_GAIN    = 0.04
_UNRESOLVED_RELIEF_GAIN = 0.06

# ─── 连接词权重表（基于 somatic_dictionary.logic 语义分类）──────────────────
# 因果词：info_gap 下降 → 结构最完整，消力最强
# 转折/时序词：处理对立或推进叙事骨架 → 中等
# 对冲词：unresolved 上升 → 结构弱，权重低
_CONNECTOR_WEIGHTS: Dict[str, float] = {
    "因为": 0.80, "所以": 0.80, "原来": 0.80,
    "但是": 0.50, "虽然": 0.50, "其实": 0.50,
    "然后": 0.50, "突然": 0.50, "而且": 0.45,
    "可能": 0.25, "应该": 0.25, "也许": 0.25,
    "大概": 0.25, "好像": 0.25, "如果": 0.25,
    "或者": 0.20,
}

# 只让内容/体感词贡献 accuracy。逻辑词、时间词、程度词和疑问词只提供句法骨架，
# 避免"因为所以但是"这类纯连接词串同时刷 structure 和 accuracy。
_ACCURACY_CATEGORIES = (
    "body",
    "emotion",
    "social",
    "cognitive",
    "existential",
    "micro",
)
_ACCURACY_FLOOR = 0.05

# 无连接词时的基础结构分（单字命名也有轻微消力）
_BASE_STRUCTURE = 0.15

# 长度曲线参数
_LEN_MU    = 8.0
_LEN_SIGMA = 5.0


def _gauss(x: float, mu: float, sigma: float) -> float:
    return math.exp(-0.5 * ((x - mu) / max(sigma, 1e-9)) ** 2)


def _connector_structure_score(expression: str) -> float:
    """
    扫描表达里的逻辑连接词，返回连续结构分 [0.15, 0.80]。
    多个连接词取最高权重（不累加，防止堆词刷分）。
    """
    scores = [_BASE_STRUCTURE]
    scores.extend(weight * float(word in expression) for word, weight in _CONNECTOR_WEIGHTS.items())
    return max(scores)


def _length_shape_score(expression: str) -> float:
    """
    长度形状分（高斯曲线，峰值 8 字）。
    1 字时 ≈ 0.14，8 字时 = 1.0，15 字后平缓下降。
    """
    char_len = len(expression.replace(" ", ""))
    return _gauss(float(char_len), _LEN_MU, _LEN_SIGMA)


def _accuracy_score(expression: str, state: Dict[str, float]) -> float:
    """
    用 somatic_dictionary rough_match 扫描表达里的内容/体感词，取最高匹配分。
    降级：导入失败时返回 0.3（中性）。
    """
    try:
        from .somatic_dictionary import SOMATIC_DICTIONARY, _rough_match
        scores = [_ACCURACY_FLOOR]
        for _cat in _ACCURACY_CATEGORIES:
            entries = SOMATIC_DICTIONARY.get(_cat, {})
            for word, profile in entries.items():
                scores.append(_rough_match(profile, state) * float(word in expression))
        return max(scores)
    except Exception:
        return 0.3


def compute_relief(
    expression: str,
    state: Dict[str, float],
    novelty: float,
    param_snapshot: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    计算表达的前向消力效果。

    参数：
        expression    : 实际说出的表达
        state         : 当前驱动力场（含 boredom、unresolved 等）
        novelty       : 新鲜度，直接传入 repetition_discount（0~1）
        param_snapshot: 参数快照（可覆盖增益常量）

    返回：
        {
            "boredom_delta": float,         # ≤ 0
            "unresolved_delta": float,      # ≤ 0
            "diagnostics": { ... }          # 含 v2 预留字段
        }
    """
    try:
        boredom_gain = float(param_snapshot.get("expression_relief.boredom_gain", _BOREDOM_RELIEF_GAIN))
    except Exception:
        boredom_gain = _BOREDOM_RELIEF_GAIN
    try:
        unresolved_gain = float(param_snapshot.get("expression_relief.unresolved_gain", _UNRESOLVED_RELIEF_GAIN))
    except Exception:
        unresolved_gain = _UNRESOLVED_RELIEF_GAIN

    accuracy         = _accuracy_score(expression, state)
    connector_score  = _connector_structure_score(expression)
    length_score     = _length_shape_score(expression)
    structure_score  = connector_score * length_score
    relief           = accuracy * novelty * structure_score

    boredom    = max(0.0, float(state.get("boredom",    0.0)))
    unresolved = max(0.0, float(state.get("unresolved", 0.0)))

    boredom_delta    = -relief * boredom    * boredom_gain
    unresolved_delta = -relief * unresolved * structure_score * unresolved_gain

    diag: Dict[str, Any] = {
        "accuracy":                 round(accuracy,        4),
        "novelty":                  round(novelty,         4),
        "connector_structure_score": round(connector_score, 4),
        "length_shape_score":        round(length_score,    4),
        "structure_score":           round(structure_score, 4),
        "relief":                    round(relief,          4),
        "boredom_delta":             round(boredom_delta,   5),
        "unresolved_delta":          round(unresolved_delta, 5),
        "proposition_confidence":    None,   # v2 预留
        "role_grounding":            None,   # v2 预留
    }

    logger.debug(
        "[ExpressionRelief] '%s' | acc=%.3f nov=%.3f struct=%.3f"
        " -> b_Δ=%.5f ur_Δ=%.5f",
        expression[:20], accuracy, novelty, structure_score,
        boredom_delta, unresolved_delta,
    )

    return {
        "boredom_delta":    boredom_delta,
        "unresolved_delta": unresolved_delta,
        "diagnostics":      diag,
    }
