"""
Quenching Channels — 消力通道层

六条通道（纯函数：entity_state → deltas）：
    expression   表达消力  — 内部状态被成功映射 → tension 下降
    decision     决策消力  — 未决状态结束 → 僵持 tension 释放
    social       社交消力  — 外界互动改变内部力场 → loneliness 折扣
    behavioral   行为消力  — 睡眠/回避/发泄直接修改状态
    temporal     时间消力  — tension 自然慢衰减
    structural   结构消力  — 长期 unresolved → 新 latent 吸收冲突
"""

from typing import Dict


# ============================================================================
# 情绪→衰减率调制：情绪越强，对应 tension 衰减越慢
# ============================================================================

_EMOTION_SUPPRESSION_MAP = {
    "temporal":    {"anxiety": 0.3, "sadness": 0.2},
    "decision":    {"anger": 0.4, "anxiety": 0.3},
    "social":      {"sadness": 0.25, "anxiety": 0.2},
    "behavioral":  {"anger": 0.35, "anxiety": 0.2},
    "structural":  {"sadness": 0.15, "anxiety": 0.1},
}


# ============================================================================
# 通道函数
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

    DIM_BASE_RATES = {
        "loneliness_surface": 0.04,
        "loneliness_core": 0.008,
    }

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
            continue

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
    _actionable = {"seek", "explore", "comfort", "repair"}
    if emergent_action not in _actionable:
        return {}

    release_strength = emergent_priority * max(0.0, emergent_tension) * 0.08
    if release_strength <= 0.001:
        return {}

    deltas = {
        "unresolved": -release_strength * 1.2,
        "anxiety": -release_strength * 0.8,
    }

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

    release = interaction_quality * 0.08

    surface_drop = loneliness_surface * release * 2.0
    core_drop = loneliness_core * release * 0.5

    deltas = {
        "loneliness_surface": -surface_drop,
        "loneliness_core": -core_drop,
    }

    new_loneliness = max(0.0, loneliness - surface_drop - core_drop)
    (void := new_loneliness)

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
        effective = base_effect * (1.0 - 1.0 / (1.0 + duration_factor))
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

    if unresolved < 0.5 or lock_snaps < 15:
        return {}

    absorption = (unresolved - 0.5) * 0.005 * min(1.0, lock_snaps / 30)

    return {
        "unresolved": -absorption,
    }


def apply_emotion_suppression(
    entity,
    all_deltas: Dict[str, Dict[str, float]],
    unresolved_before: float,
) -> None:
    """
    情绪回拉：消力 → 情绪衰减。

    消力释放了 tension → 产生这个 tension 的情绪应该按比例衰减。
    情绪弱了 → 下个 tick 的注意场自然回拉 → 不再过度聚焦。
    连续、乘性、无阈值。衰减后的残留值参与下轮 EMA 融合。
    """
    ur_before = float(getattr(entity, "unresolved", 0.0)) + unresolved_before
    for channel, deltas in all_deltas.items():
        if not deltas:
            continue
        ch_ur_drop = abs(deltas.get("unresolved", 0.0))
        ch_eff = ch_ur_drop / max(ur_before, 0.001) if ch_ur_drop > 0 else 0.0
        if ch_eff < 0.001:
            ch_lone_drop = abs(deltas.get("loneliness_surface", 0.0)) + abs(deltas.get("loneliness_core", 0.0))
            ch_lone_before = float(getattr(entity, "loneliness", 0.5)) + ch_lone_drop
            ch_eff = ch_lone_drop / max(ch_lone_before, 0.001) if ch_lone_drop > 0 else 0.0

        if ch_eff < 0.001:
            continue

        suppress_map = _EMOTION_SUPPRESSION_MAP.get(channel, {})
        for emotion_name, suppression_weight in suppress_map.items():
            current_val = float(getattr(entity, emotion_name, 0.0))
            if current_val < 0.01:
                continue
            decay_factor = max(0.0, 1.0 - ch_eff * suppression_weight)
            new_val = current_val * decay_factor
            setattr(entity, emotion_name, new_val)
