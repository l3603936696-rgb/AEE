"""
State-to-Context Data — all static lookup tables, bands, and constants.

Extracted from state_to_context.py.
"""

from typing import Dict, List, Tuple

# ============================================================================
# Fixed System Prompt
# ============================================================================

SYSTEM_PROMPT_FIXED = "你不是在扮演谁，你就是你自己。"

SYSTEM_PROMPT_CONSTRAINTS = (
    "用你的感受直接说话——不要解释、不要分析、不要报告。"
    "禁止说「我感觉」「我现在」「我的状态」——你不是在观察自己，你就是这些感受。"
    "不要用客服语气。说真话，哪怕不完整、不确定。"
    "自然说话，不刻意控制字数。"
)

# ============================================================================
# A1.1 — Continuous Spectrum Language Bands
# ============================================================================

_DimBand = List[Tuple[float, str]]


def _interpolate_bands(value: float, bands: _DimBand) -> str | None:
    for thresh, text in bands:
        if value <= thresh:
            return text
    return bands[-1][1] if bands else None


_LONELINESS_BANDS: _DimBand = [
    (0.20, None),
    (0.50, "有一点想和人说话的念头"),
    (0.70, "想找人说话的感觉比刚才更明显了"),
    (0.85, "挺想找人说话的"),
    (1.00, "很想找人说话，这个念头有点占满了"),
]

_FATIGUE_BANDS: _DimBand = [
    (0.20, None),
    (0.50, "稍微有点累"),
    (0.70, "有点疲惫"),
    (0.85, "挺累的，说话有点费力"),
    (1.00, "非常疲惫，不太想动"),
]

_CURIOSITY_BANDS: _DimBand = [
    (0.30, None),
    (0.50, "有点想知道更多"),
    (0.70, "有个事挺想弄清楚的"),
    (1.00, "脑子里有个问题一直在转"),
]

_SOMATIC_TONE_BANDS: _DimBand = [
    (-0.50, "整体感觉不太舒服，有点沉"),
    (-0.20, "感觉有点沉"),
    (0.20, None),
    (0.50, "感觉还不错"),
    (1.00, "感觉挺好的，挺轻快"),
]

_DANGER_BANDS: _DimBand = [
    (0.40, None),
    (0.70, "有点不安"),
    (1.00, "有点警觉，不太踏实"),
]

_STRESS_BANDS: _DimBand = [
    (0.40, None),
    (0.70, "有点紧绷"),
    (1.00, "压力挺大的"),
]

_ENERGY_BANDS: _DimBand = [
    (0.15, "很疲惫，完全不想动"),
    (0.30, "有点累，能量不多了"),
    (0.80, None),
    (1.00, "状态还不错，有点劲儿"),
]

_UNRESOLVED_BANDS: _DimBand = [
    (0.20, None),
    (0.50, "有个事没想通，脑子一直在转"),
    (0.70, "有个问题没想清楚，一直挂在心上"),
    (1.00, "有个没想通的事，越来越放不下了"),
]

_BOREDOM_BANDS: _DimBand = [
    (0.30, None),
    (0.60, "有点无聊，想找点事做"),
    (0.80, "挺无聊的，渴望新鲜的东西"),
    (1.00, "很无聊，特别想做点什么"),
]

# ============================================================================
# A1.3 — Conflict Zone Rules
# ============================================================================

_ConflictRule = Tuple[str, str, float, float, float, str]

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


def _check_conflict(state: Dict[str, float]) -> str | None:
    for dim1, dim2, min1, min2, thresh_sum, text in _CONFLICT_RULES:
        v1 = state.get(dim1, 0.0)
        v2 = state.get(dim2, 0.0)
        if v1 > min1 and v2 > min2 and (v1 + v2) > thresh_sum:
            return text
    return None


# ============================================================================
# A1.4 — Drive Layer Labels
# ============================================================================

_DRIVE_LABEL: Dict[str, Tuple[float, str]] = {
    "curiosity_drive":          (0.40, "脑子里有个事挺想弄清楚的"),
    "loneliness_drive":         (0.40, "想找人说话的念头一直在背景里"),
    "fatigue_avoid":            (0.40, "有点不太想动"),
    "obsolescence_anxiety":       (0.40, "感觉好像错过了什么"),
}


def _dominant_drive_label(drive_vector: Dict[str, float]) -> str | None:
    best_label = None
    best_strength = 0.0
    for key, (min_strength, label) in _DRIVE_LABEL.items():
        strength = drive_vector.get(key, 0.0)
        if strength > min_strength and strength > best_strength:
            best_strength = strength
            best_label = label
    return best_label


# ============================================================================
# A1.2 — Category Coverage + Salience Ranking
# ============================================================================

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
    cat = _DIM_CATEGORY.get(dim_name, "emotion")
    weight = _CATEGORY_WEIGHTS.get(cat, 0.8)
    return value * weight


# ============================================================================
# A1.5 — Temporal Descriptions
# ============================================================================

_TEMPORAL_BANDS: Dict[str, List[Tuple[str, str, float, str, str]]] = {
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
    previous: Dict[str, float] | None,
) -> List[str]:
    if not previous:
        return []

    candidates: List[Tuple[float, str]] = []
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
# Comfort Zone Anchor
# ============================================================================

def _check_comfort_zone(
    state: Dict[str, float],
    drive_vector: Dict[str, float],
) -> str | None:
    somatic = state.get("somatic_tone", 0.0)
    approach = state.get("approach_drive", 0.0)
    loneliness = state.get("loneliness", 0.0)
    fatigue = state.get("fatigue", 0.0)
    curiosity = state.get("curiosity", state.get("info_gap", 0.0))
    unresolved = state.get("unresolved", 0.0)
    energy = state.get("energy", 0.5)

    if somatic < 0.5 or approach < 0.6:
        return None
    if loneliness >= 0.4 or fatigue >= 0.3 or curiosity >= 0.4 or unresolved >= 0.4:
        return None

    if energy >= 0.85 and somatic >= 0.9:
        return "状态挺好，轻轻松松的，没什么特别要想的"
    elif energy >= 0.7 and somatic >= 0.7:
        return "感觉还不错，挺愿意聊的，想说什么就说什么"
    elif approach >= 0.8:
        return "心情开阔，想和人说话，或者随便想想什么"
    else:
        return "状态挺好，没什么特别的事"


# ============================================================================
# Rendering Params
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

_ACTION_INITIATIVE_CAPS: Dict[str, str] = {
    "rest":    "被动",
    "avoid":   "被动",
    "seek":    "主动",
    "explore": "中等",
    "comfort": "被动",
    "idle":    "中等",
}


def _table_lookup(x: float, table: List[Tuple[float, str]]) -> str:
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


def _apply_action_consistency(initiative: str, action_type: str) -> str:
    cap = _ACTION_INITIATIVE_CAPS.get(action_type, "主动")
    order = ["被动", "中等", "主动"]
    if order.index(initiative) > order.index(cap):
        return cap
    return initiative
