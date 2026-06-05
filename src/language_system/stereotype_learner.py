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

logger = logging.getLogger(__name__)


# ============================================================================
# 常量
# ============================================================================

# 特征提取的统计窗口
FEATURE_WINDOW = 10  # 最近 N 条消息

# 哲学性标记词
PHILOSOPHICAL_MARKERS = frozenset({
    "可能", "也许", "应该", "其实", "我觉得", "我认为",
    "好像", "似乎", "大概", "或许", "究竟", "为什么",
    "是不是", "是不是说", "什么意思", "怎么理解",
})

# 元认知标记词
METACOGNITIVE_MARKERS = frozenset({
    "我觉得", "我认为", "我以为", "我知道", "我不知道",
    "你懂", "你理解", "你明白", "理解", "不清楚",
    "记得", "忘了", "想起来", "不确定",
})

# 分析性标记词
ANALYTICAL_MARKERS = frozenset({
    "因为", "所以", "但是", "如果", "虽然", "然而",
    "因此", "所以", "不过", "而且", "或者",
    "首先", "然后", "最后", "总之", "也就是说",
})

# 第一人称标记词
FIRST_PERSON_MARKERS = frozenset({
    "我", "我们", "我的", "我们的", "我自己",
})

# 情感词（简化版）
EMOTIONAL_MARKERS = frozenset({
    "开心", "高兴", "快乐", "舒服", "满足", "幸福",  # 正向
    "难过", "伤心", "痛苦", "难受", "焦虑", "害怕", "生气", "愤怒",  # 负向
    "啊", "呀", "呢", "吧", "哦", "嗯",  # 感叹/语气
})


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

# ============================================================================
# MEMORY.md 标签提取（阶段一初始化）
# ============================================================================

def extract_tags_from_memory(memory_path: str = "MEMORY.md") -> Dict[str, List[str]]:
    """
    从 MEMORY.md 提取说话者的基础标签。

    对应刻板印象树阶段一：粗粒度锚定。

    提取维度：
        - category   : 基础类别（大二学生）
        - region     : 地区/文化（UTC+8）
        - situation  : 社会情境（机械专业、民办本科、一人工公司）
        - individual : 个体标识（bcyq）

    参数：
        memory_path: MEMORY.md 文件路径

    返回：
        {"category": [...], "region": [...], "situation": [...], "individual": [...]}
    """
    import os

    if not os.path.exists(memory_path):
        return {}

    try:
        with open(memory_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return {}

    tags = {
        "category": [],
        "region": [],
        "situation": [],
        "individual": [],
    }

    lines = content.split("\n")

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        # 身份标签
        if "身份" in line or "bcyq" in line.lower():
            if "bcyq" in line.lower():
                tags["individual"].append("bcyq")

        # 背景标签
        if "背景" in line or "专业" in line:
            if "机械" in line:
                tags["situation"].append("理工科")
                tags["situation"].append("机械专业")
            if "大二" in line:
                tags["category"].append("大学生")
                tags["category"].append("大二学生")
            if "民办" in line:
                tags["situation"].append("民办本科")
            if "二本" in line:
                tags["situation"].append("二本")

        # 时区标签
        if "UTC" in line or "时区" in line:
            if "UTC+8" in line:
                tags["region"].append("亚洲东部")
                tags["region"].append("UTC+8")

        # 项目标签
        if "项目" in line or "XIA" in line:
            tags["situation"].append("AI项目")
            if "一人公司" in line:
                tags["situation"].append("一人公司")

        # 工作区标签
        if "工作区" in line:
            if "Windows" in line:
                tags["region"].append("Windows用户")
            if "WSL" in line:
                tags["region"].append("WSL2用户")

    # 去重
    for key in tags:
        tags[key] = list(dict.fromkeys(tags[key]))

    return tags


def init_tree_from_memory(
    entity,
    memory_path: str = "MEMORY.md",
    speaker_id: str = "bcyq",
) -> None:
    """
    从 MEMORY.md 提取标签，初始化说话者在刻板印象树中的位置。

    对应刻板印象树阶段一：粗粒度锚定。
    MEMORY 来的标签存入 node._category_tags（永不覆盖），用于跨个体匹配。
    """
    from .stereotype_tree import ensure_tree

    tags = extract_tags_from_memory(memory_path)
    if not tags or not any(tags.values()):
        return

    tree = ensure_tree(entity)
    all_tags = []
    for layer_tags in tags.values():
        all_tags.extend(layer_tags)

    # 去重但保持顺序
    all_tags = list(dict.fromkeys(all_tags))

    # 先 add_individual 创建节点
    # 过滤掉 speaker_id 自身（它会作为叶子节点名，不应该混入类别标签）
    filtered_tags = [t for t in all_tags if t != speaker_id]
    node = tree.add_individual(
        speaker_id=speaker_id,
        initial_tags=filtered_tags,
        initial_features=None,
    )
    # 把 MEMORY 来的类别标签锁入 _category_tags（永不覆盖）
    if node and filtered_tags:
        node._category_tags = list(filtered_tags)


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
