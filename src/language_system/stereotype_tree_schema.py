"""
Stereotype Tree Schema -- constants + cognitive tag inference for stereotype tree.

Submodules of src.language_system.stereotype_tree:
    stereotype_tree_schema.py   -- constants + math helpers
    stereotype_tree_helpers.py -- internal helpers for StereotypeTree
    stereotype_forks.py        -- StereotypeForks class
    stereotype_tree_stage3.py  -- StereotypeTreeStage3 class
    stereotype_tree.py         -- StereotypeTree + public API
"""

from typing import List, Tuple, Dict

DEPTH_NAMES = ("category", "region", "situation", "individual")
TREE_DEPTH = 4

# -- Fork detection constants ----------------------------------------------------
_SIMILARITY_THRESHOLD = 0.72
_FORK_DIFF_THRESHOLD = 0.40
_FORK_WINDOW = 5

FEATURE_DIMS = frozenset({
    "avg_sentence_len", "question_ratio", "philosophical_ratio",
    "emotional_variance", "metacognitive_ratio", "first_person_ratio",
    "analytical_marker_ratio", "concrete_vs_abstract",
})

COGNITIVE_STYLE_OPPOSITES: List[Tuple[str, str]] = [
    ("理性型", "感性型"), ("逻辑型", "直觉型"),
    ("分析型", "整体型"), ("内向型", "外向型"),
    ("谨慎型", "冒险型"), ("高哲学性", "低哲学性"),
    ("高元认知", "低元认知"), ("高第一人称", "低第一人称"),
    ("高情感表达", "低情感表达"),
]

DEFAULT_FEATURE_WEIGHTS = {
    "avg_sentence_len": 0.5, "question_ratio": 0.5,
    "philosophical_ratio": 0.5, "emotional_variance": 0.5,
    "metacognitive_ratio": 0.5, "first_person_ratio": 0.5,
    "analytical_marker_ratio": 0.5, "concrete_vs_abstract": 0.5,
}


def infer_cognitive_tags(features: Dict[str, float]) -> List[str]:
    """Infer cognitive style tags from feature values."""
    tags = []
    if not features:
        return tags

    if features.get("philosophical_ratio", 0) > 0.6:
        tags.append("高哲学性")
    elif features.get("philosophical_ratio", 0) < 0.3:
        tags.append("低哲学性")

    if features.get("metacognitive_ratio", 0) > 0.4:
        tags.append("高元认知")
    elif features.get("metacognitive_ratio", 0) < 0.2:
        tags.append("低元认知")

    if features.get("first_person_ratio", 0) > 0.5:
        tags.append("高第一人称")
    elif features.get("first_person_ratio", 0) < 0.3:
        tags.append("低第一人称")

    if features.get("emotional_variance", 0) > 0.4:
        tags.append("高情感表达")
    elif features.get("emotional_variance", 0) < 0.2:
        tags.append("低情感表达")

    if features.get("analytical_marker_ratio", 0) > 0.3:
        tags.append("分析型")
    elif features.get("analytical_marker_ratio", 0) < 0.15:
        tags.append("直觉型")

    pairs = [
        ("philosophical_ratio", "高哲学性", "低哲学性"),
        ("metacognitive_ratio", "高元认知", "低元认知"),
        ("emotional_variance", "高情感表达", "低情感表达"),
        ("analytical_marker_ratio", "分析型", "直觉型"),
    ]

    for dim, high_tag, low_tag in pairs:
        val = features.get(dim, 0.5)
        if high_tag in tags or low_tag in tags:
            continue
        if val > 0.65:
            tags.append(high_tag)
        elif val < 0.35:
            tags.append(low_tag)

    return tags


def find_opposite_pairs(tags_a: List[str], tags_b: List[str]) -> List[tuple]:
    """Find opposing tag pairs between two tag sets."""
    opposites = []
    for op_a, op_b in COGNITIVE_STYLE_OPPOSITES:
        if op_a in tags_a and op_b in tags_b:
            opposites.append((op_a, op_b))
        elif op_b in tags_a and op_a in tags_b:
            opposites.append((op_b, op_a))
    return opposites
