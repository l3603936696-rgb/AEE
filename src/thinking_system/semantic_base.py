"""
Semantic Base — 思考系统的语义底座

给维度名、行动名附上含义，让思考系统不再只操作裸数字。

这不是行为路由——不告诉她"该做什么"。
这是解读工具——让她知道"这些数字代表什么"，
从而能问出有意义的问题、做出有根据的推断。

三层结构：
    1. 维度语义：每个内部维度是什么意思、高了好还是坏、和什么关联
    2. 行动语义：每个 action 在做什么、通常消耗/产出什么
    3. 因果种子：初始因果假设（可被 wm_rules 验证或推翻）

使用方式：
    思考系统引用这里的数据来：
    - 生成可读的问题（不再是"这条规则可靠吗"而是"explore 减少好奇心的代价值得吗"）
    - 解读规则（知道 delta 方向的含义）
    - 发现规则与因果种子的矛盾（更有价值的问题）
"""

from typing import Dict, List, Any, Optional


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


# ============================================================================
# 查询接口（供思考系统调用）
# ============================================================================

def get_dim_meaning(dim: str) -> str:
    """查维度含义，找不到返回维度名本身。"""
    info = DIMENSION_SEMANTICS.get(dim)
    return info["meaning"] if info else dim


def get_dim_polarity(dim: str) -> str:
    """查维度极性。positive/negative/neutral，未知返回 neutral。"""
    info = DIMENSION_SEMANTICS.get(dim)
    return info["polarity"] if info else "neutral"


def get_action_essence(action: str) -> str:
    """查行动本质描述。"""
    info = ACTION_SEMANTICS.get(action)
    return info["essence"] if info else action


def interpret_delta(dim: str, delta: float) -> str:
    """
    把一个 delta 翻译成可读的描述。

    例如：interpret_delta("fatigue", 0.05) → "疲惫加重了一点（累积的消耗感）"
          interpret_delta("info_gap", -0.15) → "好奇心被满足了一些（还有多少没搞懂的东西）"
    """
    info = DIMENSION_SEMANTICS.get(dim)
    if not info:
        direction = "上升" if delta > 0 else "下降"
        return f"{dim}{direction}了{abs(delta):.2f}"

    meaning = info["meaning"]
    polarity = info["polarity"]

    if delta > 0:
        if polarity == "negative":
            tone = "加重了"
        elif polarity == "positive":
            tone = "增强了"
        else:
            tone = "上升了"
    else:
        if polarity == "negative":
            tone = "减轻了"
        elif polarity == "positive":
            tone = "减弱了"
        else:
            tone = "下降了"

    magnitude = "一点" if abs(delta) < 0.05 else ("不少" if abs(delta) > 0.15 else "一些")
    return f"{dim}{tone}{magnitude}（{meaning}）"


def find_causal_path(from_dim: str, to_dim: str) -> Optional[Dict]:
    """找两个维度之间的因果种子，找不到返回 None。"""
    for seed in CAUSAL_SEEDS:
        if seed["from"] == from_dim and seed["to"] == to_dim:
            return seed
        if seed["direction"] == "bidirectional":
            if seed["from"] == to_dim and seed["to"] == from_dim:
                return seed
    return None


def find_related_seeds(dim: str) -> List[Dict]:
    """找和某个维度相关的所有因果种子。"""
    result = []
    for seed in CAUSAL_SEEDS:
        if seed["from"] == dim or seed["to"] == dim:
            result.append(seed)
    return result


def check_rule_against_seeds(rule: dict) -> Optional[Dict[str, Any]]:
    """
    拿一条 wm_rule 和因果种子对照。

    返回：
        None — 没有可对照的种子
        {"status": "consistent", ...} — 规则和种子一致
        {"status": "contradicts", ...} — 规则和种子矛盾（值得追问）
        {"status": "novel", ...} — 规则发现了种子没有的关系（值得记住）
    """
    deltas = rule.get("expected_deltas")
    if not deltas or not isinstance(deltas, dict):
        return None

    # 从 trigger 提取 action
    trigger = ""
    predicts = rule.get("predicts")
    if isinstance(predicts, dict):
        trigger = str(predicts.get("trigger", ""))
    action = ""
    for a in ACTION_SEMANTICS:
        if a in trigger:
            action = a
            break

    if not action:
        return None

    # 对每个显著 delta，查因果种子
    for dim, delta_val in deltas.items():
        try:
            d = float(delta_val)
        except (TypeError, ValueError):
            continue
        if abs(d) < 0.01:
            continue

        # 查 action → dim 的因果种子
        seed = find_causal_path(action, dim)
        if seed:
            # 判断方向一致性
            expected_inverse = seed["direction"] == "inverse"
            actual_inverse = d < 0
            if expected_inverse == actual_inverse:
                return {
                    "status": "consistent",
                    "rule_id": rule.get("id", "?"),
                    "seed": seed,
                    "dim": dim,
                    "delta": d,
                    "interpretation": f"{action}{'减少' if d < 0 else '增加'}了{dim}，"
                                      f"和预期一致（{seed['reason']}）",
                }
            else:
                return {
                    "status": "contradicts",
                    "rule_id": rule.get("id", "?"),
                    "seed": seed,
                    "dim": dim,
                    "delta": d,
                    "interpretation": f"{action}本应{'减少' if expected_inverse else '增加'}{dim}，"
                                      f"但实际{'增加' if d > 0 else '减少'}了——为什么？",
                }

        # 没有种子 → 新发现
        if abs(d) > 0.03:
            return {
                "status": "novel",
                "rule_id": rule.get("id", "?"),
                "dim": dim,
                "delta": d,
                "action": action,
                "interpretation": f"发现{action}会{'增加' if d > 0 else '减少'}{dim}"
                                  f"（{get_dim_meaning(dim)}），这是新的",
            }

    return None
