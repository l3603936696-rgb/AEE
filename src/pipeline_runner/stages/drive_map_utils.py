"""drive_map 共用常量与工具函数

职责（一句话）：为三层 input→drive 映射提供共享常量、维度定义和数学工具，
不包含任何业务逻辑，只依赖标准库。
"""
import math
from typing import Dict, List

# ============================================================================
# 维度定义
# ============================================================================
# SPM 5维 drive 空间维度名，顺序固定
_DIMS = ("curiosity", "info_hunger", "obsolescence_anxiety", "loneliness_drive", "fatigue_avoid")

# drive 维度的中文等级标签（供 symbol_to_text_description 和调试用）
_DIM_HIGH_LABELS: Dict[str, str] = {
    "curiosity":            "好奇",
    "info_hunger":          "渴知",
    "obsolescence_anxiety": "焦滞",
    "loneliness_drive":     "孤寂",
    "fatigue_avoid":        "倦避",
}

_DIM_LEVEL_LABELS: Dict[str, List[str]] = {
    "curiosity":            ["冷淡", "略有好奇", "好奇", "很想知道", "极度渴求"],
    "info_hunger":          ["满足", "略有缺失感", "渴望信息", "急需答案", "信息焦虑"],
    "obsolescence_anxiety": ["安心", "轻微不安", "明显焦虑", "强烈危机感", "极度恐慌"],
    "loneliness_drive":     ["充实", "有些孤独", "明显孤独", "非常渴望陪伴", "极度孤寂"],
    "fatigue_avoid":        ["精神饱满", "略有倦意", "明显疲惫", "非常疲倦", "精疲力竭"],
}

# 各 drive 维度的默认基线（当没有关键词命中时的背景激活）
_DRIVE_BASELINE: Dict[str, float] = {
    "curiosity":            0.3,
    "info_hunger":          0.2,
    "obsolescence_anxiety": 0.2,
    "loneliness_drive":     0.3,
    "fatigue_avoid":        0.2,
}

# somatic dictionary 维度 → SPM 5维 drive 空间的映射权重
_SOMATIC_TO_DRIVE: Dict[str, Dict[str, float]] = {
    "loneliness":    {"loneliness_drive": 1.0},
    "curiosity":     {"curiosity": 1.0, "info_hunger": 0.5},
    "info_gap":      {"info_hunger": 1.0},
    "fatigue":       {"fatigue_avoid": 1.0},
    "stress":        {"obsolescence_anxiety": 1.0},
    "anxiety":       {"obsolescence_anxiety": 1.0},
    "pain":          {"fatigue_avoid": 0.5, "obsolescence_anxiety": 0.3},
}

# 层间权重（somatic keyword 直击权重最高，因为最直接）
_LAYER_WEIGHTS = {
    "somatic_keyword":  0.50,
    "bge_semantic":     0.30,
    "drive_space":      0.20,
}


# ============================================================================
# 数学工具
# ============================================================================

def _level_index(value: float) -> int:
    """将 [0, 1] 的 drive 值映射到等级 index [0, 4]。"""
    return min(4, max(0, int(value * 5.0)))


def _drive_cosine(a: Dict[str, float], b: Dict[str, float]) -> float:
    """5维 drive 空间余弦相似度。"""
    av = tuple(float(a.get(d, 0.0)) for d in _DIMS)
    bv = tuple(float(b.get(d, 0.0)) for d in _DIMS)
    dot = sum(x * y for x, y in zip(av, bv))
    mag_a = math.sqrt(sum(x * x for x in av))
    mag_b = math.sqrt(sum(x * x for x in bv))
    return dot / (mag_a * mag_b) if (mag_a > 1e-9 and mag_b > 1e-9) else 0.0


def _cosine_sim_vec(a: List[float], b: List[float]) -> float:
    """两向量余弦相似度。"""
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    return dot / (mag_a * mag_b) if (mag_a > 1e-9 and mag_b > 1e-9) else 0.0


def _tfidf_sim(text1: str, text2: str) -> float:
    """简单词频余弦相似度（BGE 不可用时的降级方案）。"""
    words1 = set(text1.lower().split())
    words2 = set(text2.lower().split())
    if not words1 or not words2:
        return 0.0
    union = words1 | words2
    return len(words1 & words2) / math.sqrt(len(union)) if union else 0.0


def _weighted_combine(
    sources: List[Dict[str, float]],
    weights: List[float],
) -> Dict[str, float]:
    """
    多源 drive 向量加权叠加，返回归一化到 [0, 1] 的向量。

    sources : [{"dim": value, ...}, ...]
    weights : [w1, w2, ...]
    """
    total_weight = sum(w for w in weights if w > 0)
    if total_weight < 1e-9:
        return {}

    result: Dict[str, float] = {}
    for source, w in zip(sources, weights):
        if w <= 0:
            continue
        for dim in _DIMS:
            result[dim] = result.get(dim, 0.0) + float(source.get(dim, 0.0)) * w

    max_val = max((abs(v) for v in result.values()), default=1.0)
    if max_val > 1e-9:
        result = {d: max(0.0, min(1.0, v / max_val)) for d, v in result.items()}
    return result
