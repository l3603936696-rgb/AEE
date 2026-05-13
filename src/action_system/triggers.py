"""
触发器 — 她什么时候行动。

没有阈值。没有 CD。没有 if-else。

触发强度 trigger_strength ∈ [0, 1] 是一个连续值，
由优先级和张力共同计算。tick_engine 用这个连续信号决定
是否执行——强度越高越可能执行，低强度自然不触发。

跟人一样：你有多想做一件事，不是过了某个门槛就突然能做，
也不是没过门槛就完全不能做。它是一个连续的程度。
"""

import time
from typing import Optional


def evaluate_triggers(
    entity,
    emergent_behavior=None,
) -> tuple[float, str]:
    """
    计算触发强度 [0, 1] 和原因描述。

    触发强度 = priority × (1 - tension)
    - priority 高 → 强
    - tension 高 → 纠结 → 弱
    - 行为类型不在可行动范围 → 0

    返回：
        (trigger_strength, reason)
    """
    if emergent_behavior is None:
        action_type, priority, tension, dominant = _infer_from_entity(entity)
    elif isinstance(emergent_behavior, dict):
        action_type = emergent_behavior.get("action_type", "idle")
        priority = emergent_behavior.get("priority", 0.0)
        tension = emergent_behavior.get("tension_level", 0.0)
        dominant = emergent_behavior.get("dominant_state", "")
    else:
        action_type = getattr(emergent_behavior, "action_type", "idle")
        priority = getattr(emergent_behavior, "priority", 0.0)
        tension = getattr(emergent_behavior, "tension_level", 0.0)
        dominant = getattr(emergent_behavior, "dominant_state", "")

    # 不可行动类型 → 强度抹零
    _actionable = {"seek", "explore", "comfort", "repair"}
    if action_type not in _actionable:
        strength = 0.0
    else:
        strength = priority * max(0.0, 1.0 - tension)
        strength = max(0.0, min(1.0, strength))

    reason = (
        f"action={action_type} priority={priority:.3f} "
        f"tension={tension:.3f} strength={strength:.3f} "
        f"dominant={dominant}"
    )
    return strength, reason


def _infer_from_entity(entity) -> tuple[str, float, float, str]:
    """从 entity 状态推断行为类型（fallback）。"""
    approach = getattr(entity, "approach_drive", 0.0)
    avoid = getattr(entity, "avoid_drive", 0.0)
    somatic_tone = getattr(entity, "somatic_tone", 0.0)
    loneliness = getattr(entity, "loneliness", 0.0)
    unresolved = getattr(entity, "unresolved", 0.0)

    ANTAGONISM = 0.3
    net_approach = approach - avoid * ANTAGONISM
    net_avoid = avoid - approach * ANTAGONISM
    total = net_approach + net_avoid + 1e-6
    tension = max(0.0, min(1.0, 1.0 - abs(net_approach - net_avoid) / total))

    gap = net_approach - net_avoid
    if abs(gap) <= 0.1:
        pending = len(getattr(entity, "pending_failures", []))
        if pending > 0 and unresolved > 0.3:
            action_type = "repair"
            dominant = "repair_drive"
        else:
            action_type = "idle"
            dominant = "tension"
    elif gap > 0.1:
        if somatic_tone > 0:
            if loneliness > 0.5:
                action_type = "seek"
                dominant = "loneliness"
            elif unresolved > 0.5:
                action_type = "explore"
                dominant = "unresolved"
            else:
                action_type = "comfort"
                dominant = "approach_drive"
        else:
            action_type = "comfort"
            dominant = "approach_drive"
    else:
        action_type = "avoid"
        dominant = "avoid_drive"

    priority = max(0.0, min(1.0, max(net_approach, net_avoid)))
    return action_type, priority, tension, dominant
