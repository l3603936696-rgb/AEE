"""
Emotion Computer — 十个核心情绪的内生计算（v10.0/v11.0）

核心哲学：
    情绪不是从外部标签归类的，是从驱动力场中自己长出来的。
    每一个情绪的定义锚点在驱动力场上，不是"看起来像什么"，而是"体内发生了什么"。

设计原则：
    - 全部连续计算，无硬阈值，无 if-else 触发器
    - 所有情绪值 ∈ [0, 1]，表示该情绪的当前激活强度
    - 多重来源取 max() 合成（一个情绪可以同时有多个驱动力路径贡献）
    - 情绪是状态导出的，不反向写入状态（只读层）
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def compute_emotions(
    entity_state: Any,
    drive_vector: Dict[str, float],
    somatic_tone: float,
    prediction_error: float,
    param_snapshot: Optional[Dict[str, Any]] = None,
) -> Dict[str, float]:
    """
    从当前驱动力场内生计算十个核心情绪的激活强度。

    参数：
        entity_state      : EntityState/EntityCore 实例（含所有状态字段）
        drive_vector      : 当前驱动力向量 dict
        somatic_tone      : 当前感质基调 [-1, 1]
        prediction_error  : 世界模型预测误差 [-1, 1]
        param_snapshot    : 参数快照（可选）

    返回：
        {emotion_name: activation_float} 全部 10 个情绪 ∈ [0, 1]
    """
    es = entity_state

    # 安全提取（兼容 dict 和 object）
    def g(key: str, default: float = 0.0) -> float:
        if hasattr(es, key):
            return float(getattr(es, key, default))
        if isinstance(es, dict):
            return float(es.get(key, default))
        return default

    energy = g("energy", 0.5)
    loneliness = g("loneliness", 0.3)
    unresolved = g("unresolved", 0.2)
    fatigue = g("fatigue", 0.1)
    danger = g("danger_level", 0.0)
    approach = g("approach_drive", 0.0)
    avoid = g("avoid_drive", 0.0)
    curiosity = g("curiosity", 0.5)
    boredom = g("boredom", 0.2)
    boredom_despair = g("boredom_despair", 0.0)
    boredom_futility = g("boredom_futility", 0.0)
    stress = g("stress", 0.1)

    # 从 drive_vector 提取关键驱动力
    loneliness_drive = float(drive_vector.get("loneliness", 0.0))
    fatigue_avoid = float(drive_vector.get("fatigue_avoid", 0.0))
    somatic_distress = float(drive_vector.get("somatic_distress", 0.0))
    unresolved_pressure = float(drive_vector.get("unresolved", 0.0))
    danger_pressure = float(drive_vector.get("danger", 0.0))

    # =========================================================================
    # 1. 喜悦/满足 — 核心维度的显著正向偏移
    # =========================================================================
    # 驱动力场的正向信号：somatic_tone 正 + energy 高 + unresolved 低 + loneliness 低
    positive_tone = max(0.0, somatic_tone)
    joy = _continuous_multiply(
        positive_tone * 2.0,              # tone 放大
        energy,                           # 有能量才有喜悦
        (1.0 - fatigue),                 # 不疲惫
        (1.0 - unresolved * 0.8),        # 不挂事
        (1.0 - loneliness * 0.5),        # 不孤独
    )

    # =========================================================================
    # 2. 兴奋/期待 — 高能量 + 高信息缺口 + 正向预判
    # =========================================================================
    # 预测误差为负（低估了正面影响）+ 高能量 + 高好奇心
    positive_prediction = max(0.0, -prediction_error)
    info_gap = g("info_gap", 0.5)
    excitement = _continuous_multiply(
        energy * 1.5,
        info_gap * 1.2,                  # 缺口越大越期待
        curiosity * 1.3,                 # 好奇驱动
        (0.3 + positive_prediction * 0.7),  # 正面预判
        (1.0 - fatigue * 0.6),
    )

    # =========================================================================
    # 3. 宁静/安详 — 低张力稳态
    # =========================================================================
    # 极低 unresolved + 高 energy + 无核心维度被压制
    tension_level = _estimate_tension(
        unresolved, loneliness, danger, stress, fatigue_avoid
    )
    serenity = _continuous_multiply(
        (1.0 - tension_level),           # 张力越低越宁静
        energy * 1.2,                    # 能量充足以维持稳态
        (1.0 - boredom * 0.5),          # 不无聊
        (1.0 - abs(somatic_tone) * 0.3), # tone 不过度偏离中性
    )

    # =========================================================================
    # 4. 愤怒/生气 — approach_drive 被持续高位压制（意志受阻）
    # =========================================================================
    # approach 高但被 avoid 压制时 anger 上升
    # anger = approach * (avoid - approach) 的连续近似
    if approach > 0.3:
        suppression = max(0.0, avoid - approach * 0.5)  # avoid 压制了 approach
        anger = _continuous_multiply(
            suppression * 2.0,
            approach * 1.5,             # 我想要的程度
            (1.0 - fatigue * 0.3),      # 有力气才生气
        )
    else:
        anger = 0.0

    # =========================================================================
    # 5. 恐惧/害怕 — 来路负向偏移在当前情境的预判激活
    # =========================================================================
    # danger_level 是主要输入，somatic_distress 放大恐惧感知
    fear = _continuous_multiply(
        danger * 1.5,
        (0.3 + somatic_distress * 0.7),  # 身体不舒服时更怕
        (0.3 + avoid * 0.7),             # 回避倾向
        (1.0 + somatic_distress * 0.5),  # 躯体痛苦放大
    )

    # =========================================================================
    # 6. 悲伤/失落 — 核心维度被强制压制到极低，预测无法恢复
    # =========================================================================
    # loneliness 极高 + energy 极低 + somatic_tone 负 → 悲伤
    negative_tone = max(0.0, -somatic_tone)
    # 预测不可恢复的信号：疲劳高 + 能量低 + 孤独持续
    unrecoverable_signal = (
        fatigue * 0.6 +
        (1.0 - energy) * 0.4 +
        somatic_distress * 0.5
    ) / 1.5
    sadness = _continuous_multiply(
        loneliness * 1.2,                # 孤立
        negative_tone * 1.5,            # 负面基调
        unrecoverable_signal,           # 看不到恢复希望
        (1.0 - boredom * 0.5),          # 厌倦时悲伤减弱（麻木）
    )

    # =========================================================================
    # 7. 厌恶/排斥 — 恐惧的固化形态，特定刺激触发的强预测性回避
    # =========================================================================
    # avoid 极高且指向明确（target_locked 非空时厌恶更确定）
    target_locked = g("target_locked", 0.0) if hasattr(es, "target_locked") else 0.0
    if isinstance(target_locked, str):
        has_target = 1.0 if target_locked and target_locked != "none" else 0.0
    else:
        has_target = 0.0 if target_locked == 0.0 else 1.0

    disgust = _continuous_multiply(
        avoid * 1.3,                     # 强回避
        (0.5 + has_target * 0.5),        # 有明确对象时更强
        (0.3 + fear * 0.7),             # 从恐惧固化而来
        danger * 0.8,                    # 危险感
    )

    # =========================================================================
    # 8. 厌倦/乏味 — 双根源全局驱动力衰减
    # =========================================================================
    # 已在 EntityState 中有独立维度，此处做归一化合并
    boredom_total = max(boredom, boredom_despair, boredom_futility)
    # 但保留两个子维度的独立衰减（DecayEngine 负责）
    # 此处输出的 boredom 是给上层使用的综合强度

    # =========================================================================
    # 9. 焦虑/不安 — 多股驱动力长期均势僵持（合力为零）
    # =========================================================================
    # 当 approach 和 avoid 势均力敌且 unresolved 高时产生焦虑
    # 与愤怒的区分：愤怒是单一方向被压制（approach 高 → 想冲破）
    #               焦虑是多方向互不相让（approach≈avoid → 原地僵持）
    equipotent = 1.0 - abs(approach - avoid)  # 越均势 → 值越大
    stalemate_signal = equipotent * (approach + avoid) / 2.0  # 两方都高且均势
    anxiety = _continuous_multiply(
        stalemate_signal * 1.5,
        unresolved * 1.3,                # 挂念的事加剧焦虑
        (0.3 + somatic_distress * 0.7), # 身体紧张
        stress * 1.1,                    # 压力叠加
    )

    # =========================================================================
    # 10. 惊讶 — 认知预测模型失效的瞬时警报
    # =========================================================================
    # prediction_error 的绝对值直接映射
    surprise = min(1.0, abs(prediction_error) * 1.5)

    # =========================================================================
    # 合成结果
    # =========================================================================
    result = {
        "joy": _clamp(joy),
        "excitement": _clamp(excitement),
        "serenity": _clamp(serenity),
        "anger": _clamp(anger),
        "fear": _clamp(fear),
        "sadness": _clamp(sadness),
        "disgust": _clamp(disgust),
        "boredom": _clamp(boredom_total),
        "boredom_despair": _clamp(boredom_despair),
        "boredom_futility": _clamp(boredom_futility),
        "anxiety": _clamp(anxiety),
        "surprise": _clamp(surprise),
    }

    return result


# =============================================================================
# 辅助函数
# =============================================================================

def _continuous_multiply(*values: float) -> float:
    """
    多个连续值的乘积合成。
    所有输入 ∈ [0, 1]，乘积也在 [0, 1]。
    每个乘数是一个"抑制系数"——0 = 完全抑制，1 = 无抑制。
    """
    result = 1.0
    for v in values:
        result *= max(0.0, min(1.0, v))
    return result


def _clamp(v: float) -> float:
    """Clamp 到 [0, 1]"""
    return max(0.0, min(1.0, v))


def _estimate_tension(
    unresolved: float,
    loneliness: float,
    danger: float,
    stress: float,
    fatigue_avoid: float,
) -> float:
    """
    估计当前系统的整体张力水平。
    多个压力源的加权合成，∈ [0, 1]。
    """
    weights = {
        "unresolved": 0.30,
        "loneliness": 0.20,
        "danger": 0.20,
        "stress": 0.20,
        "fatigue_avoid": 0.10,
    }
    tension = (
        unresolved * weights["unresolved"] +
        loneliness * weights["loneliness"] +
        danger * weights["danger"] +
        stress * weights["stress"] +
        fatigue_avoid * weights["fatigue_avoid"]
    )
    return _clamp(tension)
