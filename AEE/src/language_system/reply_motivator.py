"""
Reply Motivator — 回复动机模块（v1.0）

计算"要不要回应这个来源"的驱动力，注入 entity.approach_social。

回复驱动力公式：
    reply_drive = 关系权重 × 意图权重 × 内部状态调制

    关系权重  = familiarity × (0.5 + trust × 0.5)
    意图权重  = _INTENT_WEIGHTS[social_intent]（dispatch table，无 if-else）
    状态调制  = 1.0 + loneliness × 0.5 + unresolved × 0.3

注入方式：
    entity.approach_social += reply_drive × INJECT_SCALE
    （累积，不覆盖；每 tick 自然衰减由现有驱动系统处理）

独立于 source_profiler：本模块依赖 source_profiler 提供 familiarity/trust，
但属于独立的动机层，不归入感知/记录层。
"""

import math
from .source_profiler import get_familiarity, get_trust

# 意图权重 dispatch table（对方输入邀请性越高 → 回复驱动力越强）
_INTENT_WEIGHTS: dict = {
    "greeting":    0.90,
    "question":    0.85,
    "support":     0.75,
    "sharing":     0.55,
    "complaint":   0.40,
    "farewell":    0.30,
    "unknown":     0.20,
}

INJECT_SCALE = 0.25    # 每次最多注入 reply_drive × 0.25 到 approach_social
APPROACH_SOCIAL_CAP = 1.0   # approach_social 上限


def compute_reply_drive(entity, source_id: str, social_intent: str) -> float:
    """计算回复驱动力 ∈ [0, 1]，连续函数，无 if-else。"""
    familiarity = get_familiarity(entity, source_id)
    trust = get_trust(entity, source_id)

    # 关系权重：熟悉度为基础，信任度为乘数（陌生人也有最低基础权重）
    relation_weight = familiarity * (0.5 + trust * 0.5)

    # 意图权重：dispatch table 查找，未知意图给最低非零权重
    intent_weight = _INTENT_WEIGHTS.get(social_intent, _INTENT_WEIGHTS["unknown"])

    # 内部状态调制：孤独高、unresolved高 → 更想回应
    _loneliness = float(getattr(entity, "loneliness", 0.0))
    _unresolved = float(getattr(entity, "unresolved", 0.0))
    state_mod = 1.0 + _loneliness * 0.5 + _unresolved * 0.3

    drive = relation_weight * intent_weight * state_mod
    return min(1.0, drive)


def inject_reply_drive(entity, source_id: str, social_intent: str) -> float:
    """将回复驱动力注入 entity.approach_social，返回注入量。"""
    drive = compute_reply_drive(entity, source_id, social_intent)
    inject = drive * INJECT_SCALE

    current = float(getattr(entity, "approach_social", 0.0))
    entity.approach_social = min(APPROACH_SOCIAL_CAP, current + inject)
    return inject
