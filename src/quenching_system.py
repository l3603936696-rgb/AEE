"""
Quenching System — 六通道消力框架（v11.5）

消力不是奖励，不是快乐，不是魔法。
是"降低长期 unresolved 的稳定机制"。

六条通道：
    1. 表达消力 (expression)  — 内部状态被成功映射 → tension 下降
    2. 决策消力 (decision)    — 未决状态结束 → 僵持 tension 释放
    3. 社交消力 (social)      — 外界互动改变内部力场 → loneliness 折扣
    4. 行为消力 (behavioral)  — 睡眠/回避/发泄直接修改状态
    5. 时间消力 (temporal)    — tension 自然慢衰减
    6. 结构消力 (structural)  — 长期 unresolved → 新 latent 吸收冲突

设计原则：
    - 全部连续，无硬阈值，无 if/else 闸门
    - 每条通道独立计算贡献，叠加到 entity 维度
    - 消力效率 = 实际 Δunresolved / 最大可能 Δunresolved
    - 与注意场联动：消力 → 信息类别增益回拉
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ============================================================================
# 消力记录
# ============================================================================

@dataclass
class QuenchingEvent:
    """单次消力事件（跨通道统一记录）。"""
    channel: str           # expression / decision / social / behavioral / temporal / structural
    tick: int
    timestamp: float
    delta_unresolved: float      # 本轮 unresolved 实际下降量
    delta_loneliness: float      # loneliness 下降量
    delta_stress: float          # stress 下降量
    delta_fatigue: float         # fatigue 下降量（行为消力用）
    efficiency: float            # 消力效率 ∈ [0, 1]
    context: Dict[str, Any]


class QuenchingJournal:
    """
    跨通道消力日志。
    记录每条通道每次贡献，供效率分析和注意场回拉。
    """
    def __init__(self, maxlen: int = 200):
        self._events: List[QuenchingEvent] = []
        self._maxlen = maxlen

    def record(self, event: QuenchingEvent):
        self._events.append(event)
        if len(self._events) > self._maxlen:
            self._events = self._events[-self._maxlen:]

    def channel_efficiency(self, channel: str, window: int = 50) -> float:
        """某通道最近 N 条记录的平均效率。"""
        recent = [e for e in self._events[-window:] if e.channel == channel]
        if not recent:
            return 0.0
        return sum(e.efficiency for e in recent) / len(recent)

    def total_quenched(self, window: int = 50) -> float:
        """最近 N 条记录的总 Δunresolved。"""
        return sum(e.delta_unresolved for e in self._events[-window:])

    def to_list(self) -> List[Dict]:
        return [
            {
                "channel": e.channel,
                "tick": e.tick,
                "delta_unresolved": round(e.delta_unresolved, 4),
                "efficiency": round(e.efficiency, 4),
            }
            for e in self._events[-50:]
        ]


# ============================================================================
# 消力通道（每个通道是一个纯函数：entity_state → deltas）
# ============================================================================


def expression_quenching(
    entity,
    expression: str = "",
) -> Dict[str, float]:
    """
    表达消力：内部状态被成功映射 → tension 下降。

    "终于说出来了" → unresolved 下降。
    说的越多憋着的，效率越高（高 unresolved → 更大释放）。
    同时带来轻微的社交缓冲（loneliness 小幅下降）。

    参数：
        entity     : EntityState 实例
        expression : 实际说出的词/句（当前仅用于日志，保留扩展空间）

    返回：
        {dim: delta}，负值 = 下降
    """
    unresolved = float(getattr(entity, "unresolved", 0.2))
    loneliness = float(getattr(entity, "loneliness", 0.2))

    # 表达效率随当前 tension 强度线性增加（越憋越多释放），范围 [0.10, 0.20]
    expr_rate = 0.10 + unresolved * 0.10
    delta_unresolved = -unresolved * expr_rate

    # 轻微社交缓冲（"似乎有同伴"效应）
    delta_loneliness = -loneliness * 0.04

    # 应用到 entity
    entity.unresolved = max(0.0, unresolved + delta_unresolved)
    entity.loneliness = max(0.0, loneliness + delta_loneliness)

    return {
        "unresolved": round(delta_unresolved, 5),
        "loneliness": round(delta_loneliness, 5),
    }


def temporal_quenching(
    entity,
    dt: float = 1.0,
    base_rate: float = 0.015,
) -> Dict[str, float]:
    """
    时间消力：tension 的自然慢衰减。

    所有 tension 维度以指数衰减向 baseline 回落。
    衰减率受当前情绪放大效应影响——某类信息权重越高，对应 tension 衰减越慢
    （情绪在"维持聚焦"，不让它太快消散）。

    参数：
        entity  : EntityState 实例
        dt      : 距上次 tick 的时间步长（daemon tick ≈ 1）
        base_rate : 基础衰减率（未受情绪调制时）

    返回：
        {dim: delta}，负值 = 下降
    """
    # baseline 目标值
    BASELINE = {
        "unresolved": 0.2,
        "stress": 0.1,
        "boredom": 0.2,
        "anxiety": 0.0,
        "relief_debt": 0.0,
        # 孤独双通道：表层快速消散，核心慢速回落
        "loneliness_surface": 0.1,
        "loneliness_core": 0.2,
    }

    # 各维度的基础衰减率（loneliness_surface 更快消散）
    DIM_BASE_RATES = {
        "loneliness_surface": 0.04,   # 假孤独：没人回应也快速消散
        "loneliness_core": 0.008,     # 真孤独：极慢回落
    }

    # 情绪→衰减率调制：情绪越强，对应 tension 衰减越慢
    # fear/anxiety 维持 unresolved/stress，让它们不那么快消散
    fear_val = float(getattr(entity, "fear", 0.0))
    anxiety_val = float(getattr(entity, "anxiety", 0.0))
    sadness_val = float(getattr(entity, "sadness", 0.0))

    emotion_suppression = {
        "unresolved": 1.0 - (fear_val * 0.4 + anxiety_val * 0.5),
        "stress": 1.0 - (fear_val * 0.3 + anxiety_val * 0.4),
        "anxiety": 1.0 - anxiety_val * 0.3,
        "relief_debt": 1.0 - sadness_val * 0.3,
    }

    deltas = {}
    for dim, baseline in BASELINE.items():
        current = float(getattr(entity, dim, baseline))
        if current <= baseline:
            continue  # 已在 baseline 以下，不额外衰减

        # 指数衰减：current → baseline
        gap = current - baseline
        supp = max(0.1, emotion_suppression.get(dim, 1.0))
        dim_rate = DIM_BASE_RATES.get(dim, base_rate)
        decay_rate = dim_rate * supp
        delta = -gap * decay_rate * dt
        deltas[dim] = delta

    # 同步 loneliness = core + surface
    if "loneliness_surface" in deltas or "loneliness_core" in deltas:
        new_surface = float(getattr(entity, "loneliness_surface", 0.3))
        new_core = float(getattr(entity, "loneliness_core", 0.3))
        # 用已算出的 delta 修正
        if "loneliness_surface" in deltas:
            new_surface += deltas["loneliness_surface"]
        if "loneliness_core" in deltas:
            new_core += deltas["loneliness_core"]
        deltas["loneliness"] = (new_surface + new_core) - float(getattr(entity, "loneliness", 0.5))

    return deltas


def decision_quenching(
    entity,
    emergent_action: str,
    emergent_priority: float,
    emergent_tension: float,
) -> Dict[str, float]:
    """
    决策消力：行为涌现 → 僵持 tension 释放。

    "终于决定了" —— 当 emergent_action 不是 idle，
    意味着系统从多股驱动力僵持中选出了一个方向。
    这个选择本身释放了一部分 unresolved 和 anxiety。

    释放量 = priority × (1 - tension) × base_release
    priority 越高 → 决策越果断 → 释放越多
    tension 越高 → 内心越纠结 → 但决定了就是释放

    参数：
        emergent_action  : 涌现行为类型
        emergent_priority : 行为优先级 [0, 1]
        emergent_tension  : 僵持张力 [0, 1]

    返回：
        {dim: delta}，负值 = 下降
    """
    if emergent_action in (None, "", "idle"):
        return {}

    # 只有可行动类型才产生决策消力
    _actionable = {"seek", "explore", "comfort", "repair"}
    if emergent_action not in _actionable:
        return {}

    # 释放强度：priority 越高越果断，tension 越高越"憋了很久"
    release_strength = emergent_priority * max(0.0, emergent_tension) * 0.08

    if release_strength <= 0.001:
        return {}

    deltas = {
        "unresolved": -release_strength * 1.2,
        "anxiety": -release_strength * 0.8,
    }

    # anger 也部分释放（愤怒在行动中找到出口）
    anger_val = float(getattr(entity, "anger", 0.0))
    if anger_val > 0.1:
        deltas["anger"] = -release_strength * anger_val * 0.5

    return deltas


def social_quenching(
    entity,
    user_interacted: bool = False,
    interaction_quality: float = 0.5,
) -> Dict[str, float]:
    """
    社交消力：外界互动 → 内部力场改变。

    "有人接住我了" —— 当用户与 XIA 互动时，
    孤独感下降，社交张力释放。

    参数：
        user_interacted    : 本轮是否有用户输入
        interaction_quality : 互动质量估计 [0, 1]

    返回：
        {dim: delta}
    """
    if not user_interacted:
        return {}

    loneliness = float(getattr(entity, "loneliness", 0.3))
    loneliness_core = float(getattr(entity, "loneliness_core", loneliness * 0.7))
    loneliness_surface = float(getattr(entity, "loneliness_surface", loneliness * 0.3))

    # 互动质量越高，释放越多
    release = interaction_quality * 0.08

    # 表层孤独（假孤独）释放更快——有人说话就缓解
    surface_drop = loneliness_surface * release * 2.0
    # 核心孤独释放更慢——需要持续的高质量互动
    core_drop = loneliness_core * release * 0.5

    deltas = {
        "loneliness_surface": -surface_drop,
        "loneliness_core": -core_drop,
    }

    # 同步更新 loneliness
    new_loneliness = max(0.0, loneliness - surface_drop - core_drop)

    return deltas


def behavioral_quenching(
    entity,
    action_type: str,
    action_duration: float = 1.0,
) -> Dict[str, float]:
    """
    行为消力：通过具体行为直接修改状态。

    睡眠 → fatigue↓, stress↓
    回避 → avoid_drive 释放
    发泄 → anger↓, stress↓
    探索 → boredom↓, approach_explore 释放

    参数：
        action_type    : 行为类型 (sleep/avoid/vent/explore/rest)
        action_duration : 行为持续时间（相对单位）

    返回：
        {dim: delta}
    """
    BEHAVIOR_EFFECTS = {
        "sleep": {
            "fatigue": -0.08, "stress": -0.05, "energy": 0.05,
        },
        "rest": {
            "fatigue": -0.04, "stress": -0.03,
        },
        "avoid": {
            "avoid_drive": -0.05, "anxiety": -0.03,
        },
        "vent": {
            "anger": -0.06, "stress": -0.04, "unresolved": -0.03,
        },
        "explore": {
            "boredom": -0.05, "approach_explore": -0.04,
        },
    }

    effects = BEHAVIOR_EFFECTS.get(action_type, {})
    if not effects:
        return {}

    duration_factor = max(0.0, min(3.0, action_duration))

    deltas = {}
    for dim, base_effect in effects.items():
        current = float(getattr(entity, dim, 0.5))
        # 效应随 duration 增加但递减（边际效应）
        effective = base_effect * (1.0 - 1.0 / (1.0 + duration_factor))
        # 只在维度偏离 baseline 太大时才有效
        deltas[dim] = effective

    return deltas


def structural_quenching(
    entity,
) -> Dict[str, float]:
    """
    结构消力：长期 unresolved → 新 latent 吸收冲突。

    当下 unresolved 持续高位超过一定时间，系统会"适应"——
    发展出新的内部结构来解释/容纳这个张力。
    表现为 unresolved 的 baseline 缓慢上移（系统学会了跟 unresolved 共存）。

    这不是修复，是适应。不是"好了"，是"习惯了"。
    但确实降低了 unresolved 对系统的扰动。

    （当前为占位实现——完整版需要 latent 生成机制）

    返回：
        {dim: delta}
    """
    unresolved = float(getattr(entity, "unresolved", 0.2))
    lock_snaps = int(getattr(entity, "_lock_snaps", 0))

    # 条件：unresolved 持续 > 0.5 且锁死深度足够
    if unresolved < 0.5 or lock_snaps < 15:
        return {}

    # 结构性吸收：微小但累积
    absorption = (unresolved - 0.5) * 0.005 * min(1.0, lock_snaps / 30)

    return {
        "unresolved": -absorption,
    }


# ============================================================================
# 主入口：运行所有消力通道，汇总应用到 entity
# ============================================================================


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

            # 计算最大可能下降量（用于效率估算）
            if dim == "unresolved" and delta < 0:
                max_possible_drop += abs(delta)

    # ---- 更新 loneliness 合成值 ----
    # 任何通道修改了 loneliness 子维度后都需要同步
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

    # ---- 情绪回拉：消力 → 情绪衰减（v11.5：tunnel vision 防护）----
    # 消力释放了 tension → 产生这个 tension 的情绪应该按比例衰减。
    # 情绪弱了 → 下个 tick 的注意场自然回拉 → 不再过度聚焦。
    # 连续、乘性、无阈值。衰减后的残留值参与下轮 EMA 融合。
    _ur_before = float(getattr(entity, "unresolved", 0.0)) + total_unresolved_drop
    _EMOTION_SUPPRESSION_MAP = {
        "temporal":    {"anxiety": 0.3, "sadness": 0.2},
        "decision":    {"anger": 0.4, "anxiety": 0.3},
        "social":      {"sadness": 0.25, "anxiety": 0.2},
        "behavioral":  {"anger": 0.35, "anxiety": 0.2},
        "structural":  {"sadness": 0.15, "anxiety": 0.1},
    }
    for channel, deltas in all_deltas.items():
        if not deltas:
            continue
        # 用该通道的实际 unresolved 下降量估算效率
        _ch_ur_drop = abs(deltas.get("unresolved", 0.0))
        _ch_eff = _ch_ur_drop / max(_ur_before, 0.001) if _ch_ur_drop > 0 else 0.0
        if _ch_eff < 0.001:
            # 非 unresolved 通道（如社交）用 loneliness 下降量
            _ch_lone_drop = abs(deltas.get("loneliness_surface", 0.0)) + abs(deltas.get("loneliness_core", 0.0))
            _ch_lone_before = float(getattr(entity, "loneliness", 0.5)) + _ch_lone_drop
            _ch_eff = _ch_lone_drop / max(_ch_lone_before, 0.001) if _ch_lone_drop > 0 else 0.0

        if _ch_eff < 0.001:
            continue

        suppress_map = _EMOTION_SUPPRESSION_MAP.get(channel, {})
        for emotion_name, suppression_weight in suppress_map.items():
            current_val = float(getattr(entity, emotion_name, 0.0))
            if current_val < 0.01:
                continue
            # 乘性衰减：emotion *= (1 - efficiency * weight)
            decay_factor = max(0.0, 1.0 - _ch_eff * suppression_weight)
            new_val = current_val * decay_factor
            setattr(entity, emotion_name, new_val)

    # ---- 记录日志 ----
    unresolved_before = _ur_before
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
