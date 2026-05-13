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

设计：
    1. ~37 个锚点词，覆盖 12 个身体感受聚类
    2. 每个锚点定义驱动力场 delta 向量（这个词对应的状态偏差）
    3. BGE 传播：任意词通过余弦距离从最近锚点继承映射
    4. 三层接口：
       - get_state_match_score: 候选词多准确地描述了当前状态（诊断精度）
       - get_counter_delta: 匹配成功后给出的"帮助"（反向 delta）
       - apply_help_delta: 验证匹配后施加帮助 + 消力
"""

import logging
import math
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# =============================================================================
# 锚点表 — 51 个身体感受聚类代表词
# =============================================================================
#
# Delta 含义：
#   正值 → 这个维度被激活/升高
#   负值 → 这个维度被抑制/降低
#   0    → 无影响
#
# 绝对值范围 0.02~0.30，对应"微扰"到"明显感受"。
# 这些不是状态跳变，是身体感的连续调制。

SOMATIC_ANCHORS: Dict[str, Dict[str, float]] = {
    "冷": {
        "somatic_tone": -0.18,
        "avoid_drive": +0.15,
        "energy": -0.12,
        "approach_drive": -0.10,
    },
    "热": {
        "serenity": +0.12,
        "somatic_tone": +0.12,
        "approach_drive": +0.10,
        "anxiety": -0.08,
    },
    "痛": {
        "somatic_tone": -0.30,
        "avoid_drive": +0.25,
        "fear": +0.15,
        "stress": +0.15,
    },
    "痒": {
        "curiosity": +0.08,
        "avoid_drive": +0.06,
        "anxiety": +0.05,
        "stress": +0.04,
    },
    "软": {
        "somatic_tone": +0.15,
        "approach_drive": +0.10,
        "avoid_drive": -0.10,
        "serenity": +0.10,
    },
    "硬": {
        "avoid_drive": +0.15,
        "somatic_tone": -0.10,
        "stress": +0.08,
        "approach_drive": -0.06,
    },
    "粗": {
        "avoid_drive": +0.10,
        "somatic_tone": -0.10,
        "disgust": +0.08,
        "anxiety": +0.06,
    },
    "湿": {
        "somatic_tone": -0.12,
        "avoid_drive": +0.08,
        "approach_drive": -0.06,
        "fatigue": +0.05,
    },
    "干": {
        "somatic_tone": -0.10,
        "energy": -0.10,
        "fatigue": +0.06,
        "anxiety": +0.05,
    },
    "重": {
        "fatigue": +0.22,
        "energy": -0.15,
        "sadness": +0.12,
        "somatic_tone": -0.12,
    },
    "轻": {
        "joy": +0.18,
        "energy": +0.15,
        "somatic_tone": +0.12,
        "fatigue": -0.08,
    },
    "饿": {
        "somatic_tone": -0.15,
        "energy": -0.10,
        "stress": +0.08,
        "approach_drive": +0.05,
    },
    "渴": {
        "somatic_tone": -0.20,
        "energy": -0.15,
        "stress": +0.08,
        "approach_drive": +0.10,
    },
    "累": {
        "fatigue": +0.30,
        "somatic_tone": -0.10,
    },
    "困": {
        "fatigue": +0.28,
        "energy": -0.20,
        "avoid_drive": +0.10,
        "curiosity": -0.10,
    },
    "舒服": {
        "somatic_tone": +0.25,
        "joy": +0.15,
        "serenity": +0.15,
        "avoid_drive": -0.10,
    },
    "静": {
        "serenity": +0.20,
        "avoid_drive": -0.10,
        "anxiety": -0.08,
        "approach_drive": +0.05,
    },
    "快": {
        "excitement": +0.15,
        "energy": +0.10,
        "prediction_error": +0.08,
        "anxiety": +0.03,
    },
    "慢": {
        "serenity": +0.10,
        "energy": -0.06,
        "fatigue": +0.05,
        "anxiety": -0.03,
    },
    "紧": {
        "anxiety": +0.18,
        "stress": +0.15,
        "avoid_drive": +0.10,
        "somatic_tone": -0.08,
    },
    "松": {
        "serenity": +0.18,
        "avoid_drive": -0.15,
        "stress": -0.12,
        "anxiety": -0.12,
    },
    "麻": {
        "somatic_tone": -0.15,
        "anxiety": +0.08,
        "curiosity": -0.05,
        "energy": -0.05,
    },
    "胀": {
        "somatic_tone": -0.18,
        "stress": +0.15,
        "avoid_drive": +0.12,
        "anxiety": +0.08,
    },
    "晕": {
        "somatic_tone": -0.20,
        "energy": -0.15,
        "fear": +0.12,
        "anxiety": +0.10,
    },
    "烫": {
        "avoid_drive": +0.25,
        "somatic_tone": -0.25,
        "fear": +0.10,
        "stress": +0.10,
    },
    "凉": {
        "somatic_tone": -0.08,
        "approach_drive": +0.18,
        "energy": +0.06,
        "serenity": +0.10,
    },
    "僵": {
        "somatic_tone": -0.20,
        "fatigue": +0.18,
        "avoid_drive": +0.15,
        "stress": +0.10,
    },
    "闷": {
        "sadness": +0.18,
        "somatic_tone": -0.15,
        "energy": -0.12,
        "approach_drive": -0.10,
    },
    "慌": {
        "fear": +0.25,
        "stress": +0.20,
        "anxiety": +0.20,
        "energy": -0.10,
    },
    "抖": {
        "fear": +0.18,
        "stress": +0.15,
        "anxiety": +0.10,
        "energy": -0.08,
    },
    "沉": {
        "sadness": +0.22,
        "fatigue": +0.22,
        "energy": -0.20,
        "approach_drive": -0.12,
    },
    "飘": {
        "joy": +0.15,
        "somatic_tone": +0.15,
        "energy": +0.10,
        "excitement": +0.08,
    },
    "刺": {
        "avoid_drive": +0.15,
        "somatic_tone": -0.15,
        "fear": +0.08,
        "stress": +0.08,
    },
    "木": {
        "somatic_tone": -0.25,
        "fatigue": +0.20,
        "avoid_drive": +0.12,
        "curiosity": -0.08,
    },
    "堵": {
        "somatic_tone": -0.18,
        "anxiety": +0.18,
        "stress": +0.15,
        "avoid_drive": +0.12,
    },
    "跳": {
        "stress": +0.12,
        "anxiety": +0.10,
        "energy": +0.08,
        "somatic_tone": -0.08,
    },
    "抽": {
        "avoid_drive": +0.28,
        "somatic_tone": -0.28,
        "fear": +0.15,
        "stress": +0.12,
    },
    "烧": {
        "somatic_tone": -0.28,
        "avoid_drive": +0.25,
        "fear": +0.15,
        "stress": +0.12,
    },
    "压": {
        "somatic_tone": -0.20,
        "anxiety": +0.18,
        "stress": +0.15,
        "avoid_drive": +0.12,
    },
    "绷": {
        "anxiety": +0.15,
        "stress": +0.12,
        "avoid_drive": +0.10,
        "somatic_tone": -0.08,
    },
    "缩": {
        "fear": +0.18,
        "avoid_drive": +0.15,
        "approach_drive": -0.12,
        "somatic_tone": -0.12,
    },
    "撑": {
        "somatic_tone": -0.20,
        "stress": +0.18,
        "avoid_drive": +0.12,
        "approach_drive": -0.10,
    },
    "空": {
        "sadness": +0.15,
        "somatic_tone": -0.15,
        "energy": -0.12,
        "joy": -0.10,
    },
    "酥": {
        "serenity": +0.20,
        "joy": +0.15,
        "somatic_tone": +0.12,
        "stress": -0.10,
    },
    "乏": {
        "fatigue": +0.35,
        "energy": -0.30,
        "sadness": +0.15,
        "avoid_drive": +0.15,
    },
    "黏": {
        "disgust": +0.18,
        "avoid_drive": +0.15,
        "somatic_tone": -0.15,
        "anxiety": +0.08,
    },
    "坠": {
        "somatic_tone": -0.22,
        "fear": +0.18,
        "anxiety": +0.15,
        "sadness": +0.08,
    },
    # === v11.5 情绪词汇 ===
    "开心": {
        "joy": +0.25,
        "energy": +0.12,
        "serenity": +0.10,
        "somatic_tone": +0.10,
    },
    "难过": {
        "sadness": +0.25,
        "energy": -0.12,
        "joy": -0.10,
        "approach_drive": -0.08,
    },
    "害怕": {
        "fear": +0.25,
        "avoid_drive": +0.15,
        "anxiety": +0.12,
        "somatic_tone": -0.10,
    },
    "焦虑": {
        "anxiety": +0.25,
        "stress": +0.15,
        "fear": +0.10,
        "energy": -0.08,
    },
    "生气": {
        "anger": +0.25,
        "stress": +0.15,
        "avoid_drive": +0.10,
        "approach_urgency": +0.08,
    },
    "平静": {
        "serenity": +0.25,
        "stress": -0.12,
        "anxiety": -0.12,
        "joy": +0.08,
    },
    "兴奋": {
        "excitement": +0.25,
        "energy": +0.15,
        "joy": +0.12,
        "approach_drive": +0.10,
    },
}

# =============================================================================
# 锚点聚类表（v11.5: 多词组合，同簇词不叠加）
# =============================================================================
# 每个锚点属于一个身体感受簇。多词组合时，TOP2 必须来自不同簇。
# 例如："冷"(温度) + "痛"(疼痛) → "又冷又痛" ✓
#       "痛"(疼痛) + "烫"(疼痛) → 跳过，同簇不叠加 ✗

ANCHOR_CLUSTERS: Dict[str, str] = {
    # ── 温度 ──
    "冷": "温度", "热": "温度", "凉": "温度", "烫": "温度",
    # ── 疼痛 ──
    "痛": "疼痛", "刺": "疼痛", "抽": "疼痛", "烧": "疼痛", "痒": "疼痛",
    # ── 触感 ──
    "软": "触感", "硬": "触感", "粗": "触感", "湿": "触感", "干": "触感",
    "黏": "触感", "麻": "触感",
    # ── 疲劳 ──
    "累": "疲劳", "困": "疲劳", "乏": "疲劳", "重": "疲劳",
    # ── 饥饿 ──
    "饿": "饥饿", "渴": "饥饿",
    # ── 舒适 ──
    "舒服": "舒适", "轻": "舒适", "静": "舒适", "松": "舒适",
    "酥": "舒适", "飘": "舒适",
    # ── 持续紧张 ──
    "紧": "持续紧张", "绷": "持续紧张",
    # ── 急性应激 ──
    "慌": "急性应激", "抖": "急性应激", "跳": "急性应激",
    # ── 压迫 ──
    "胀": "压迫", "压": "压迫", "撑": "压迫", "堵": "压迫", "闷": "压迫",
    # ── 僵硬 ──
    "僵": "僵硬", "缩": "僵硬", "木": "僵硬",
    # ── 低落 ──
    "空": "低落", "坠": "低落", "沉": "低落",
    # ── 速度 ──
    "快": "速度", "慢": "速度",
    # ── 失衡 ──
    "晕": "失衡",
    # ── 情绪 ──
    "开心": "情绪", "难过": "情绪", "害怕": "情绪",
    "焦虑": "情绪", "生气": "情绪", "平静": "情绪", "兴奋": "情绪",
}

# 所有可用的维度名（用于保证 delta 向量的对齐）
ALL_DIMENSIONS = [
    "energy", "loneliness", "unresolved", "fatigue", "danger_level",
    "approach_drive", "avoid_drive", "curiosity", "boredom",
    "boredom_despair", "boredom_futility", "stress", "somatic_tone",
    "prediction_error",
    # 情绪维度
    "joy", "excitement", "serenity", "anger", "fear",
    "sadness", "disgust", "anxiety", "surprise",
]

# =============================================================================
# BGE 传播层
# =============================================================================

# 模块级缓存
_anchor_embeddings: Optional[Dict[str, "numpy.ndarray"]] = None  # type: ignore
_anchor_words: List[str] = []


def _ensure_anchor_embeddings():
    """懒加载：计算所有锚点词的 BGE 嵌入。"""
    global _anchor_embeddings, _anchor_words
    if _anchor_embeddings is not None:
        return

    from .bge_analyzer import _get_bge_model

    model = _get_bge_model()
    if model is None:
        logger.warning("[SomaticMap] BGE not available, propagation disabled")
        _anchor_embeddings = {}
        return

    _anchor_words = list(SOMATIC_ANCHORS.keys())
    try:
        import numpy as np
        embeddings = model.encode(_anchor_words, normalize_embeddings=True)
        _anchor_embeddings = {
            word: emb for word, emb in zip(_anchor_words, embeddings)
        }
        logger.info(
            f"[SomaticMap] {len(_anchor_embeddings)} anchors embedded "
            f"(dim={embeddings.shape[1]})"
        )
    except Exception as e:
        logger.warning(f"[SomaticMap] Embedding failed: {e}")
        _anchor_embeddings = {}


def get_somatic_delta(
    word: str,
    top_k: int = 3,
    min_similarity: float = 0.35,
    propagation_weight: float = 0.60,
) -> Dict[str, float]:
    """
    计算任意词的驱动力场身体感映射。

    算法：
        1. 如果 word 直接是锚点词，返回其映射（权重 1.0）
        2. 通过 BGE 计算 word 和所有锚点的余弦相似度
        3. 取 top_k 个最相似的锚点
        4. 加权平均各锚点的 delta，权重 = sim × propagation_weight
        5. 相似度低于 min_similarity 的锚点不参与

    参数：
        word               : 待查询的词
        top_k              : 参与传播的最近锚点数
        min_similarity     : 最低相似度阈值
        propagation_weight : 传播衰减系数（继承锚点映射的强度）

    返回：
        {dimension: delta} dict。word 无法映射时返回空 dict。
    """
    # 直接命中锚点
    if word in SOMATIC_ANCHORS:
        return dict(SOMATIC_ANCHORS[word])

    _ensure_anchor_embeddings()

    if not _anchor_embeddings or not _anchor_words:
        return {}

    from .bge_analyzer import _get_bge_model

    model = _get_bge_model()
    if model is None:
        return {}

    try:
        import numpy as np
        word_emb = model.encode([word], normalize_embeddings=True)[0]

        # 计算和所有锚点的余弦相似度
        similarities = []
        for anchor_word in _anchor_words:
            anchor_emb = _anchor_embeddings[anchor_word]
            sim = float(word_emb @ anchor_emb)  # 已归一化，点积 = 余弦
            similarities.append((anchor_word, sim))

        # 按相似度降序，取 top_k
        similarities.sort(key=lambda x: x[1], reverse=True)
        top = [(w, s) for w, s in similarities[:top_k] if s >= min_similarity]

        if not top:
            return {}

        # 加权平均 delta
        total_weight = sum(s for _, s in top)
        merged: Dict[str, float] = {}

        for anchor_word, sim in top:
            weight = (sim / total_weight) * propagation_weight
            anchor_delta = SOMATIC_ANCHORS[anchor_word]
            for dim, delta in anchor_delta.items():
                merged[dim] = merged.get(dim, 0.0) + delta * weight

        return merged

    except Exception as e:
        logger.warning(f"[SomaticMap] get_delta('{word}') failed: {e}")
        return {}


def get_state_match_score(
    candidate_word: str,
    drive_state: Dict[str, float],
    top_k: int = 3,
    min_similarity: float = 0.35,
) -> float:
    """
    诊断精度评分——这个词多准确地描述了当前的身体状态？

    原理：
        词的 delta 向量描述了一个"身体画像"：
        冷={energy低, avoid高, somatic低}
        如果她当前状态确实是 energy低 + avoid高 + somatic低，
        那"冷"就是一个精准的诊断。

    算法：
        1. 获取 candidate_word 的 somatic delta
        2. 对每个维度，比较 delta 符号和当前状态的偏离方向
           - delta>0 表示词预期这个维度偏高 → 检查状态是否确实偏高
           - delta<0 表示词预期这个维度偏低 → 检查状态是否确实偏低
        3. 按 |delta| 加权平均匹配度
        4. 归一化到 [0, 1]

    中性维度（中性点附近的维度）不参与评分——如果状态接近 0.5，
    无论 delta 正负都不算"错"，只是这个词没在描述这个维度。

    返回：
        诊断精度 [0, 1]；无法映射时返回 0.5（中性）
    """
    delta = get_somatic_delta(
        candidate_word,
        top_k=top_k,
        min_similarity=min_similarity,
        propagation_weight=0.60,
    )

    if not delta:
        return 0.5

    match_sum = 0.0
    weight_sum = 0.0
    NEUTRAL_ZONE = 0.25  # |current - 0.5| < 0.25 时视为中性，不参与评分

    for dim, d in delta.items():
        if abs(d) < 1e-6:
            continue

        current = drive_state.get(dim, 0.5)
        # somatic_tone 和 prediction_error 范围是 [-1,1]，先映射到 [0,1]
        if dim in ("somatic_tone", "prediction_error"):
            mapped = (current + 1.0) / 2.0
        else:
            mapped = current

        # 偏离中性多少
        deviation = mapped - 0.5  # [-0.5, 0.5]
        if abs(deviation) < NEUTRAL_ZONE:
            continue  # 中性区，这个词没在描述这个维度

        dim_weight = abs(d)

        # 词的 delta 符号告诉我们它"预期"的方向
        word_expects_high = d > 0   # 词说这个维度应该高
        state_is_high = mapped > 0.5  # 状态确实高

        if word_expects_high == state_is_high:
            # 方向匹配——词准确描述了状态方向
            # 匹配度由偏离幅度决定：偏离越远，描述越精准
            match_quality = abs(deviation) * 2.0  # max ~1.0
            match_sum += dim_weight * match_quality
        else:
            # 方向矛盾——词的描述和实际状态相反
            match_sum -= dim_weight * abs(deviation) * 1.5  # 惩罚

        weight_sum += dim_weight

    if weight_sum < 1e-6:
        return 0.5

    raw = match_sum / weight_sum  # 可能在 [-1, 1] 附近
    # sigmoid 映射，让分数在 0~1 之间温和分布
    normalized = 1.0 / (1.0 + math.exp(-raw * 3.0))
    return max(0.0, min(1.0, normalized))


def get_counter_delta(
    word: str,
    scaling: float = 1.0,
) -> Dict[str, float]:
    """
    获取词的"帮助向量"——始终向中性/正常状态拉回。

    原理：
        词描述了一个偏离中性的身体状态（冷→能量低，热→能量高）。
        帮助不是选择性地强化或抵消——就是归中力。
        无论偏离是"愉快"还是"不愉快"，奖励都是回到正常。

        冷 {energy:-0.12, avoid:+0.15} → 帮助 {energy:+0.12, avoid:-0.15} 回暖
        好 {joy:+0.15, approach:+0.10} → 帮助 {joy:-0.15, approach:-0.10} 平复

        这是生理稳态——不是让你更舒服，是让你正常。

    参数：
        word    : 被准确描述的词
        scaling : 帮助强度系数

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

    参数：
        word          : 她说出的词
        drive_state   : 她当前的状态
        min_match     : 最低匹配阈值（低于此分数的帮助按比例缩减到 0）
        help_scaling  : 基础帮助强度

    返回：
        (match_score, help_delta_dict)
    """
    match = get_state_match_score(word, drive_state)

    if match >= min_match:
        # 连续奖励：帮助强度正比于匹配精度
        effective_scaling = help_scaling * match
        help_delta = get_counter_delta(word, scaling=effective_scaling)
        return match, help_delta
    elif match > 0.05:
        # 微匹配也有微帮助（渐入，无断崖）
        effective_scaling = help_scaling * match * 0.3
        help_delta = get_counter_delta(word, scaling=effective_scaling)
        return match, help_delta
    else:
        return match, {}


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

    参数：
        word         : 她说出的词
        entity       : EntityCore 实例
        drive_state  : 当前驱动力场
        min_match    : 最小匹配阈值
        help_scaling : 帮助强度

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
        # 施加帮助
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

        # 消力：她准确描述了自己 → unresolved 下降
        unresolved_drop = match * 0.08  # 匹配度越高，消力越多
        if hasattr(entity, "unresolved"):
            current_unresolved = float(getattr(entity, "unresolved", 0.5))
            entity.unresolved = max(0.0, current_unresolved - unresolved_drop)

        # ---- 可观测帮助事件 ----
        # 让她能归因因果链：我说了X → 系统理解了我 → 我变好了
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
        # 存储到 entity 上，供下一 tick 的 state_snapshot 读取
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


# 保留旧函数名的兼容别名
get_somatic_expected_score = get_state_match_score
apply_somatic_delta = lambda word, drive_state, scaling=1.0: {}  # 已废弃——v10 不再有魔法 delta


def list_anchors() -> List[Tuple[str, int]]:
    """列出所有锚点词及其覆盖的维度数。"""
    return [(word, len(deltas)) for word, deltas in SOMATIC_ANCHORS.items()]


def training_exploration_nudge(
    entity,
    drive_state: Dict[str, float],
    stuck_threshold: float = 0.35,
    nudge_strength: float = 0.015,
) -> Dict[str, float]:
    """
    训练探索扰动——对长时间锁死在极端值的维度施加微弱的归中力。

    设计原理：
        早期训练中，她可能困在某个状态区域出不来
        （如高 stress + 高 approach → 只能说"好/嗯"）。
        微弱的归中力让她自然漂移到新状态，接触到更多种子词。

        这不是硬阈值——力是连续的，且每 tick 的 nudge 很小 (0.015)，
        不足以跳变状态，只是加速自然漂移。

    参数：
        entity         : EntityCore 实例
        drive_state    : 当前驱动力场
        stuck_threshold: 偏离中性多少算"锁死"（默认 0.35，即 <0.15 或 >0.85）
        nudge_strength : 每 tick 的归中力强度

    返回：
        {dim: nudge_applied} dict
    """
    NEUTRAL = {
        "energy": 0.5, "loneliness": 0.3, "unresolved": 0.2,
        "boredom": 0.2, "fatigue": 0.1, "stress": 0.1,
        "approach_drive": 0.5, "avoid_drive": 0.5,
        "danger_level": 0.0, "curiosity": 0.5,
        "somatic_tone": 0.0,  # somatic_tone neutral = 0
    }

    applied = {}
    for dim, neutral in NEUTRAL.items():
        if not hasattr(entity, dim):
            continue
        current = float(getattr(entity, dim, neutral))
        deviation = current - neutral

        if abs(deviation) > stuck_threshold:
            # 向中性方向微推
            nudge = -deviation * nudge_strength  # 符号与偏离相反

            if dim in ("somatic_tone", "prediction_error"):
                lo, hi = -1.0, 1.0
            else:
                lo, hi = 0.0, 1.0
            setattr(entity, dim, max(lo, min(hi, current + nudge)))
            applied[dim] = round(nudge, 4)

    if applied:
        logger.debug(
            f"[SomaticMap] exploration nudge: "
            f"{', '.join(f'{k}{v:+.3f}' for k, v in applied.items())}"
        )

    return applied


def get_top_matches(
    drive_state: Dict[str, float],
    top_k: int = 5,
    min_score: float = 0.2,
    cluster_weights: Optional[Dict[str, float]] = None,
) -> List[Tuple[str, float]]:
    """
    对所有 29 个锚点词打分，返回 top-K。

    用于候选词选择：不只是取第 1 名，前几名都注入候选池，
    让词汇选择有多样性。

    v11.3: cluster_weights 来自长词训练积累，权重高的聚类得分会被微调上浮。

    参数：
        drive_state: 当前驱动力场
        top_k: 返回前几名
        min_score: 最低精度阈值
        cluster_weights: {anchor_word: weight} 聚类权重字典

    返回：
        [(word, match_score), ...] 按分降序
    """
    results = []
    for word in SOMATIC_ANCHORS:
        try:
            score = get_state_match_score(word, drive_state)
            # v11.3: 聚类权重微调（最多 ±15%，防止权重主导）
            if cluster_weights and word in cluster_weights:
                w = cluster_weights[word]
                # tanh 压缩到 [-0.15, +0.15] 范围
                bias = math.tanh(w * 0.5) * 0.15
                score = max(0.0, min(1.0, score + bias))
            if score >= min_score:
                results.append((word, score))
        except Exception:
            pass

    results.sort(key=lambda x: x[1], reverse=True)
    return results[:top_k]


def get_cluster_peers(
    word: str,
    min_similarity: float = 0.6,
) -> List[str]:
    """
    返回与给定词同簇的锚点词（语义相近，可作为词汇扩展）。

    用于发现奖励：当某个词匹配精度高时，注入同簇词到发现池。
    """
    if not _anchor_embeddings or not _anchor_words or word not in _anchor_words:
        return []

    try:
        import numpy as np
        word_idx = _anchor_words.index(word)
        word_emb = _anchor_embeddings[word]

        peers = []
        for i, anchor in enumerate(_anchor_words):
            if anchor == word:
                continue
            sim = float(np.dot(word_emb, _anchor_embeddings[anchor]))
            if sim >= min_similarity:
                peers.append((anchor, sim))

        peers.sort(key=lambda x: x[1], reverse=True)
        return [p[0] for p in peers[:5]]
    except Exception as e:
        logger.debug(f"[SomaticMap] get_cluster_peers('{word}') failed: {e}")
        return []


def find_closest_anchor(word: str, min_score: float = 0.3) -> Optional[Tuple[str, float]]:
    """
    用 BGE 找到一个词最近的体感锚点。

    v11.3: 长词（3+字）被选中后，找到它归属的体感聚类，
    用于调整聚类权重——让"好用"的聚类在体感匹配中更受重视。

    返回:
        (anchor_word, similarity) 或 None（无足够接近的锚点）
    """
    _ensure_anchor_embeddings()
    if not _anchor_embeddings or not _anchor_words:
        return None

    try:
        import numpy as np
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(
            "BAAI/bge-small-zh-v1.5",
            cache_folder=None,
            local_files_only=True,
        )
        word_emb = model.encode([word], normalize_embeddings=True)[0]

        best_anchor = None
        best_sim = -1.0
        for anchor_word in _anchor_words:
            anchor_emb = _anchor_embeddings[anchor_word]
            sim = float(np.dot(word_emb, anchor_emb))
            if sim > best_sim:
                best_sim = sim
                best_anchor = anchor_word

        if best_sim >= min_score and best_anchor is not None:
            return (best_anchor, best_sim)
        return None
    except Exception as e:
        logger.debug(f"[SomaticMap] find_closest_anchor('{word}') failed: {e}")
        return None
