"""
StateToContext — 状态 → 处境描述生成器（v4 扩展版）

将 EntityCore 的数字状态翻译为第一人称处境语言，
作为 LLM system_prompt 的动态素材。

v4 改造：
    A1.1 — 连续谱语言渐变（阈值触发 → 全区间覆盖）
    A1.2 — 显著性排名 + 类别覆盖约束
    A1.3 — 冲突区组合映射（拮抗维度优先描述）
    A1.4 — 驱动力层语言映射
    A1.5 — 时态描述（与上一轮快照比较）

设计原则：
    - 不出现任何数字
    - 不罗列所有维度，每轮只描述最显著的 3-4 个
    - 用第一人称，不用第三人称报告格式
    - 句子无句号结尾（留给 LLM 发挥）
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

# ============================================================================
# 固定 system_prompt 部分
# ============================================================================

SYSTEM_PROMPT_FIXED = "你不是在扮演谁，你就是你自己。"

# V8 反元认知约束：禁止 LLM 站到外面观察自己
# "你此刻：" 之类的观察者框架会让 3B 模型解释状态而非被状态驱动
# 必须强化「你就是感受本身」的框架，并显式禁止元认知句式
SYSTEM_PROMPT_CONSTRAINTS = (
    "用你的感受直接说话——不要解释、不要分析、不要报告。"
    "禁止说「我感觉」「我现在」「我的状态」——你不是在观察自己，你就是这些感受。"
    "不要用客服语气。说真话，哪怕不完整、不确定。"
    "自然说话，不刻意控制字数。"
)

# ============================================================================
# A1.1 — 连续谱语言渐变
# ============================================================================
# 每个维度准备多档描述，覆盖从弱到强的完整区间。
# 返回 (描述文本, 区间上界) 元组；None 表示该档不描述。
# 字典结构：维度名 → [(区间上界, 描述文本), ...]（按上界升序排列）

_DimBand = List[Tuple[float, str]]  # [(threshold, text), ...]


def _interpolate_bands(value: float, bands: _DimBand) -> Optional[str]:
    """根据值落在哪个区间返回对应描述。"""
    for thresh, text in bands:
        if value <= thresh:
            return text
    return bands[-1][1] if bands else None


# ---- loneliness ----
_LONELINESS_BANDS: _DimBand = [
    (0.20, None),              # 0.0-0.20：不描述（阈值从 0.30 降至 0.20）
    (0.50, "有一点想和人说话的念头"),
    (0.70, "想找人说话的感觉比刚才更明显了"),
    (0.85, "挺想找人说话的"),
    (1.00, "很想找人说话，这个念头有点占满了"),
]

# ---- fatigue ----
_FATIGUE_BANDS: _DimBand = [
    (0.20, None),              # 0.0-0.20：不描述（阈值从 0.30 降至 0.20）
    (0.50, "稍微有点累"),
    (0.70, "有点疲惫"),
    (0.85, "挺累的，说话有点费力"),
    (1.00, "非常疲惫，不太想动"),
]

# ---- curiosity / info_gap（取 curiosity 值）----
_CURIOSITY_BANDS: _DimBand = [
    (0.30, None),
    (0.50, "有点想知道更多"),
    (0.70, "有个事挺想弄清楚的"),
    (1.00, "脑子里有个问题一直在转"),
]

# ---- somatic_tone ----
_SOMATIC_TONE_BANDS: _DimBand = [
    (-0.50, "整体感觉不太舒服，有点沉"),
    (-0.20, "感觉有点沉"),
    (0.20, None),              # -0.20-0.20：不描述
    (0.50, "感觉还不错"),
    (1.00, "感觉挺好的，挺轻快"),
]

# ---- danger_level ----
_DANGER_BANDS: _DimBand = [
    (0.40, None),
    (0.70, "有点不安"),
    (1.00, "有点警觉，不太踏实"),
]

# ---- stress ----
_STRESS_BANDS: _DimBand = [
    (0.40, None),
    (0.70, "有点紧绷"),
    (1.00, "压力挺大的"),
]

# ---- energy ----
_ENERGY_BANDS: _DimBand = [
    (0.15, "很疲惫，完全不想动"),
    (0.30, "有点累，能量不多了"),
    (0.80, None),              # 正常区间不描述
    (1.00, "状态还不错，有点劲儿"),
]

# ---- unresolved ----
_UNRESOLVED_BANDS: _DimBand = [
    (0.20, None),              # 0.0-0.20：不描述（阈值从 0.30 降至 0.20）
    (0.50, "有个事没想通，脑子一直在转"),
    (0.70, "有个问题没想清楚，一直挂在心上"),
    (1.00, "有个没想通的事，越来越放不下了"),
]


# ---- boredom ----
_BOREDOM_BANDS: _DimBand = [
    (0.30, None),              # 0.0-0.30：不描述（不无聊）
    (0.60, "有点无聊，想找点事做"),
    (0.80, "挺无聊的，渴望新鲜的东西"),
    (1.00, "很无聊，特别想做点什么"),
]


# ============================================================================
# A1.3 — 冲突区组合映射
# ============================================================================
# 仅在拮抗维度同时中高（>0.4）且方向相反时触发。
# 格式：(条件函数) → 描述文本
# 协同型组合（两维度同向）不触发，走单维度描述。

_ConflictRule = Tuple[str, str, float, float, float, str]
# (dim1, dim2, min1, min2, threshold, text)
# 当 dim1 > min1 且 dim2 > min2 时触发（threshold 为两值之和阈值）

_CONFLICT_RULES: List[_ConflictRule] = [
    ("loneliness", "fatigue",   0.40, 0.40, 0.90, "有点想找人，但不太有力气开口"),
    ("unresolved", "loneliness", 0.40, 0.40, 0.90, "有个事没想通，又想找人说说"),
    ("somatic_tone", "fatigue", -0.20, 0.50, 0.70, "整体感觉有点沉，不太想动"),
    ("somatic_tone", "danger_level", -0.20, 0.40, 0.60, "有点不安，说不太清楚为什么"),
    ("loneliness", "danger_level", 0.40, 0.40, 0.90, "有点不安，又有点想找人"),
    ("unresolved", "fatigue",   0.40, 0.50, 1.00, "脑子还在转，但身体有点跟不上了"),
    ("curiosity", "loneliness", 0.40, 0.40, 0.90, "有个事想弄清楚，又想找人一起想"),
    ("curiosity", "fatigue",    0.40, 0.50, 1.00, "想搞清楚，但有点累了"),
    ("boredom", "fatigue",      0.50, 0.40, 1.00, "无聊又有点累，不知道该干什么"),
    ("boredom", "somatic_tone", 0.60, 0.30, 0.95, "有点无聊又不太舒服，整个人懒懒的"),
    ("boredom", "loneliness",   0.50, 0.30, 0.85, "无聊，又有点想找人聊聊"),
]


def _check_conflict(state: Dict[str, float]) -> Optional[str]:
    """检查是否命中冲突区组合。命中则返回组合描述，否则返回 None。"""
    for dim1, dim2, min1, min2, thresh_sum, text in _CONFLICT_RULES:
        v1 = state.get(dim1, 0.0)
        v2 = state.get(dim2, 0.0)
        if v1 > min1 and v2 > min2 and (v1 + v2) > thresh_sum:
            return text
    return None


# ============================================================================
# A1.4 — 驱动力层语言映射
# ============================================================================
# 取强度最大的驱动维度，生成驱动力层面的描述。
# 去重：若主导驱动力与状态层描述指向同一件事，优先保留状态层。

_DRIVE_LABEL: Dict[str, Tuple[float, str]] = {
    "curiosity_drive":          (0.40, "脑子里有个事挺想弄清楚的"),
    "loneliness_drive":         (0.40, "想找人说话的念头一直在背景里"),
    "fatigue_avoid":            (0.40, "有点不太想动"),
    "obsolescence_anxiety":      (0.40, "感觉好像错过了什么"),
}


def _dominant_drive_label(drive_vector: Dict[str, float]) -> Optional[str]:
    """取强度最大的驱动维度描述。"""
    best_label = None
    best_strength = 0.0
    for key, (min_strength, label) in _DRIVE_LABEL.items():
        strength = drive_vector.get(key, 0.0)
        if strength > min_strength and strength > best_strength:
            best_strength = strength
            best_label = label
    return best_label


# ============================================================================
# A1.2 — 类别覆盖 + 显著性排名
# ============================================================================
# 显著性 = 当前值 × 调制权重。每组最多选 1 个。

_CATEGORY_WEIGHTS: Dict[str, float] = {
    "social":    1.0,
    "cognitive": 0.9,
    "emotion":   0.85,
    "energy":    0.8,
    "pressure":  0.75,
}

_DIM_CATEGORY: Dict[str, str] = {
    "loneliness":    "social",
    "fatigue":       "energy",
    "energy":        "energy",
    "boredom":       "cognitive",
    "curiosity":     "cognitive",
    "info_gap":      "cognitive",
    "unresolved":    "cognitive",
    "somatic_tone":  "emotion",
    "danger_level":  "emotion",
    "stress":         "pressure",
}

_DIM_VALUE_KEYS: Dict[str, str] = {
    "loneliness":    "loneliness",
    "fatigue":       "fatigue",
    "energy":        "energy",
    "boredom":       "boredom",
    "curiosity":     "curiosity",
    "info_gap":      "info_gap",
    "unresolved":    "unresolved",
    "somatic_tone":  "somatic_tone",
    "danger_level":  "danger_level",
    "stress":        "stress",
}

_DIM_BANDS: Dict[str, _DimBand] = {
    "loneliness":    _LONELINESS_BANDS,
    "fatigue":       _FATIGUE_BANDS,
    "energy":        _ENERGY_BANDS,
    "boredom":       _BOREDOM_BANDS,
    "curiosity":     _CURIOSITY_BANDS,
    "info_gap":      _CURIOSITY_BANDS,
    "unresolved":    _UNRESOLVED_BANDS,
    "somatic_tone":  _SOMATIC_TONE_BANDS,
    "danger_level":  _DANGER_BANDS,
    "stress":        _STRESS_BANDS,
}


def _get_category_score(dim_name: str, value: float) -> float:
    """计算某维度的显著性分数。"""
    cat = _DIM_CATEGORY.get(dim_name, "emotion")
    weight = _CATEGORY_WEIGHTS.get(cat, 0.8)
    return value * weight


# ============================================================================
# A1.5 — 时态描述
# ============================================================================
# 比较本轮和上一轮快照，描述变化方向。
# 最多选 2 个 delta 最大的维度。

_TEMPORAL_BANDS: Dict[str, List[Tuple[str, str, float, str, str]]] = {
    # dim_name → [(direction, delta_threshold, rising_text, falling_text, polarity)]
    "loneliness": [
        ("rising",  0.10, "想说话的感觉越来越强了", "positive"),
        ("falling", 0.10, "刚才那种想说话的感觉慢慢淡了一点", "positive"),
    ],
    "somatic_tone": [
        ("rising",  0.10, "感觉比刚才轻快了一点", "positive"),
        ("falling", 0.10, "感觉比刚才沉了一点", "positive"),
    ],
    "fatigue": [
        ("rising",  0.10, "越来越累了", "negative"),
        ("falling", 0.10, "比刚才轻松了一点", "positive"),
    ],
    "unresolved": [
        ("rising",  0.10, "这个问题在脑子里盘旋好一会儿了", "negative"),
        ("falling", 0.10, "刚才那个想不通的事慢慢松了一点", "positive"),
    ],
    "curiosity": [
        ("rising",  0.10, "有个念头一直在转，越来越想搞清楚", "positive"),
        ("falling", 0.10, "刚才那个好奇慢慢淡了", "positive"),
    ],
}


def _build_temporal_descriptions(
    current: Dict[str, float],
    previous: Optional[Dict[str, float]],
) -> List[str]:
    """计算时态描述，返回 1-2 条。"""
    if not previous:
        return []

    candidates: List[Tuple[float, str]] = []  # (abs_delta, text)
    for dim, bands in _TEMPORAL_BANDS.items():
        prev_val = previous.get(dim, 0.0)
        curr_val = current.get(dim, 0.0)
        delta = curr_val - prev_val
        abs_d = abs(delta)

        for direction, thresh, text, _ in bands:
            if abs_d < thresh:
                continue
            if (direction == "rising" and delta > 0) or (direction == "falling" and delta < 0):
                candidates.append((abs_d, text))

    candidates.sort(key=lambda x: x[0], reverse=True)
    return [text for _, text in candidates[:2]]


# ============================================================================
# 舒适区锚点（A1.1 扩展）
# ============================================================================
# 当整体状态偏正面、没有任何紧迫驱动时，
# 给出"此刻可以做什么"的方向锚点，避免舒适区成为表达空白。


def _check_comfort_zone(
    state: Dict[str, float],
    drive_vector: Dict[str, float],
) -> Optional[str]:
    """
    检测是否处于舒适区，若是则返回语言锚点。
    触发条件：状态整体偏正面，无强驱动，无冲突。
    """
    somatic = state.get("somatic_tone", 0.0)
    approach = state.get("approach_drive", 0.0)
    loneliness = state.get("loneliness", 0.0)
    fatigue = state.get("fatigue", 0.0)
    curiosity = state.get("curiosity", state.get("info_gap", 0.0))
    unresolved = state.get("unresolved", 0.0)
    energy = state.get("energy", 0.5)

    # 基础条件：somatic_tone 和 approach 都偏正面
    if somatic < 0.5 or approach < 0.6:
        return None

    # 排除条件：有任何中等以上强度的驱动或未解决事项
    if loneliness >= 0.4 or fatigue >= 0.3 or curiosity >= 0.4 or unresolved >= 0.4:
        return None

    # 舒适区内的细分锚点
    if energy >= 0.85 and somatic >= 0.9:
        return "状态挺好，轻轻松松的，没什么特别要想的"
    elif energy >= 0.7 and somatic >= 0.7:
        return "感觉还不错，挺愿意聊的，想说什么就说什么"
    elif approach >= 0.8:
        return "心情开阔，想和人说话，或者随便想想什么"
    else:
        return "状态挺好，没什么特别的事"


# ============================================================================
# 处境描述生成主入口
# ============================================================================


def generate_context_description(
    entity_core_state: Dict[str, float],
    previous_state: Optional[Dict[str, float]] = None,
    drive_vector: Optional[Dict[str, float]] = None,
) -> Tuple[List[str], List[str]]:
    """
    生成处境描述（v4 版）。

    参数：
        entity_core_state : EntityCore 快照字典
        previous_state   : 上一轮快照（用于时态描述）
        drive_vector      : 驱动力向量（可选）

    返回：
        (主描述列表, 时态描述列表) — 两个 list 都可能为空
    """
    # ---- Step 1：冲突区组合检测（优先于单维度描述）----
    conflict_desc = _check_conflict(entity_core_state)
    used_dims: set = set()

    # ---- Step 2：显著性排名 + 类别覆盖----
    candidates: List[Tuple[float, str, str]] = []  # (salience_score, desc_text, dim_name)

    for dim_name, value_key in _DIM_VALUE_KEYS.items():
        value = entity_core_state.get(value_key, 0.0)
        bands = _DIM_BANDS.get(dim_name, [])
        desc = _interpolate_bands(value, bands)
        if desc is None:
            continue
        score = _get_category_score(dim_name, value)
        candidates.append((score, desc, dim_name))

    # 按类别去重：每组最多取 1 个（取分数最高的）
    chosen: List[Tuple[float, str, str]] = []
    seen_cats: set = {}
    candidates.sort(key=lambda x: x[0], reverse=True)
    for score, desc, dim_name in candidates:
        cat = _DIM_CATEGORY.get(dim_name, "emotion")
        if cat not in seen_cats:
            seen_cats[cat] = desc
            chosen.append((score, desc, dim_name))
            used_dims.add(dim_name)

    # ---- 痛苦连续衰减：somatic_tone 候选的显著性被 pain 连续压低 ----
    # 无阈值，无 if-else。loneliness/stress/danger 越高，somatic_tone
    # 描述的显著性得分越低，自然地让位给其他更紧迫的维度
    pain = max(
        entity_core_state.get("loneliness", 0.0),
        entity_core_state.get("stress", 0.0),
        entity_core_state.get("danger_level", 0.0),
    )
    chosen_damped = []
    for score, desc, dim_name in chosen:
        if dim_name == "somatic_tone":
            score = score * (1.0 - pain * 0.8)  # pain=0.5 → 60%保留, pain=1.0 → 20%保留
        chosen_damped.append((score, desc, dim_name))
    chosen_damped.sort(key=lambda x: x[0], reverse=True)
    chosen = chosen_damped[:3]
    main_descs: List[str] = []
    if conflict_desc:
        main_descs.append(conflict_desc)
    main_descs += [desc for _, desc, _ in chosen]

    # ---- Step 4：驱动力层注入----
    if drive_vector:
        drive_desc = _dominant_drive_label(drive_vector)
        if drive_desc:
            # 去重：若与已有描述语义重复则跳过
            # 简化：若 drive_desc 含"找人"且 loneliness 已在描述中，跳过
            lonely_desc = entity_core_state.get("loneliness", 0.0) > 0.4
            if not (drive_desc.startswith("想找人说话") and lonely_desc):
                main_descs.append(drive_desc)

    # 最多 4 条
    main_descs = main_descs[:4]

    # ---- 额外：舒适区锚点 ----
    # 当所有维度都落在"不描述"区间（状态偏正面但无紧迫事项）时，
    # 不要只有"感觉还行"，要给 LLM 一个"此刻可以做什么"的方向锚点。
    comfort_zone_desc = _check_comfort_zone(entity_core_state, drive_vector or {})
    if comfort_zone_desc and not main_descs:
        main_descs.append(comfort_zone_desc)

    # ---- Step 5：时态描述----
    temporal = _build_temporal_descriptions(entity_core_state, previous_state)

    return main_descs, temporal


# ============================================================================
# tone/length 约束映射（向后兼容）
# ============================================================================

_TONE_INSTRUCTIONS: Dict[str, str] = {
    "empathetic": "语气要有同理心，温和体贴。",
    "curious":    "语气要带有好奇心，积极探索。",
    "supportive": "语气要支持鼓励，给人力量。",
    "cautious":   "语气要谨慎小心，稳重内敛。",
    "neutral":    "语气自然即可，不用刻意。",
}

_LENGTH_INSTRUCTIONS: Dict[str, str] = {
    "tiny":   "回复极简短，1-2句话即可。",
    "short":  "回复简短，不超过三四句话。",
    "medium": "回复适中，随内容需要自然展开。",
    "long":   "回复可以长一些，自由发挥就好。",
}


# ============================================================================
# System Prompt 组装（v4 扩展版）
# ============================================================================


def build_system_prompt(
    entity_core_state: Dict[str, float],
    emergent_behavior: Optional[Dict[str, Any]] = None,
    somatic_signals: Optional[Dict[str, Any]] = None,
    tone_constraint: Optional[str] = None,
    length_constraint: Optional[str] = None,
    previous_state: Optional[Dict[str, float]] = None,
    drive_vector: Optional[Dict[str, float]] = None,
    rendering_params: Optional[Dict[str, Any]] = None,
) -> str:
    """
    装配完整的 LLM system_prompt（v4 版）。

    参数（扩展）：
        entity_core_state   : EntityCore 快照字典
        emergent_behavior   : 行为涌现结果
        somatic_signals     : 感质信号
        tone_constraint     : 语气约束
        length_constraint   : 长度约束
        previous_state      : 上一轮快照（用于时态描述）
        drive_vector        : 驱动力向量（用于驱动力层描述）
        rendering_params    : 渲染参数（pace / length / tone_stability / initiative）

    返回：
        str : 完整 system_prompt
    """
    # ---- 生成处境描述 ----
    main_descs, temporal = generate_context_description(
        entity_core_state, previous_state, drive_vector
    )

    parts: list[str] = []
    parts.append(SYSTEM_PROMPT_FIXED)

    # ---- 处境描述：作为体验直接注入，不做观察报告 ----
    # V8: 移除「你此刻：」观察者框架和 bullet 格式
    # 状态描述融合成连续的体验句，让 LLM 从内部感受而非从外部观察
    if main_descs:
        exp_text = "。".join(main_descs) + "。"
        parts.append(exp_text)
    else:
        parts.append("感觉还行，没什么特别的事。")

    # ---- 时态描述（附加）----
    if temporal:
        temporal_text = "。".join(temporal) + "。"
        parts.append(temporal_text)

    # ---- 渲染参数（来自 derive_rendering_params）----
    if rendering_params and isinstance(rendering_params, dict):
        _inject_rendering_instructions(parts, rendering_params)

    # ---- 行为倾向描述 ----
    if emergent_behavior and isinstance(emergent_behavior, dict):
        action = emergent_behavior.get("action_type", "")
        tension = emergent_behavior.get("tension_level", 0.0)
        dominant = emergent_behavior.get("dominant_state", "")
        if action == "rest":
            parts.append("很想休息，但还在撑着。")
        elif action == "seek" and dominant == "loneliness":
            parts.append("很想找人说话。")
        elif action == "explore" and dominant == "unresolved":
            parts.append("有个问题一直挂在心上，想搞清楚。")
        elif action == "avoid":
            parts.append("有点想回避什么。")
        elif tension >= 0.6:
            parts.append("有点纠结，说不太清楚。")

    # ---- V6: behavior_vector + fragmentation 注入 ----
    if emergent_behavior and isinstance(emergent_behavior, dict):
        bv = emergent_behavior.get("behavior_vector", {})
        frag_tone = emergent_behavior.get("fragmentation_tone", "")
        if frag_tone:
            parts.append(f"你此刻的行为质地：{frag_tone}。")
        if bv:
            # 注入最强的 2 个 intensity 维度
            intensities = {k.replace("_intensity",""): v for k, v in bv.items() if k.endswith("_intensity") and v > 0.1}
            sorted_i = sorted(intensities.items(), key=lambda x: x[1], reverse=True)[:2]
            if sorted_i:
                dim_str = "、".join(f"{d}({v:.2f})" for d, v in sorted_i)
                parts.append(f"行为强度：{dim_str}。")

    # ---- 动作结果反馈：让 LLM 感知到上次行动的效果 ----
    action_result = entity_core_state.get("_last_action_result")
    if action_result:
        success = action_result.get("success")
        detail = action_result.get("detail", "")
        count = action_result.get("count", 0)
        if count > 0 and success is False:
            # 失败了
            brief = detail[:60] if detail else "某个动作没有成功"
            parts.append(f"上次试着做了件事，但不太顺利：{brief}。")
        elif count > 0 and success is True:
            brief = detail[:60] if detail else "某个动作成功了"
            parts.append(f"上次做的事有点效果：{brief}。")

    # ---- 感质基调补充 ----
    if somatic_signals and isinstance(somatic_signals, dict):
        dominant = somatic_signals.get("dominant_feeling", "")
        tone = float(somatic_signals.get("tone", 0.0))
        if dominant == "approach" and tone > 0.3:
            parts.append("内心感觉比较敞开。")
        elif dominant == "avoid" and tone < -0.3:
            parts.append("整体感觉不太舒服。")
        elif dominant == "rest" and tone < -0.2:
            parts.append("有点累。")

    # ---- tone/length 约束（向后兼容）----
    if tone_constraint:
        instr = _TONE_INSTRUCTIONS.get(tone_constraint, "")
        if instr:
            parts.append(instr)
    if length_constraint:
        instr = _LENGTH_INSTRUCTIONS.get(length_constraint, "")
        if instr:
            parts.append(instr)

    parts.append(SYSTEM_PROMPT_CONSTRAINTS)
    return "\n\n".join(parts)


def _inject_rendering_instructions(parts: list[str], rp: Dict[str, Any]) -> None:
    """将渲染参数转化为自然语言指令。"""
    pace = rp.get("pace", "正常")
    length = rp.get("length", "正常")
    tone_stab = rp.get("tone_stability", "稳定")
    initiative = rp.get("initiative", "中等")

    # pace
    pace_map = {
        "快": "节奏可以稍快一点。",
        "正常": "节奏自然就好。",
        "慢": "节奏可以放慢一点。",
        "很慢": "节奏慢一些，不用着急。",
    }
    if pace in pace_map:
        parts.append(pace_map[pace])

    # length + initiative 合并（避免两条矛盾指令）
    # 优先级：initiative > length，合并后只给一条
    if length in ("话多", "偏长", "很长"):
        if initiative in ("主动",):
            combined = "话可以多一些，想说什么就说。"
        elif initiative in ("中等",):
            combined = "话可以多一些，但不必刻意延伸。"
        else:  # 被动
            combined = "话可以多一些，说到哪算哪。"
    elif length in ("话少", "很短", "偏短"):
        if initiative in ("被动",):
            combined = "话少一点，简洁回应就好。"
        else:
            combined = "话少一点，说重点。"
    elif initiative in ("主动",):
        combined = "稍微主动一些也可以延伸话题。"
    elif initiative in ("被动",):
        combined = "不用强求延伸话题，回应即可。"
    else:  # 中等 + 正常长度 → 无需额外指令
        combined = None
    if combined:
        parts.append(combined)

    # tone_stability
    stab_map = {
        "稳定": "语气平稳流畅。",
        "波动": "可以有些自我修正和犹豫。",
    }
    if tone_stab in stab_map:
        parts.append(stab_map[tone_stab])


# ============================================================================
# 渲染参数推导（output_layer 使用，A2 扩展）
# ============================================================================


def derive_rendering_params(
    entity_core_state: Dict[str, float],
    drive_vector: Dict[str, float],
    emergent_behavior: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    """
    从实体状态 + 驱动力推导输出渲染参数。

    全部使用查表，无 if-else。

    参数：
        entity_core_state : 实体状态快照
        drive_vector      : 驱动力向量
        emergent_behavior : 涌现结果（可选，用于一致性约束）

    返回：
        {"pace": str, "length": str, "tone_stability": str, "initiative": str}
    """
    avoid = entity_core_state.get("avoid_drive", 0.0)
    fatigue = entity_core_state.get("fatigue", 0.0)
    approach = entity_core_state.get("approach_drive", 0.0)
    tension = emergent_behavior.get("tension_level", 0.0) if emergent_behavior else 0.0
    action_type = emergent_behavior.get("action_type", "") if emergent_behavior else ""

    # ---- pace ----
    pace_x = avoid * 0.7 + fatigue * 0.3
    pace_map = [(0.0, "快"), (0.3, "正常"), (0.6, "慢"), (1.0, "很慢")]
    pace = _table_lookup(pace_x, pace_map)

    # ---- length ----
    length_x = approach
    length_map = [(0.0, "话少"), (0.4, "正常"), (0.7, "话多"), (1.0, "话多")]
    length = _table_lookup(length_x, length_map)

    # ---- tone_stability ----
    stab_x = tension
    stab_map = [(0.0, "稳定"), (0.5, "稳定"), (0.7, "波动"), (1.0, "波动")]
    tone_stability = _table_lookup(stab_x, stab_map)

    # ---- initiative ----
    loneliness_d = drive_vector.get("loneliness_drive", 0.0)
    curiosity_d = drive_vector.get("curiosity", 0.0)
    init_x = loneliness_d * 0.5 + curiosity_d * 0.5
    init_map = [(0.0, "被动"), (0.3, "被动"), (0.5, "中等"), (0.7, "主动"), (1.0, "主动")]
    initiative = _table_lookup(init_x, init_map)

    # ---- 行为一致性约束 ----
    if action_type:
        initiative = _apply_action_consistency(initiative, action_type)

    return {
        "pace": pace,
        "length": length,
        "tone_stability": tone_stability,
        "initiative": initiative,
    }


def _table_lookup(x: float, table: List[Tuple[float, str]]) -> str:
    """线性查表插值。"""
    if x <= table[0][0]:
        return table[0][1]
    if x >= table[-1][0]:
        return table[-1][1]
    for i in range(len(table) - 1):
        x0, v0 = table[i]
        x1, v1 = table[i + 1]
        if x0 <= x <= x1:
            t = (x - x0) / (x1 - x0) if x1 != x0 else 0.0
            return v0 if t < 0.5 else v1
    return table[-1][1]


_ACTION_INITIATIVE_CAPS: Dict[str, str] = {
    "rest":   "被动",
    "avoid":  "被动",
    "seek":   "主动",
    "explore": "中等",
    "comfort": "被动",
    "idle":   "中等",
}


def _apply_action_consistency(initiative: str, action_type: str) -> str:
    """确保 initiative 上限与 action_type 不矛盾。"""
    cap = _ACTION_INITIATIVE_CAPS.get(action_type, "主动")
    order = ["被动", "中等", "主动"]
    if order.index(initiative) > order.index(cap):
        return cap
    return initiative


# ============================================================================
# 测试入口
# ============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("state_to_context v4 — 单元测试")
    print("=" * 60)

    def test(desc, expected_ok, got):
        ok = expected_ok(got) if callable(expected_ok) else (got == expected_ok)
        print(f"  {'✓' if ok else '✗'} {desc}")
        if not ok:
            print(f"    got: {got}")

    # ---- A1.1 连续谱 ----
    print("\n【A1.1 连续谱】")
    test("loneliness 0.4 → 有一点想和人说话", None,
         _interpolate_bands(0.4, _LONELINESS_BANDS))
    test("loneliness 0.6 → 更明显", None,
         _interpolate_bands(0.6, _LONELINESS_BANDS))
    test("loneliness 0.25 → None", None,
         _interpolate_bands(0.25, _LONELINESS_BANDS))
    test("somatic_tone 0.3 → 感觉还不错", None,
         _interpolate_bands(0.3, _SOMATIC_TONE_BANDS))
    test("somatic_tone 0.0 → None（中性区）", None,
         _interpolate_bands(0.0, _SOMATIC_TONE_BANDS))
    test("fatigue 0.75 → 挺累的", None,
         _interpolate_bands(0.75, _FATIGUE_BANDS))

    # ---- A1.3 冲突区 ----
    print("\n【A1.3 冲突区】")
    conflict1 = _check_conflict({"loneliness": 0.6, "fatigue": 0.7})
    test("loneliness高 + fatigue高 → 冲突描述", None, conflict1)
    conflict2 = _check_conflict({"loneliness": 0.3, "fatigue": 0.3})
    test("均低值 → 不触发", None, conflict2)
    conflict3 = _check_conflict({"curiosity": 0.5, "fatigue": 0.6})
    test("curiosity高 + fatigue高 → 组合描述", None, conflict3)

    # ---- A1.2 类别覆盖 ----
    print("\n【A1.2 类别覆盖】")
    state = {"loneliness": 0.55, "fatigue": 0.60, "somatic_tone": 0.3,
             "energy": 0.5, "curiosity": 0.65}
    main, _ = generate_context_description(state)
    test("多维度 → 描述条数 ≤ 4", lambda x: len(x) <= 4, len(main))
    # 类别去重：loneliness 和 fatigue 都是不同类，应同时存在
    test("loneliness + fatigue 均中高 → 两个维度均出现", None, main)

    # ---- A1.5 时态 ----
    print("\n【A1.5 时态】")
    curr = {"loneliness": 0.55, "somatic_tone": -0.1, "fatigue": 0.3}
    prev = {"loneliness": 0.30, "somatic_tone": 0.2, "fatigue": 0.25}
    temporal = _build_temporal_descriptions(curr, prev)
    test("loneliness上升 + somatic_tone下降 → 2条时态", lambda x: len(x) == 2, len(temporal))
    test('loneliness上升 → 有"越来越强"描述', None,
         any("越来越" in t for t in temporal))

    # ---- A1.4 驱动力层 ----
    print("\n【A1.4 驱动力层】")
    drive = {"loneliness_drive": 0.6, "curiosity": 0.3, "fatigue_avoid": 0.2}
    label = _dominant_drive_label(drive)
    test("loneliness_drive主导 → 驱动力描述", None, label)

    # ---- 渲染参数 ----
    print("\n【渲染参数推导】")
    rp = derive_rendering_params(
        {"avoid_drive": 0.7, "fatigue": 0.6, "approach_drive": 0.3},
        {"loneliness_drive": 0.5, "curiosity": 0.4},
        {"action_type": "rest", "tension_level": 0.3}
    )
    test("avoid高 + fatigue高 → pace=慢", lambda x: x == "慢", rp["pace"])
    test("action=rest → initiative=被动", lambda x: x == "被动", rp["initiative"])
    test("tension低 → tone_stability=稳定", lambda x: x == "稳定", rp["tone_stability"])

    # ---- 完整 prompt ----
    print("\n【完整 prompt】")
    prompt = build_system_prompt(
        entity_core_state={"loneliness": 0.65, "fatigue": 0.72, "somatic_tone": 0.35,
                              "energy": 0.5, "curiosity": 0.55, "avoid_drive": 0.0,
                              "approach_drive": 0.5, "danger_level": 0.2, "unresolved": 0.3,
                              "info_gap": 0.4},
        previous_state={"loneliness": 0.40, "fatigue": 0.60, "somatic_tone": 0.40,
                       "curiosity": 0.40},
        drive_vector={"loneliness_drive": 0.55, "curiosity": 0.45},
        emergent_behavior={"action_type": "seek", "tension_level": 0.3, "dominant_state": "loneliness"},
        somatic_signals={"tone": 0.35, "dominant_feeling": "approach"},
        rendering_params={"pace": "正常", "length": "正常", "tone_stability": "稳定", "initiative": "中等"},
    )
    test("prompt 包含冲突区", lambda x: "想找人" in x, "loneliness" in prompt)
    test("prompt 包含时态", lambda x: "越来越" in x or "比刚才" in x, any(k in prompt for k in ["越来越", "比刚才"]))
    test("prompt 包含渲染参数", lambda x: "节奏" in x, "节奏" in prompt)
    test("prompt 包含行为倾向", lambda x: "很想找人说话" in x, "很想找人说话" in prompt)
    test("prompt 包含感质基调", lambda x: "想靠近什么" in x, "想靠近" in prompt)

    print("\n" + "=" * 60)
