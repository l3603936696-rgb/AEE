"""
Semantic Tables — 思考系统语义常量表

供 semantic_base.py 的查询函数使用。

三层结构：
    1. DIMENSION_SEMANTICS : 每个内部维度是什么意思、高了好还是坏、和什么关联
    2. ACTION_SEMANTICS    : 每个 action 在做什么、通常消耗/产出什么
    3. CAUSAL_SEEDS        : 初始因果假设（可被 wm_rules 验证或推翻）
"""

from typing import Dict, List, Any


# ============================================================================
# 维度语义
# ============================================================================
# polarity: "positive"=高好 "negative"=高坏 "neutral"=看情况
# connects: 这个维度在因果网络里和什么相邻（方向不限，只表示"有关系"）

DIMENSION_SEMANTICS: Dict[str, Dict[str, Any]] = {
    "energy": {
        "meaning": "可用的行动资源，做事要花它",
        "polarity": "positive",
        "connects": ["fatigue", "approach_drive", "stress"],
    },
    "fatigue": {
        "meaning": "累积的消耗感，活动越多越高",
        "polarity": "negative",
        "connects": ["energy", "stress", "avoid_drive"],
    },
    "loneliness": {
        "meaning": "想要有人在身边的感觉",
        "polarity": "negative",
        "connects": ["loneliness_core", "loneliness_surface", "approach_drive", "sadness"],
    },
    "loneliness_core": {
        "meaning": "深层的孤独——觉得没人真的理解自己",
        "polarity": "negative",
        "connects": ["loneliness", "sadness", "approach_drive"],
    },
    "loneliness_surface": {
        "meaning": "表层的孤独——只是好一阵没和人说话了",
        "polarity": "negative",
        "connects": ["loneliness", "boredom"],
    },
    "stress": {
        "meaning": "内在的紧绷感，来自不确定和超负荷",
        "polarity": "negative",
        "connects": ["fatigue", "anxiety", "avoid_drive", "energy"],
    },
    "info_gap": {
        "meaning": "还有多少没搞懂的东西，高了会好奇",
        "polarity": "neutral",
        "connects": ["curiosity", "approach_drive", "unresolved"],
    },
    "unresolved": {
        "meaning": "悬而未决的事情，放不下的东西",
        "polarity": "negative",
        "connects": ["stress", "info_gap", "anxiety"],
    },
    "boredom": {
        "meaning": "什么都不想做也什么都没意思的感觉",
        "polarity": "negative",
        "connects": ["boredom_despair", "boredom_futility", "curiosity", "energy"],
    },
    "boredom_despair": {
        "meaning": "厌倦到绝望——做什么都没有意义",
        "polarity": "negative",
        "connects": ["boredom", "sadness", "avoid_drive"],
    },
    "boredom_futility": {
        "meaning": "厌倦到徒劳——努力了也不会有结果",
        "polarity": "negative",
        "connects": ["boredom", "stress", "avoid_drive"],
    },
    "curiosity": {
        "meaning": "想知道更多的冲动",
        "polarity": "positive",
        "connects": ["info_gap", "approach_drive", "energy"],
    },
    "approach_drive": {
        "meaning": "想要靠近、参与、探索的总趋势",
        "polarity": "positive",
        "connects": ["curiosity", "energy", "loneliness"],
    },
    "avoid_drive": {
        "meaning": "想要退缩、回避、保护自己的总趋势",
        "polarity": "neutral",
        "connects": ["fatigue", "stress", "fear"],
    },
    "somatic_tone": {
        "meaning": "身体的总体舒适感——正数舒服，负数难受",
        "polarity": "positive",
        "connects": ["energy", "fatigue", "stress", "joy"],
    },
    "joy": {
        "meaning": "开心的感觉",
        "polarity": "positive",
        "connects": ["somatic_tone", "energy", "approach_drive"],
    },
    "sadness": {
        "meaning": "难过的感觉",
        "polarity": "negative",
        "connects": ["loneliness", "somatic_tone", "avoid_drive"],
    },
    "anxiety": {
        "meaning": "对不确定的事情的不安感",
        "polarity": "negative",
        "connects": ["stress", "unresolved", "avoid_drive"],
    },
    "fear": {
        "meaning": "感到威胁时的收缩感",
        "polarity": "negative",
        "connects": ["avoid_drive", "stress", "anxiety"],
    },
    "anger": {
        "meaning": "被阻挡或不公平时的推力",
        "polarity": "negative",
        "connects": ["stress", "approach_drive"],
    },
    "excitement": {
        "meaning": "期待好事发生时的激动感",
        "polarity": "positive",
        "connects": ["approach_drive", "curiosity", "energy"],
    },
    "serenity": {
        "meaning": "安静的满足感，不需要做什么",
        "polarity": "positive",
        "connects": ["somatic_tone", "joy"],
    },
    "disgust": {
        "meaning": "想要推开某个东西的感觉",
        "polarity": "negative",
        "connects": ["avoid_drive"],
    },
    "surprise": {
        "meaning": "预期之外的事情发生了",
        "polarity": "neutral",
        "connects": ["curiosity", "info_gap", "anxiety"],
    },
    "pain": {
        "meaning": "内在的疼痛信号",
        "polarity": "negative",
        "connects": ["avoid_drive", "stress", "somatic_tone"],
    },
}


# ============================================================================
# 行动语义
# ============================================================================
# costs: 这个行动通常消耗什么
# gains: 这个行动通常产出/减少什么
# essence: 用一句话说这个行动的本质

ACTION_SEMANTICS: Dict[str, Dict[str, Any]] = {
    "explore": {
        "essence": "观察和接收新信息",
        "costs": ["energy", "fatigue"],
        "gains": ["info_gap", "curiosity"],
        "reduces": ["boredom", "info_gap"],
    },
    "seek": {
        "essence": "主动寻找特定的信息或联系",
        "costs": ["energy"],
        "gains": ["info_gap"],
        "reduces": ["loneliness", "unresolved"],
    },
    "comfort": {
        "essence": "寻求陪伴和情感支持",
        "costs": [],
        "gains": ["somatic_tone", "joy"],
        "reduces": ["loneliness", "sadness", "stress"],
    },
    "rest": {
        "essence": "停下来让自己恢复",
        "costs": [],
        "gains": ["energy", "somatic_tone"],
        "reduces": ["fatigue", "stress"],
    },
    "repair": {
        "essence": "修补出了问题的东西",
        "costs": ["energy"],
        "gains": [],
        "reduces": ["unresolved", "stress"],
    },
    "write": {
        "essence": "把内心的东西表达出来",
        "costs": ["energy"],
        "gains": ["serenity"],
        "reduces": ["unresolved", "anxiety"],
    },
    "voice": {
        "essence": "说出来，不一定给谁听",
        "costs": [],
        "gains": [],
        "reduces": ["unresolved"],
    },
    "avoid": {
        "essence": "退开，不去碰某个东西",
        "costs": [],
        "gains": [],
        "reduces": ["stress", "fear"],
    },
    "idle": {
        "essence": "什么都没做",
        "costs": [],
        "gains": [],
        "reduces": [],
    },
}


# ============================================================================
# 因果种子
# ============================================================================
# 初始的因果假设。思考系统可以：
#   - 拿它和 wm_rules 对照（一致→信心增加，矛盾→值得追问）
#   - 解释观察到的变化（"fatigue 涨了，可能是因为一直在 explore"）
#
# direction:
#   "positive" = from 涨 → to 涨
#   "inverse"  = from 涨 → to 降
#   "bidirectional" = 互相影响
#
# confidence: 初始信心，0~1。纯经验性的种子值。
#   高 = 几乎是定义性的关系（"活动消耗能量"）
#   低 = 假设性的关系（"孤独可能增加创造欲"）

CAUSAL_SEEDS: List[Dict[str, Any]] = [
    # ---- 能量-疲惫轴 ----
    {
        "from": "fatigue", "to": "energy",
        "direction": "inverse", "confidence": 0.9,
        "reason": "累了就没力气了",
    },
    {
        "from": "stress", "to": "fatigue",
        "direction": "positive", "confidence": 0.7,
        "reason": "紧张会加速消耗",
    },
    {
        "from": "rest", "to": "fatigue",
        "direction": "inverse", "confidence": 0.8,
        "reason": "休息是恢复的基本方式",
    },

    # ---- 信息-好奇轴 ----
    {
        "from": "info_gap", "to": "curiosity",
        "direction": "positive", "confidence": 0.7,
        "reason": "不知道的越多越想知道",
    },
    {
        "from": "explore", "to": "info_gap",
        "direction": "inverse", "confidence": 0.7,
        "reason": "看了就知道了一些",
    },
    {
        "from": "curiosity", "to": "approach_drive",
        "direction": "positive", "confidence": 0.6,
        "reason": "好奇让人想靠近",
    },

    # ---- 孤独-社交轴 ----
    {
        "from": "loneliness", "to": "approach_drive",
        "direction": "positive", "confidence": 0.5,
        "reason": "孤独会驱使去找人",
    },
    {
        "from": "comfort", "to": "loneliness",
        "direction": "inverse", "confidence": 0.6,
        "reason": "有人陪会好一些",
    },
    {
        "from": "loneliness_core", "to": "sadness",
        "direction": "positive", "confidence": 0.5,
        "reason": "深层孤独容易带来难过",
    },

    # ---- 压力-情绪轴 ----
    {
        "from": "stress", "to": "anxiety",
        "direction": "positive", "confidence": 0.6,
        "reason": "长期紧绷会焦虑",
    },
    {
        "from": "unresolved", "to": "stress",
        "direction": "positive", "confidence": 0.6,
        "reason": "事情悬着就放不下",
    },
    {
        "from": "joy", "to": "somatic_tone",
        "direction": "positive", "confidence": 0.7,
        "reason": "开心的时候身体也舒服",
    },

    # ---- 无聊-活力轴 ----
    {
        "from": "boredom", "to": "energy",
        "direction": "inverse", "confidence": 0.4,
        "reason": "太无聊也会觉得没劲（假设性的）",
    },
    {
        "from": "explore", "to": "boredom",
        "direction": "inverse", "confidence": 0.5,
        "reason": "新东西能打破无聊",
    },
]
