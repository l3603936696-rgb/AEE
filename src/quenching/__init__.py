"""
Quenching — 六通道消力框架（v11.5）

消力不是奖励，不是快乐，不是魔法。
是"降低长期 unresolved 的稳定机制"。

六条通道：
    expression   表达消力  — 内部状态被成功映射 → tension 下降
    decision     决策消力  — 未决状态结束 → 僵持 tension 释放
    social       社交消力  — 外界互动改变内部力场 → loneliness 折扣
    behavioral   行为消力  — 睡眠/回避/发泄直接修改状态
    temporal     时间消力  — tension 自然慢衰减
    structural   结构消力  — 长期 unresolved → 新 latent 吸收冲突

设计原则：
    - 全部连续，无硬阈值，无 if/else 闸门
    - 每条通道独立计算贡献，叠加到 entity 维度
    - 消力效率 = 实际 Δunresolved / 最大可能 Δunresolved
    - 与注意场联动：消力 → 信息类别增益回拉
"""

from .quenching_event import QuenchingEvent, QuenchingJournal
from .quenching_channels import (
    expression_quenching,
    temporal_quenching,
    decision_quenching,
    social_quenching,
    behavioral_quenching,
    structural_quenching,
    apply_emotion_suppression,
)
from .quenching_channels import _EMOTION_SUPPRESSION_MAP

import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def apply_all_quenching(
    entity,
    emergent_action: str = "",
    emergent_priority: float = 0.0,
    emergent_tension: float = 0.0,
    user_interacted: bool = False,
    interaction_quality: float = 0.5,
    behavior_action: str = "",
    dt: float = 1.0,
    journal: Optional[QuenchingJournal] = None,
) -> Dict[str, Any]:
    """
    运行全部消力通道，叠加应用到 entity。

    参数：
        entity              : EntityState 实例
        emergent_action     : 涌现行为类型
        emergent_priority   : 行为优先级
        emergent_tension    : 僵持张力
        user_interacted     : 本轮是否有用户输入
        interaction_quality : 互动质量估计
        dt                  : 时间步长
        journal             : 可选的 QuenchingJournal（跨 tick 累积）

    返回：
        {
            "total_delta_unresolved": float,
            "channel_deltas": {channel: {dim: delta}},
            "efficiency": float,
        }
    """
    all_deltas: Dict[str, Dict[str, float]] = {}
    total_unresolved_drop = 0.0

    # 1. 时间消力（每个 tick 都运行）
    temporal_deltas = temporal_quenching(entity, dt=dt)
    all_deltas["temporal"] = temporal_deltas
    total_unresolved_drop += abs(temporal_deltas.get("unresolved", 0.0))

    # 2. 决策消力
    if emergent_action and emergent_action != "idle":
        decision_deltas = decision_quenching(
            entity, emergent_action, emergent_priority, emergent_tension
        )
        all_deltas["decision"] = decision_deltas
        total_unresolved_drop += abs(decision_deltas.get("unresolved", 0.0))

    # 3. 社交消力
    if user_interacted:
        social_deltas = social_quenching(entity, user_interacted=True, interaction_quality=interaction_quality)
        all_deltas["social"] = social_deltas
        total_unresolved_drop += abs(social_deltas.get("unresolved", 0.0))

    # 4. 行为消力
    if behavior_action:
        behavior_deltas = behavioral_quenching(entity, behavior_action)
        if behavior_deltas:
            all_deltas["behavioral"] = behavior_deltas
            total_unresolved_drop += abs(behavior_deltas.get("unresolved", 0.0))

    # 5. 结构消力
    structural_deltas = structural_quenching(entity)
    if structural_deltas:
        all_deltas["structural"] = structural_deltas
        total_unresolved_drop += abs(structural_deltas.get("unresolved", 0.0))

    # ---- 应用所有 delta 到 entity ----
    max_possible_drop = 0.0
    for channel, deltas in all_deltas.items():
        for dim, delta in deltas.items():
            if delta == 0.0:
                continue
            current = float(getattr(entity, dim, 0.0))
            new_val = max(0.0, min(1.0, current + delta))
            setattr(entity, dim, new_val)

            if dim == "unresolved" and delta < 0:
                max_possible_drop += abs(delta)

    # ---- 更新 loneliness 合成值 ----
    _need_sync = False
    for _ch in ("social", "temporal"):
        _deltas = all_deltas.get(_ch, {})
        if "loneliness_core" in _deltas or "loneliness_surface" in _deltas:
            _need_sync = True
            break
    if _need_sync:
        entity.loneliness = (
            float(getattr(entity, "loneliness_core", entity.loneliness * 0.7)) +
            float(getattr(entity, "loneliness_surface", entity.loneliness * 0.3))
        )

    # ---- 情绪回拉 ----
    apply_emotion_suppression(entity, all_deltas, total_unresolved_drop)

    # ---- 记录日志 ----
    unresolved_before = float(getattr(entity, "unresolved", 0.0)) + total_unresolved_drop
    unresolved_after = float(getattr(entity, "unresolved", 0.0))
    efficiency = total_unresolved_drop / max(unresolved_before, 0.001)

    if journal is not None:
        for channel, deltas in all_deltas.items():
            ur_drop = abs(deltas.get("unresolved", 0.0))
            if ur_drop > 0.0001:
                journal.record(QuenchingEvent(
                    channel=channel,
                    tick=int(getattr(entity, "tick", 0)),
                    timestamp=time.time(),
                    delta_unresolved=ur_drop,
                    delta_loneliness=abs(deltas.get("loneliness_surface", 0.0)) + abs(deltas.get("loneliness_core", 0.0)),
                    delta_stress=abs(deltas.get("stress", 0.0)),
                    delta_fatigue=abs(deltas.get("fatigue", 0.0)),
                    efficiency=ur_drop / max(unresolved_before, 0.001),
                    context={"action": emergent_action, "user_interacted": user_interacted},
                ))

    return {
        "total_delta_unresolved": round(total_unresolved_drop, 4),
        "channel_deltas": {
            ch: {k: round(v, 4) for k, v in d.items()}
            for ch, d in all_deltas.items()
        },
        "efficiency": round(efficiency, 4),
    }
