"""
Attention Field — 情绪向量 → 信息类别权重（v11.5）

情绪不是状态标签，是注意场的调制器。
同样的身体信号 + 不同情绪标签 → 不同信息类别被放大/抑制。

设计原则：
    - 所有增益连续，无阈值，无 if/else 闸门
    - 增益 = 1.0 为基线（不调制），>1 放大，<1 抑制
    - 多情绪叠加：对数域相加再 exp 还原（乘法效应）
    - 情绪越强，调制越深（连续缩放）

使用方式：
    Tick N:   emotion_compute → 情绪向量存 entity
    Tick N+1: pipeline Step 4 读 entity 情绪 → compute_attention_field() → 偏置概念标签
"""

import math
from typing import Dict, List, Tuple

# ============================================================================
# 情绪 → 信息类别调制映射
# ============================================================================
# 每个情绪对各类别的增益系数（乘法因子）。
# key = 情绪名, value = {信息类别: 增益}
# 增益 1.0 = 不影响，>1 = 放大，<1 = 抑制

EMOTION_CATEGORY_GAINS: Dict[str, Dict[str, float]] = {
    "fear": {
        "threat": 1.70,
        "risk": 1.50,
        "safety": 1.30,      # 恐惧同时激活安全搜寻（双面）
        "social": 0.60,
        "exploration": 0.50,
        "novelty": 0.55,
    },
    "joy": {
        "social": 1.50,
        "novelty": 1.30,
        "aesthetic": 1.40,
        "exploration": 1.30,
        "threat": 0.50,
        "risk": 0.60,
    },
    "sadness": {
        "causal": 1.40,         # 寻找原因
        "somatic": 1.30,        # 身体感受放大
        "retrospective": 1.50,  # 回顾过去
        "social": 0.70,
        "exploration": 0.80,
        "novelty": 0.65,
    },
    "anger": {
        "threat": 1.30,         # 愤怒指向威胁源
        "agency": 1.50,         # 自我效能感放大
        "conflict": 1.60,
        "social": 0.60,
        "aesthetic": 0.70,
    },
    "anxiety": {
        "threat": 1.50,
        "risk": 1.40,
        "temporal": 1.40,       # 时间压力
        "uncertainty": 1.60,    # 扫描不确定
        "social": 0.70,
        "routine": 0.75,
    },
    "excitement": {
        "exploration": 1.50,
        "novelty": 1.40,
        "social": 1.30,
        "agency": 1.30,
        "routine": 0.60,
        "threat": 0.65,
    },
    "serenity": {
        "routine": 1.30,
        "aesthetic": 1.40,
        "somatic": 1.20,        # 舒适感知放大
        "threat": 0.40,
        "risk": 0.50,
        "conflict": 0.55,
    },
    "disgust": {
        "threat": 1.50,
        "conflict": 1.40,
        "somatic": 1.30,        # 身体排斥感知
        "social": 0.50,
        "novelty": 0.55,
        "aesthetic": 0.40,
    },
    "surprise": {
        "novelty": 1.60,
        "uncertainty": 1.50,
        "exploration": 1.30,
        "routine": 0.50,
    },
}

# ============================================================================
# 所有信息类别（用于确保输出完整性）
# ============================================================================

ALL_CATEGORIES = [
    "threat", "risk", "safety",
    "social", "agency", "conflict",
    "exploration", "novelty", "uncertainty",
    "routine", "causal", "retrospective",
    "somatic", "aesthetic", "temporal",
]


def compute_attention_field(emotions: Dict[str, float]) -> Dict[str, float]:
    """
    从情绪向量计算当前注意场（信息类别增益向量）。

    参数：
        emotions: 情绪名 → 激活强度 [0, 1]

    返回：
        {category: gain}，gain ∈ (0, 2+]。
        1.0 = 基线不调制，>1 = 放大，<1 = 抑制。
    """
    if not emotions:
        return {cat: 1.0 for cat in ALL_CATEGORIES}

    # 对数域累积：多情绪叠加 = 乘法效应
    # 情绪越强 → 增益越偏离 1.0
    log_gains: Dict[str, float] = {cat: 0.0 for cat in ALL_CATEGORIES}

    for emotion_name, intensity in emotions.items():
        if intensity <= 0.01:
            continue
        gains = EMOTION_CATEGORY_GAINS.get(emotion_name)
        if not gains:
            continue

        # 强度缩放：intensity=0 → 不调制, intensity=1 → 满调制
        for cat, gain in gains.items():
            if gain == 1.0:
                continue
            # 对数域：log(gain) * intensity
            log_gains[cat] += math.log(max(0.01, gain)) * intensity

    # 还原为线性增益
    result = {}
    for cat in ALL_CATEGORIES:
        log_val = log_gains.get(cat, 0.0)
        result[cat] = math.exp(log_val)

    return result


def get_entity_emotions(entity) -> Dict[str, float]:
    """
    从 entity 读取当前情绪激活值（EMA 融合后的值）。

    返回情绪名 → 强度 [0, 1]。
    """
    emotion_names = list(EMOTION_CATEGORY_GAINS.keys())
    result = {}
    for name in emotion_names:
        val = getattr(entity, name, None)
        if val is not None:
            result[name] = float(val)
    return result


def compute_attention_field_from_entity(entity) -> Dict[str, float]:
    """便捷函数：从 entity 直接算注意场。"""
    emotions = get_entity_emotions(entity)
    return compute_attention_field(emotions)


# ============================================================================
# 注意场 → drive_vector 放大
# ============================================================================

# 注意类别 → 对应的 drive_vector key 列表
_ATTENTION_TO_DRIVE: Dict[str, List[str]] = {
    "exploration": ["curiosity"],
    "novelty":     ["curiosity", "info_hunger"],
    "uncertainty": ["obsolescence_anxiety"],
    "social":      ["loneliness_drive"],
    "temporal":    ["fatigue_avoid"],
    "threat":      ["fatigue_avoid"],
}


def apply_attention_to_drive_vector(
    drive_vector: Dict[str, float],
    attention_field: Dict[str, float],
) -> Dict[str, float]:
    """
    用注意场增益放大 drive_vector 中对应的驱动力信号。

    实现"情绪 → 有限算力聚焦"：
        焦虑激活时 uncertainty 增益 > 1 → obsolescence_anxiety 被放大
        兴奋激活时 exploration/novelty 增益 > 1 → curiosity/info_hunger 被放大
        恐惧激活时 threat 增益 > 1 → fatigue_avoid 被放大
        …

    参数：
        drive_vector   : Step 6 计算的原始驱动力向量（不修改原 dict）
        attention_field: compute_attention_field() 的输出

    返回：
        放大后的新 drive_vector dict
    """
    result = dict(drive_vector)

    for attn_cat, drive_keys in _ATTENTION_TO_DRIVE.items():
        gain = attention_field.get(attn_cat, 1.0)
        if abs(gain - 1.0) < 0.05:   # 增益太小跳过，节省噪声
            continue
        for key in drive_keys:
            if key in result:
                result[key] = min(1.0, result[key] * gain)

    return result


def apply_attention_gain(
    category: str,
    base_confidence: float,
    attention_field: Dict[str, float],
    sensitivity: float = 0.5,
) -> float:
    """
    用注意场调制某个信息类别标签的置信度。

    参数：
        category     : 信息类别名
        base_confidence : 原始置信度 [0, 1]
        attention_field : compute_attention_field 的输出
        sensitivity  : 调制敏感度。0=不调制，1=满调制。
                       默认 0.5，让注意场是"偏置"而非"开关"。

    返回：
        调制后置信度 [0, 1]
    """
    gain = attention_field.get(category, 1.0)
    # 增益向 1.0 插值：sensitivity=0 时不调制，sensitivity=1 时全调制
    effective_gain = 1.0 + (gain - 1.0) * sensitivity
    return max(0.0, min(1.0, base_confidence * effective_gain))
