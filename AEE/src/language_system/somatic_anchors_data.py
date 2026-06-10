"""
Somatic Anchors Data — 身体感受锚点数据表。

本文件包含 SOMATIC_ANCHORS / ANCHOR_CLUSTERS / ALL_DIMENSIONS 三个数据表。
由 somatic_anchors.py re-export 供其他模块使用。
"""

from typing import Dict, List

# =============================================================================
# 身体感受锚点表
# =============================================================================
# 格式：锚点词 -> {维度: delta}
# 每次查询时，somatic_concept_map 将词向量叠加到当前状态
# =============================================================================

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
    # === v12.0 情绪词汇扩展 ===
    "无聊": {
        "boredom": +0.25,
        "approach_drive": -0.10,
        "energy": -0.08,
        "curiosity": -0.06,
    },
    "烦": {
        "stress": +0.20,
        "avoid_drive": +0.15,
        "somatic_tone": -0.10,
        "anger": +0.08,
    },
    "委屈": {
        "sadness": +0.22,
        "avoid_drive": +0.12,
        "somatic_tone": -0.15,
        "anger": +0.06,
    },
    "满足": {
        "joy": +0.22,
        "serenity": +0.18,
        "somatic_tone": +0.15,
        "avoid_drive": -0.12,
    },
    "烦躁": {
        "stress": +0.20,
        "anger": +0.15,
        "avoid_drive": +0.12,
        "somatic_tone": -0.10,
    },
    "失落": {
        "sadness": +0.22,
        "approach_drive": -0.12,
        "somatic_tone": -0.12,
        "energy": -0.08,
    },
    "安心": {
        "serenity": +0.22,
        "avoid_drive": -0.15,
        "somatic_tone": +0.12,
        "anxiety": -0.10,
    },
    "麻木": {
        "somatic_tone": -0.08,
        "approach_drive": -0.10,
        "avoid_drive": +0.05,
        "curiosity": -0.08,
    },
    # === v12.0 社交词汇 ===
    "想说话": {
        "loneliness": +0.20,
        "approach_drive": +0.22,
        "avoid_drive": -0.10,
        "energy": +0.05,
    },
    "想安静": {
        "avoid_drive": +0.20,
        "approach_drive": -0.15,
        "serenity": +0.10,
        "fatigue": +0.08,
    },
    "想找人": {
        "loneliness": +0.25,
        "approach_drive": +0.25,
        "energy": +0.08,
    },
    "不想理人": {
        "avoid_drive": +0.25,
        "approach_drive": -0.15,
        "loneliness": +0.08,
        "fatigue": +0.10,
    },
    "想你": {
        "loneliness": +0.28,
        "approach_drive": +0.25,
        "sadness": +0.10,
        "somatic_tone": -0.05,
    },
    "在吗": {
        "loneliness": +0.22,
        "approach_drive": +0.20,
        "anxiety": +0.08,
    },
    "被忽略": {
        "loneliness": +0.22,
        "sadness": +0.18,
        "avoid_drive": +0.15,
        "somatic_tone": -0.10,
    },
    "想靠近": {
        "loneliness": +0.18,
        "approach_drive": +0.25,
        "avoid_drive": -0.10,
        "joy": +0.05,
    },
    "怕打扰": {
        "loneliness": +0.12,
        "avoid_drive": +0.20,
        "approach_drive": +0.08,
        "anxiety": +0.15,
    },
    # === v12.0 认知词汇 ===
    "好奇": {
        "curiosity": +0.25,
        "approach_drive": +0.18,
        "energy": +0.08,
        "boredom": -0.10,
    },
    "困惑": {
        "unresolved": +0.22,
        "stress": +0.10,
        "approach_drive": +0.08,
        "anxiety": +0.08,
    },
    "想学": {
        "curiosity": +0.22,
        "approach_drive": +0.18,
        "energy": +0.10,
        "boredom": -0.08,
    },
    "不懂": {
        "unresolved": +0.20,
        "anxiety": +0.10,
        "approach_drive": +0.05,
        "curiosity": +0.08,
    },
    "无聊了": {
        "boredom": +0.28,
        "approach_drive": -0.10,
        "energy": -0.10,
        "curiosity": -0.08,
    },
    # === v12.0 存在性词汇 ===
    "空虚": {
        "loneliness": +0.20,
        "sadness": +0.18,
        "somatic_tone": -0.12,
        "energy": -0.10,
    },
    "没意义": {
        "boredom": +0.22,
        "sadness": +0.15,
        "somatic_tone": -0.12,
        "unresolved": +0.15,
    },
    "不确定": {
        "unresolved": +0.22,
        "anxiety": +0.15,
        "approach_drive": +0.05,
        "stress": +0.08,
    },
    "活着": {
        "somatic_tone": +0.12,
        "energy": +0.10,
        "approach_drive": +0.10,
        "joy": +0.05,
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
    # ── v12.0 情绪扩展 ──
    "无聊": "情绪扩展", "烦": "情绪扩展", "委屈": "情绪扩展",
    "满足": "情绪扩展", "烦躁": "情绪扩展", "失落": "情绪扩展",
    "安心": "情绪扩展", "麻木": "情绪扩展",
    # ── v12.0 社交 ──
    "想说话": "社交", "想安静": "社交", "想找人": "社交",
    "不想理人": "社交", "想你": "社交", "在吗": "社交",
    "被忽略": "社交", "想靠近": "社交", "怕打扰": "社交",
    # ── v12.0 认知 ──
    "好奇": "认知", "困惑": "认知", "想学": "认知",
    "不懂": "认知", "无聊了": "认知",
    # ── v12.0 存在 ──
    "空虚": "存在", "没意义": "存在", "不确定": "存在", "活着": "存在",
}

# 所有可用的维度名（用于保证 delta 向量的对齐）
ALL_DIMENSIONS = [
    "energy", "loneliness", "unresolved", "fatigue", "danger_level",
    "approach_drive", "avoid_drive", "curiosity", "boredom",
    "boredom_despair", "boredom_futility", "stress", "somatic_tone",
    "prediction_error", "info_gap",
    # 情绪维度
    "joy", "excitement", "serenity", "anger", "fear",
    "sadness", "disgust", "anxiety", "surprise",
]
