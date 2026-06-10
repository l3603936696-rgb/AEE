"""
Somatic Concept Map -- 身体感受词汇的驱动力场映射（v10.0）

核心哲学：
    词不是咒语。不是"她说冷所以变冷"，而是"她状态变了所以她说冷"。
    每个锚点词的 delta 向量描述的是"这个词对应什么样的身体状态"——
    不是"这个词会造成什么"。

诊断+帮助模型（闯关游戏式）：
    1. 她状态变化 → 体内某些维度偏离中性
    2. 她尝试用词描述自己的状态（"冷"）
    3. 系统验证：这个词的 somatic profile 是否匹配当前状态？
    4. 匹配 → 她被理解了 → 系统施加反向帮助（抵消冷的效应）→ 奖励
    5. 不匹配 → 无帮助、无奖励 → 她学到这个词不适合这个状态

    这让她学会准确的自省——越准确描述自己，越能获得帮助。

子模块：
    somatic_anchors.py              — 51个锚点词数据（数据模块，豁免400行）
    somatic_concept_map_helpers.py  — BGE传播层 + 聚类辅助函数
    somatic_concept_map.py          — 核心API（匹配验证 + 帮助施加）
"""

import logging
from typing import Any, Dict, Tuple

logger = logging.getLogger(__name__)

from .somatic_concept_map_helpers import (
    get_somatic_delta,
    get_top_matches,
    get_cluster_peers,
    find_closest_anchor,
    list_anchors,
    training_exploration_nudge,
    _get_state_match_score_impl,
    _NEUTRAL_ANCHOR,
)
from .somatic_anchors import SOMATIC_ANCHORS


# =============================================================================
# Core API: Match Scoring
# =============================================================================

def get_state_match_score(
    candidate_word: str,
    drive_state: Dict[str, float],
    top_k: int = 3,
    min_similarity: float = 0.35,
) -> float:
    """
    诊断精度评分——这个词多准确地描述了当前的身体状态？

    返回：
        诊断精度 [0, 1]；无法映射时返回 0.5（中性）
    """
    return _get_state_match_score_impl(
        candidate_word, drive_state, top_k=top_k, min_similarity=min_similarity,
    )


def get_counter_delta(
    word: str,
    scaling: float = 1.0,
) -> Dict[str, float]:
    """
    获取词的"帮助向量"——始终向中性/正常状态拉回。

    原理：
        词描述了一个偏离中性的身体状态。帮助不是选择性地强化或抵消——
        就是归中力。冷 {energy:-0.12, avoid:+0.15} → 帮助 {energy:+0.12, avoid:-0.15}

    返回：
        {dimension: counter_delta} dict
    """
    delta = get_somatic_delta(word)
    if not delta:
        return {}
    return {dim: -d * scaling for dim, d in delta.items()}


def get_match_and_help(
    word: str,
    drive_state: Dict[str, float],
    min_match: float = 0.55,
    help_scaling: float = 0.50,
) -> Tuple[float, Dict[str, float]]:
    """
    一站式：验证诊断精度 + 返回帮助向量。

    v3.2: 连续奖励——帮助强度 = 匹配精度 × help_scaling。
    不再一刀切：精度 0.35 得 35% 帮助，精度 0.85 得 85% 帮助。

    返回：
        (match_score, help_delta_dict)
    """
    match = get_state_match_score(word, drive_state)

    if match >= min_match:
        effective_scaling = help_scaling * match
        help_delta = get_counter_delta(word, scaling=effective_scaling)
        return match, help_delta
    elif match > 0.05:
        effective_scaling = help_scaling * match * 0.3
        help_delta = get_counter_delta(word, scaling=effective_scaling)
        return match, help_delta
    else:
        return match, {}


# =============================================================================
# Core API: Help Application
# =============================================================================

def apply_help_delta(
    word: str,
    entity,
    drive_state: Dict[str, float],
    min_match: float = 0.55,
    help_scaling: float = 0.50,
) -> Dict[str, Any]:
    """
    验证匹配并施加帮助——直接修改 entity 状态。

    这是主循环中"闯关成功"的执行函数：
        1. 计算诊断精度
        2. 如果精度足够 → 施加反向帮助（抵消该词描述的不适）
        3. 如果精度不足 → 不施加任何帮助（无奖励）

    返回：
        {
            "word": str,
            "matched": bool,
            "match_score": float,
            "help_applied": {dim: delta, ...},
            "unresolved_drop": float,
        }
    """
    match, help_delta = get_match_and_help(
        word, drive_state, min_match=min_match, help_scaling=help_scaling
    )

    result = {
        "word": word,
        "matched": False,
        "match_score": round(match, 3),
        "help_applied": {},
        "unresolved_drop": 0.0,
    }

    if help_delta:
        applied = {}
        for dim, delta in help_delta.items():
            if hasattr(entity, dim) and abs(delta) > 1e-6:
                current = float(getattr(entity, dim, 0.0))
                if dim in ("somatic_tone", "prediction_error"):
                    lo, hi = -1.0, 1.0
                else:
                    lo, hi = 0.0, 1.0
                setattr(entity, dim, max(lo, min(hi, current + delta)))
                applied[dim] = round(delta, 3)

        unresolved_drop = match * 0.08
        if hasattr(entity, "unresolved"):
            current_unresolved = float(getattr(entity, "unresolved", 0.5))
            entity.unresolved = max(0.0, current_unresolved - unresolved_drop)

        dim_desc = ", ".join(
            f"{dim}{delta:+.2f}" for dim, delta in sorted(applied.items())[:6]
        )
        event = {
            "type": "somatic_help",
            "word": word,
            "match_score": round(match, 3),
            "help_applied": applied,
            "description": (
                f"你说了'{word}'，精准描述了你当前的身体状态"
                f"（匹配度{match:.0%}）。系统识别了你的诊断，"
                f"帮你抵消了这些不适：{dim_desc}。"
                f"同时你的心事(unresolved)减轻了{unresolved_drop:.3f}——"
                f"被理解本身就是奖励。"
            ),
            "tick": getattr(entity, "tick", 0),
        }
        if hasattr(entity, "_last_help_event"):
            entity._last_help_event = event

        result["matched"] = True
        result["help_applied"] = applied
        result["unresolved_drop"] = round(unresolved_drop, 3)

        logger.debug(
            f"[SomaticMap] ✓ '{word}' matched ({match:.2f}), "
            f"help: {list(applied.keys())[:4]}, "
            f"unresolved -{unresolved_drop:.3f}"
        )
    else:
        logger.debug(
            f"[SomaticMap] ✗ '{word}' no match ({match:.2f} < {min_match})"
        )

    return result


# =============================================================================
# Compatibility aliases
# =============================================================================

get_somatic_expected_score = get_state_match_score
