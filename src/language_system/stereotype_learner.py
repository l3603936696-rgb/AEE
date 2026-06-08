"""
Stereotype Learner — 刻板印象学习器：自动推断说话者特征（v1.0）

职责：
    - 从对话历史中提取说话者的行为特征
    - 根据特征推断说话者的高层标签（粗粒度刻板印象）
    - 触发刻板印象树的生长或分叉

特征提取维度：
    - 用词风格（问句比例、哲学词比例、抽象词比例）
    - 思考模式（元认知词、分析性标记）
    - 情感倾向（情感波动幅度、情感表达频率）
    - 语言习惯（句长、第一人称使用频率）
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from .stereotype_tree import (
    FEATURE_DIMS,
    DEFAULT_FEATURE_WEIGHTS,
    StereotypeTree,
    ensure_tree,
    StereotypeContext,
)
from .stereotype_markers import (
    FEATURE_WINDOW,
    PHILOSOPHICAL_MARKERS,
    METACOGNITIVE_MARKERS,
    ANALYTICAL_MARKERS,
    FIRST_PERSON_MARKERS,
    EMOTIONAL_MARKERS,
)

logger = logging.getLogger(__name__)


# ============================================================================
# 特征提取器
# ============================================================================

class FeatureExtractor:
    """
    从对话历史中提取说话者的行为特征。
    """

    def __init__(self, window_size: int = FEATURE_WINDOW):
        self._window_size = window_size

    def extract(self, conversation_history: List[Dict[str, Any]]) -> Dict[str, float]:
        """
        从对话历史中提取特征向量。

        参数：
            conversation_history: 对话历史列表
                [{"speaker": str, "text": str, "emotion": float, "timestamp": float}, ...]

        返回：
            特征向量 {dim: value}，值范围 [0, 1]
        """
        # 取最近 N 条
        recent = conversation_history[-self._window_size:] if conversation_history else []

        if not recent:
            return dict(DEFAULT_FEATURE_WEIGHTS)

        # 基础统计
        text_lengths = [len(msg.get("text", "")) for msg in recent]
        emotions = [msg.get("emotion", 0.0) for msg in recent]
        texts = [msg.get("text", "") for msg in recent]

        n = len(recent)

        # 统计各项
        total_chars = sum(text_lengths)
        question_count = sum(1 for t in texts if "？" in t or "?" in t)
        philosophical_count = sum(1 for t in texts if any(m in t for m in PHILOSOPHICAL_MARKERS))
        metacognitive_count = sum(1 for t in texts if any(m in t for m in METACOGNITIVE_MARKERS))
        analytical_count = sum(1 for t in texts if any(m in t for m in ANALYTICAL_MARKERS))
        first_person_count = sum(t.count("我") + t.count("我们") for t in texts)
        emotional_markers_count = sum(1 for t in texts if any(m in t for m in EMOTIONAL_MARKERS))

        # 情感统计
        emotion_variance = self._variance(emotions) if emotions else 0.0
        emotion_mean = sum(emotions) / n if emotions else 0.0

        # 具体 vs 抽象（简化：用句长代理）
        avg_sentence_len = total_chars / n if n > 0 else 0.0

        features = {
            "avg_sentence_len": min(1.0, avg_sentence_len / 50.0),  # 50字为基准
            "question_ratio": question_count / n,
            "philosophical_ratio": philosophical_count / n,
            "emotional_variance": min(1.0, emotion_variance),
            "metacognitive_ratio": metacognitive_count / n,
            "first_person_ratio": min(1.0, first_person_count / (total_chars + 1)),
            "analytical_marker_ratio": analytical_count / n,
            "concrete_vs_abstract": 0.5 if avg_sentence_len < 30 else (0.8 if avg_sentence_len > 60 else 0.5),
        }

        return features

    @staticmethod
    def _variance(values: List[float]) -> float:
        """计算方差。"""
        if not values:
            return 0.0
        mean = sum(values) / len(values)
        return sum((v - mean) ** 2 for v in values) / len(values)

    def extract_from_single_message(self, text: str, emotion: float = 0.0) -> Dict[str, float]:
        """
        从单条消息中提取特征（简化版，用于实时更新）。

        参数：
            text   : 消息文本
            emotion: 情感值

        返回：
            特征向量
        """
        text_len = len(text)
        has_question = "？" in text or "?" in text
        has_philosophical = any(m in text for m in PHILOSOPHICAL_MARKERS)
        has_metacognitive = any(m in text for m in METACOGNITIVE_MARKERS)
        has_analytical = any(m in text for m in ANALYTICAL_MARKERS)
        first_person_count = text.count("我") + text.count("我们")
        has_emotional = any(m in text for m in EMOTIONAL_MARKERS)

        # 简化：返回相对值（需要累积才能得到绝对特征）
        return {
            "avg_sentence_len": min(1.0, text_len / 50.0),
            "question_ratio": 1.0 if has_question else 0.0,
            "philosophical_ratio": 1.0 if has_philosophical else 0.0,
            "emotional_variance": abs(emotion),
            "metacognitive_ratio": 1.0 if has_metacognitive else 0.0,
            "first_person_ratio": min(1.0, first_person_count / 10.0),
            "analytical_marker_ratio": 1.0 if has_analytical else 0.0,
            "concrete_vs_abstract": 0.5 if text_len < 30 else (0.8 if text_len > 60 else 0.5),
        }


# ============================================================================
# 标签推断器
# ============================================================================

class TagInferrer:
    """
    根据特征向量推断说话者的高层标签。
    """

    def infer(self, features: Dict[str, float]) -> List[str]:
        """
        从特征向量推断标签。

        参数：
            features: 特征向量

        返回：
            推断出的标签列表（按置信度排序）
        """
        tags = []

        # 思维模式推断
        if features.get("philosophical_ratio", 0) > 0.5:
            tags.append(("哲学型", features["philosophical_ratio"]))
        if features.get("question_ratio", 0) > 0.4:
            tags.append(("好奇型", features["question_ratio"]))
        if features.get("metacognitive_ratio", 0) > 0.3:
            tags.append(("反思型", features["metacognitive_ratio"]))
        if features.get("analytical_marker_ratio", 0) > 0.3:
            tags.append(("逻辑型", features["analytical_marker_ratio"]))

        # 语言风格推断
        if features.get("concrete_vs_abstract", 0) > 0.6:
            tags.append(("抽象思维", features["concrete_vs_abstract"]))
        elif features.get("concrete_vs_abstract", 0) < 0.4:
            tags.append(("具体思维", 1.0 - features["concrete_vs_abstract"]))

        # 句长推断
        if features.get("avg_sentence_len", 0) > 0.7:
            tags.append(("长句型", features["avg_sentence_len"]))
        elif features.get("avg_sentence_len", 0) < 0.3:
            tags.append(("短句型", 1.0 - features["avg_sentence_len"]))

        # 第一人称推断
        if features.get("first_person_ratio", 0) > 0.4:
            tags.append(("自我中心", features["first_person_ratio"]))

        # 情感推断
        if features.get("emotional_variance", 0) > 0.5:
            tags.append(("高情感表达", features["emotional_variance"]))
        elif features.get("emotional_variance", 0) < 0.2:
            tags.append(("低情感表达", 1.0 - features["emotional_variance"]))

        # 按置信度排序
        tags.sort(key=lambda x: x[1], reverse=True)

        return [tag for tag, _ in tags]


# ============================================================================
# 刻板印象学习器
# ============================================================================

class StereotypeLearner:
    """
    刻板印象学习器。

    协调 FeatureExtractor 和 TagInferrer，从对话历史中学习说话者的刻板印象，
    并更新刻板印象树。
    """

    def __init__(self):
        self._extractor = FeatureExtractor()
        self._inferrer = TagInferrer()

    def learn_from_conversation(
        self,
        entity,
        speaker_id: str,
        conversation_history: List[Dict[str, Any]],
        force_update: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """
        从对话历史中学习说话者的刻板印象，并触发树生长。

        当推断出的新标签与现有标签不同时，触发树往下生长。

        参数：
            entity            : EntityState 实例
            speaker_id        : 说话者 ID
            conversation_history: 对话历史
            force_update      : 是否强制更新（即使样本不足）

        返回：
            学习结果 {
                "features": Dict[str, float],
                "inferred_tags": List[str],
                "tree_updated": bool,
                "confidence_delta": float,
                "tree_grew": bool,
            }
        """
        # 确保树存在
        tree = ensure_tree(entity)

        if not conversation_history:
            return None

        # 提取特征
        features = self._extractor.extract(conversation_history)

        # 存入 entity（用于 fork 比较）
        entity._recent_speaker_features[speaker_id] = dict(features)

        # 推断标签
        inferred_tags = self._inferrer.infer(features)

        # 获取现有节点
        existing_node = tree._individuals.get(speaker_id)

        # 如果是新说话者，基于相似度注册（必须在添加样本之前！）
        tree_grew = False
        if speaker_id not in tree._individuals or force_update:
            reg_result = tree.register_with_similarity(
                speaker_id,
                features,
                inferred_tags,
            )
            logger.debug(
                f"[StereotypeLearner] register: speaker={speaker_id}, "
                f"action={reg_result['action']}, "
                f"similar_to={reg_result.get('similar_to')}"
            )

        # 添加对话样本到树
        for msg in conversation_history[-self._extractor._window_size:]:
            sample = {
                "text": msg.get("text", ""),
                "emotion": msg.get("emotion", 0.0),
                "timestamp": msg.get("timestamp", 0.0),
            }
            tree.add_conversation_sample(speaker_id, sample)

        # 更新特征权重
        old_confidence = existing_node.confidence if existing_node else 0.0
        tree.update_features_from_samples(speaker_id)

        # 检查是否需要树生长（新标签 vs 现有标签）
        existing_node = tree._individuals.get(speaker_id)
        if existing_node:
            existing_tags = set(existing_node.tags)
            new_inferred = set(inferred_tags)
            new_tags = new_inferred - existing_tags

            if new_tags and (len(conversation_history) >= 3 or force_update):
                # 有新标签，触发树往下生长
                tree.add_individual(
                    speaker_id,
                    initial_tags=list(new_tags),
                    initial_features=features,
                )
                tree_grew = True
                logger.debug(
                    f"[StereotypeTree] grow: speaker={speaker_id}, "
                    f"new_tags={list(new_tags)}"
                )

        # 获取新置信度
        updated_node = tree._individuals.get(speaker_id)
        new_confidence = updated_node.confidence if updated_node else old_confidence

        logger.debug(
            f"[StereotypeLearner] learn: speaker={speaker_id}, "
            f"tags={inferred_tags}, samples={len(conversation_history)}, "
            f"confidence={old_confidence:.2f}->{new_confidence:.2f}, "
            f"tree_grew={tree_grew}"
        )

        return {
            "features": features,
            "inferred_tags": inferred_tags,
            "tree_updated": True,
            "confidence_delta": new_confidence - old_confidence,
            "tree_grew": tree_grew,
        }

    def quick_learn(
        self,
        entity,
        speaker_id: str,
        text: str,
        emotion: float = 0.0,
    ) -> None:
        """
        从单条消息快速学习。

        样本存入 entity._stereotype_conversation_history，
        累积足够（≥5条）后触发完整学习 + 树生长检查。

        参数：
            entity    : EntityState 实例
            speaker_id: 说话者 ID
            text      : 消息文本
            emotion   : 情感值
        """
        # 存入对话历史
        history = getattr(entity, "_stereotype_conversation_history", None)
        if history is None:
            entity._stereotype_conversation_history = {}
            history = entity._stereotype_conversation_history

        if speaker_id not in history:
            history[speaker_id] = []

        sample = {
            "text": text,
            "emotion": emotion,
            "timestamp": 0.0,
        }
        history[speaker_id].append(sample)
        # 最多保留 30 条
        if len(history[speaker_id]) > 30:
            history[speaker_id] = history[speaker_id][-30:]

        # 样本足够时触发完整学习（包含树的生长检查）
        if len(history[speaker_id]) >= 5:
            self.learn_from_conversation(entity, speaker_id, history[speaker_id])
            # 学习后清空历史（避免重复学习）
            history[speaker_id] = []

# ============================================================================
# 便捷函数
# ============================================================================

from .stereotype_memory import (
    extract_tags_from_memory as _extract_tags_from_memory,
    init_tree_from_memory as _init_tree_from_memory,
)


def extract_tags_from_memory(memory_path: str = "MEMORY.md") -> Dict[str, List[str]]:
    return _extract_tags_from_memory(memory_path)


def init_tree_from_memory(
    entity,
    memory_path: str = "MEMORY.md",
    speaker_id: str = "bcyq",
) -> None:
    return _init_tree_from_memory(entity, memory_path, speaker_id)


def learn_speaker(
    entity,
    speaker_id: str,
    conversation_history: List[Dict[str, Any]],
    force_update: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    从对话历史中学习说话者的刻板印象。

    参数：
        entity            : EntityState 实例
        speaker_id        : 说话者 ID
        conversation_history: 对话历史
        force_update      : 是否强制更新

    返回：
        学习结果
    """
    learner = StereotypeLearner()
    return learner.learn_from_conversation(entity, speaker_id, conversation_history, force_update)


def quick_learn(
    entity,
    speaker_id: str,
    text: str,
    emotion: float = 0.0,
) -> None:
    """
    从单条消息快速学习。
    """
    learner = StereotypeLearner()
    learner.quick_learn(entity, speaker_id, text, emotion)
