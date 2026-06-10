"""Stereotype Tree API - top-level functions.

Extracted from stereotype_tree.py to keep it below 400 lines.
The three functions here are re-exported by stereotype_tree.py.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from .stereotype_tree_schema import DEFAULT_FEATURE_WEIGHTS


def get_speaker_context(
    entity,
    speaker_id: str,
    input_features: Optional[Dict[str, float]] = None,
) -> Optional[StereotypeContext]:
    """
    从 entity._stereotype_trees 获取说话者的刻板印象上下文。

    参数：
        entity        : EntityState 实例
        speaker_id    : 说话者 ID
        input_features: 当前输入的特征（可选）

    返回：
        StereotypeContext 或 None
    """
    trees = getattr(entity, "_stereotype_trees", None)
    if trees is None:
        return None

    # 获取 XIA 自己的树
    tree = trees.get("default")
    if tree is None:
        return None

    return tree.match(speaker_id, input_features)


def ensure_tree(entity, name: str = "default") -> StereotypeTree:
    """
    确保 entity 有刻板印象树，没有则创建。

    参数：
        entity: EntityState 实例
        name  : 树名称

    返回：
        StereotypeTree
    """
    trees = getattr(entity, "_stereotype_trees", None)
    if trees is None:
        entity._stereotype_trees = {}
        trees = entity._stereotype_trees

    if name not in trees:
        from .stereotype_tree import StereotypeTree
        trees[name] = StereotypeTree(owner_id=name)

    return trees[name]

def apply_stereotype_bias(
    semantic_packet: dict,
    context: "StereotypeContext",
) -> dict:
    """
    用刻板印象上下文偏置语义包。

    偏置是概率性的、叠加的——它调整可能性分布，而不是硬编码结果。
    偏置强度 = context.confidence（树对说话者的置信度）。

    偏置维度：
        - emotion: 高情感表达者放大 emotion，绝对值向 ±1 移动
        - intensity: 长句型说话者轻微增加 intensity
        - intent: 哲学型说话者轻微提升 "求助" 和 "分享" 意图得分
        - anchors: 加入说话者风格的标记

    参数：
        semantic_packet: 原始语义包
        context        : 刻板印象上下文

    返回：
        偏置后的语义包（新的 dict，不修改原对象）
    """
    if context is None or context.confidence < 0.3:
        # 置信度太低，不应用偏置
        return semantic_packet

    weights = context.feature_weights
    confidence = context.confidence

    # 深拷贝
    biased = dict(semantic_packet)

    # ---- emotion 偏置 ----
    emotional_variance = weights.get("emotional_variance", 0.5)
    # 高情感表达者：emotion 向极值移动
    if emotional_variance > 0.6:
        bias_strength = (emotional_variance - 0.6) * 2.5 * confidence
        old_emotion = biased.get("emotion", 0.0)
        # 向 ±1 方向拉伸
        biased["emotion"] = old_emotion + bias_strength * old_emotion
        biased["emotion"] = max(-1.0, min(1.0, biased["emotion"]))
    elif emotional_variance < 0.3:
        bias_strength = (0.3 - emotional_variance) * 1.5 * confidence
        old_emotion = biased.get("emotion", 0.0)
        # 向中性收缩
        biased["emotion"] = old_emotion * (1.0 - bias_strength * 0.5)

    # ---- intensity 偏置 ----
    avg_sentence_len = weights.get("avg_sentence_len", 0.5)
    if avg_sentence_len > 0.6:
        # 长句型说话者轻微增加 intensity
        bias_delta = (avg_sentence_len - 0.6) * 0.15 * confidence
        biased["intensity"] = min(1.0, biased.get("intensity", 0.5) + bias_delta)
    elif avg_sentence_len < 0.3:
        # 短句型说话者轻微降低 intensity
        bias_delta = (0.3 - avg_sentence_len) * 0.1 * confidence
        biased["intensity"] = max(0.1, biased.get("intensity", 0.5) - bias_delta)

    # ---- intent 偏置 ----
    philosophical_ratio = weights.get("philosophical_ratio", 0.5)
    question_ratio = weights.get("question_ratio", 0.5)
    analytical_ratio = weights.get("analytical_marker_ratio", 0.5)

    intent_bias = confidence * 0.3  # 偏置幅度上限

    # 哲学型说话者：轻微偏向 "求助" 或 "分享"
    if philosophical_ratio > 0.5:
        current_intent = biased.get("intent", "闲聊")
        if current_intent == "闲聊" and question_ratio > 0.4:
            biased["intent"] = "求助"
            if "求助" not in str(biased.get("anchors", [])):
                biased.setdefault("anchors", []).insert(0, "stereotype:哲学型")

    # 逻辑型说话者：轻微提升 "指令" 意图权重
    if analytical_ratio > 0.4:
        biased.setdefault("anchors", []).append("stereotype:逻辑型")

    # ---- anchors 注入 ----
    anchors = biased.setdefault("anchors", [])
    # 加入说话者置信度标记
    if confidence > 0.7:
        anchors.append(f"stereotype:confidence_high")
    elif confidence > 0.5:
        anchors.append(f"stereotype:confidence_medium")
    else:
        anchors.append(f"stereotype:confidence_low")

    # 加入说话者推断的标签（如果有）
    for tag in context.active_tags[:2]:
        if tag not in ["unknown", "root"]:
            safe_tag = f"speaker:{tag}"
            if safe_tag not in anchors:
                anchors.append(safe_tag)

    return biased
