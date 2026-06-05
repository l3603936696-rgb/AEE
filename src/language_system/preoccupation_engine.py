"""
Preoccupation Engine — 心事系统（v1.0）

她的"心事"——挂在心里的具体念头。

与标量驱动力（fatigue、loneliness）不同，心事是有**对象**、有**时间跨度**的：
    - 担心你
    - 想念妹妹
    - 期待明天

每条心事：
    - 有强度（0-1），自然衰减
    - 会投射到标量状态（"担心你" → stress↑、anxiety↑）
    - 会被输入刷新或安抚
    - 强度太低时自然消失

这让她的内心不只是一组数字，而有具体在想的东西。

设计原则：
    - 纯函数式，不直接修改 entity 状态（投射结果由调用方应用）
    - 全连续，无 if/else 路由
    - 强度上限 1.0，下限 0.05（低于自动消失）
"""

import logging
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ============================================================================
# 心事类型 → 标量状态投射
# ============================================================================
#
# 每个 type 的投射 dict 描述了"强度为 1.0 的这种心事会给状态加多少"。
# 实际 contribution = projection * intensity
#
# 这些数值是状态偏置（在每 tick 被加到 _real_state 上），不是状态本身。
# 量级参考：和 SOMATIC_ANCHORS 同数量级（0.1~0.3）。

TYPE_PROJECTION: Dict[str, Dict[str, float]] = {
    "担心": {
        "stress":     +0.25,
        "anxiety":    +0.20,
        "unresolved": +0.18,
    },
    "想念": {
        "loneliness":     +0.30,
        "somatic_tone":   -0.08,
        "approach_drive": +0.10,
    },
    "期待": {
        "approach_drive": +0.22,
        "curiosity":      +0.15,
        "joy":            +0.08,
    },
    "不安": {
        "anxiety": +0.25,
        "stress":  +0.15,
        "fear":    +0.10,
    },
    "怀念": {
        "loneliness":   +0.15,
        "somatic_tone": +0.05,
        "unresolved":   +0.10,
    },
    "好奇": {
        "curiosity":      +0.30,
        "approach_drive": +0.15,
        "info_gap":       +0.20,
    },
}

# 衰减率：每 tick 强度 *= (1 - DECAY_RATE)
# 0.02 → 50 tick 后衰减到约 37%（30s/tick 时约 25 分钟）
DECAY_RATE = 0.02

# 强度下限——低于此自动消失
MIN_INTENSITY = 0.05

# 强度上限——刷新时不能超过此值
MAX_INTENSITY = 1.0

# 同一 (about, type) 的心事被刷新时强度增量
REFRESH_BOOST = 0.15

# 安抚（soothe）时强度衰减倍率
SOOTHE_FACTOR = 0.4

# 同时存在的心事上限——超过则淘汰最弱的
MAX_PREOCCUPATIONS = 8


# ============================================================================
# 心事的创建 / 刷新 / 安抚
# ============================================================================

def _make_id() -> str:
    """生成唯一 id（短 uuid）。"""
    return uuid.uuid4().hex[:8]


def _find_match(
    preoccupations: List[Dict],
    about: str,
    p_type: str,
) -> Optional[Dict]:
    """查找同一 (about, type) 的已存在心事。"""
    for p in preoccupations:
        if p.get("about") == about and p.get("type") == p_type:
            return p
    return None


def add_or_refresh(
    entity: Any,
    about: str,
    p_type: str,
    initial_intensity: float = 0.5,
) -> Dict:
    """
    添加新心事或刷新已存在的心事。

    若 (about, type) 已存在 → 强度提升 REFRESH_BOOST（不超过 MAX_INTENSITY）+ 更新 last_refresh_tick
    若不存在 → 创建新心事，初始强度 = initial_intensity

    返回：被刷新/创建的心事 dict
    """
    if not about or not p_type:
        return {}
    if p_type not in TYPE_PROJECTION:
        logger.debug(f"[Preoccupation] unknown type: {p_type}")
        return {}

    pre_list = getattr(entity, "_preoccupations", None)
    if pre_list is None:
        pre_list = []
        entity._preoccupations = pre_list

    tick = int(getattr(entity, "tick", 0))
    existing = _find_match(pre_list, about, p_type)

    if existing:
        # 刷新：强度提升 + 时间戳更新
        existing["intensity"] = min(MAX_INTENSITY, float(existing["intensity"]) + REFRESH_BOOST)
        existing["last_refresh_tick"] = tick
        logger.debug(
            f"[Preoccupation] refreshed: {p_type}({about}) → intensity={existing['intensity']:.2f}"
        )
        return existing

    # 创建新心事
    new_p = {
        "id":                _make_id(),
        "about":             about,
        "type":              p_type,
        "intensity":         max(MIN_INTENSITY, min(MAX_INTENSITY, float(initial_intensity))),
        "created_tick":      tick,
        "last_refresh_tick": tick,
    }
    pre_list.append(new_p)

    # 超过上限 → 淘汰强度最弱的
    if len(pre_list) > MAX_PREOCCUPATIONS:
        pre_list.sort(key=lambda x: x.get("intensity", 0.0), reverse=True)
        del pre_list[MAX_PREOCCUPATIONS:]

    logger.debug(f"[Preoccupation] created: {p_type}({about}) intensity={new_p['intensity']:.2f}")
    return new_p


def soothe(entity: Any, about: str, p_type: Optional[str] = None) -> int:
    """
    安抚心事——让 (about, [type]) 匹配的心事强度衰减更快。

    p_type=None 时安抚该 about 的所有类型。

    返回：被安抚的心事数量。
    """
    pre_list = getattr(entity, "_preoccupations", None)
    if not pre_list:
        return 0

    count = 0
    for p in pre_list:
        if p.get("about") != about:
            continue
        if p_type is not None and p.get("type") != p_type:
            continue
        p["intensity"] = float(p["intensity"]) * SOOTHE_FACTOR
        count += 1

    if count:
        logger.debug(f"[Preoccupation] soothed {count} concern(s) about '{about}'")
    return count


# ============================================================================
# 每 tick 调用：衰减 + 清理 + 投射
# ============================================================================

def tick_decay(entity: Any) -> None:
    """
    每 tick 衰减所有心事，强度 < MIN_INTENSITY 的移除。
    in-place 修改 entity._preoccupations。
    """
    pre_list = getattr(entity, "_preoccupations", None)
    if not pre_list:
        return

    # 衰减
    for p in pre_list:
        p["intensity"] = float(p["intensity"]) * (1.0 - DECAY_RATE)

    # 清理
    before = len(pre_list)
    entity._preoccupations = [
        p for p in pre_list
        if float(p.get("intensity", 0.0)) >= MIN_INTENSITY
    ]
    removed = before - len(entity._preoccupations)
    if removed:
        logger.debug(f"[Preoccupation] removed {removed} faded concern(s)")


def project_to_state(entity: Any) -> Dict[str, float]:
    """
    把所有心事投射成标量状态偏置 dict。

    contribution[dim] = sum over all preoccupations of:
                         TYPE_PROJECTION[type][dim] * intensity

    返回：{dim: delta} 由调用方加到 _real_state 上。
    """
    pre_list = getattr(entity, "_preoccupations", None)
    if not pre_list:
        return {}

    bias: Dict[str, float] = {}
    for p in pre_list:
        p_type = p.get("type", "")
        intensity = float(p.get("intensity", 0.0))
        proj = TYPE_PROJECTION.get(p_type, {})
        for dim, val in proj.items():
            bias[dim] = bias.get(dim, 0.0) + val * intensity

    return bias


# ============================================================================
# 查询接口（供语言系统引用具体心事）
# ============================================================================

def get_top_preoccupation(entity: Any) -> Optional[Dict]:
    """返回当前强度最高的心事，没有则 None。"""
    pre_list = getattr(entity, "_preoccupations", None)
    if not pre_list:
        return None
    return max(pre_list, key=lambda p: float(p.get("intensity", 0.0)))


def list_active(entity: Any, min_intensity: float = 0.1) -> List[Dict]:
    """返回强度 >= 阈值的心事列表，按强度降序。"""
    pre_list = getattr(entity, "_preoccupations", None)
    if not pre_list:
        return []
    active = [p for p in pre_list if float(p.get("intensity", 0.0)) >= min_intensity]
    active.sort(key=lambda p: float(p.get("intensity", 0.0)), reverse=True)
    return active
