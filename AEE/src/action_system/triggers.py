"""
触发器 — 她什么时候行动。

触发强度 trigger_strength ∈ [0, 1] 是连续值。
没有阈值，没有 if-else，没有离散门控。

强度 = priority × (1 - tension)
    priority 高 → 想做事
    tension 高 → 趋近/回避拉扯 → 抑制

pipeline 提供了 emergent_behavior 时直接用它的 priority / tension。
否则从 entity 状态维度连续评分（fallback）。
"""

import math


def evaluate_triggers(
    entity,
    emergent_behavior=None,
) -> tuple[float, str]:
    """
    计算触发强度 [0, 1] 和原因描述。

    返回：
        (trigger_strength, reason)
    """
    # ---- Pipeline 提供的决策 ----
    _eb = emergent_behavior
    _from_pipeline = _eb is not None
    if _from_pipeline:
        _is_dict = isinstance(_eb, dict)
        action_type = (_eb.get("action_type", "idle") if _is_dict
                       else getattr(_eb, "action_type", "idle"))
        priority = float(_eb.get("priority", 0.0) if _is_dict
                         else getattr(_eb, "priority", 0.0))
        tension = float(_eb.get("tension_level", 0.0) if _is_dict
                        else getattr(_eb, "tension_level", 0.0))
        dominant = (_eb.get("dominant_state", "") if _is_dict
                    else getattr(_eb, "dominant_state", ""))
    else:
        # ---- Fallback：从状态维度连续评分 ----
        action_type, priority, tension, dominant = _score_from_state(entity)

    # ---- 强度 = priority × (1 - tension) ----
    strength = priority * max(0.0, 1.0 - tension)
    strength = max(0.0, min(1.0, strength))

    reason = (
        f"action={action_type} priority={priority:.3f} "
        f"tension={tension:.3f} strength={strength:.3f} "
        f"dominant={dominant}"
    )
    return strength, reason


def _score_from_state(entity) -> tuple[str, float, float, str]:
    """
    从 entity 状态维度计算连续触发评分。

    每种行动倾向是状态维度的加权和——没有阈值，没有分支。
    最终选出得分最高的倾向作为 action_type。

    返回：
        (action_type, priority, tension, dominant_state)
    """
    approach = float(getattr(entity, "approach_drive", 0.0))
    avoid = float(getattr(entity, "avoid_drive", 0.0))
    loneliness = float(getattr(entity, "loneliness", 0.0))
    info_gap = float(getattr(entity, "info_gap", 0.0))
    curiosity = float(getattr(entity, "curiosity", 0.0))
    boredom = float(getattr(entity, "boredom", 0.0))
    unresolved = float(getattr(entity, "unresolved", 0.0))
    stress = float(getattr(entity, "stress", 0.0))
    energy = float(getattr(entity, "energy", 0.5))
    somatic_tone = float(getattr(entity, "somatic_tone", 0.0))
    pending_n = float(len(getattr(entity, "pending_failures", [])))

    # ---- 每种行动倾向的连续评分（加权和）----
    scores = {
        "seek":    loneliness * 0.5 + approach * 0.3 + max(0.0, 1.0 - energy) * 0.1,
        "explore": info_gap * 0.4 + curiosity * 0.3 + boredom * 0.2,
        "comfort": approach * 0.4 + max(0.0, somatic_tone) * 0.3 + energy * 0.2,
        "repair":  unresolved * 0.5 + min(pending_n * 0.2, 0.5) * 0.5 + stress * 0.2,
    }

    # 最强倾向
    dominant_action = max(scores, key=scores.get)
    dominant_score = scores[dominant_action]

    # ---- 张力：趋近与回避的拉扯程度 ----
    _ANTAGONISM = 0.3
    net_approach = max(0.0, approach - avoid * _ANTAGONISM)
    net_avoid = max(0.0, avoid - approach * _ANTAGONISM)
    total = net_approach + net_avoid + 1e-6
    tension = 1.0 - abs(net_approach - net_avoid) / total
    tension = max(0.0, min(1.0, tension))

    priority = max(0.0, min(1.0, dominant_score))

    return dominant_action, priority, tension, dominant_action
