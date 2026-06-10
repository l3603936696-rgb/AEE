"""
Stereotype Learner Core — 刻板印象学习器核心类。

从 `stereotype_learner.py` 提取，保持 public API 不变。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class StereotypeLearner:
    """
    刻板印象学习器。

    协调 FeatureExtractor 和 TagInferrer，从对话历史中学习说话者的刻板印象，
    并更新刻板印象树。
    """

    def __init__(self):
        # 延迟导入避免循环
        from .stereotype_learner import FeatureExtractor, TagInferrer
        self._extractor = FeatureExtractor()
        self._inferrer = TagInferrer()

    def learn_from_conversation(
        self,
        entity,
        speaker_id: str,
        conversation_history: List[Dict[str, Any]],
        force_update: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """从对话历史中学习说话者的刻板印象，并触发树生长。"""
        from .stereotype_tree import ensure_tree

        tree = ensure_tree(entity)

        if not conversation_history:
            return None

        features = self._extractor.extract(conversation_history)
        entity._recent_speaker_features[speaker_id] = dict(features)
        inferred_tags = self._inferrer.infer(features)

        existing_node = tree._individuals.get(speaker_id)

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

        for msg in conversation_history[-self._extractor._window_size:]:
            sample = {
                "text": msg.get("text", ""),
                "emotion": msg.get("emotion", 0.0),
                "timestamp": msg.get("timestamp", 0.0),
            }
            tree.add_conversation_sample(speaker_id, sample)

        old_confidence = existing_node.confidence if existing_node else 0.0
        tree.update_features_from_samples(speaker_id)

        existing_node = tree._individuals.get(speaker_id)
        if existing_node:
            existing_tags = set(existing_node.tags)
            new_inferred = set(inferred_tags)
            new_tags = new_inferred - existing_tags

            if new_tags and (len(conversation_history) >= 3 or force_update):
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
        """从单条消息快速学习。"""
        history = getattr(entity, "_stereotype_conversation_history", None)
        if history is None:
            entity._stereotype_conversation_history = {}
            history = entity._stereotype_conversation_history

        if speaker_id not in history:
            history[speaker_id] = []

        sample = {"text": text, "emotion": emotion, "timestamp": 0.0}
        history[speaker_id].append(sample)
        if len(history[speaker_id]) > 30:
            history[speaker_id] = history[speaker_id][-30:]

        if len(history[speaker_id]) >= 5:
            self.learn_from_conversation(entity, speaker_id, history[speaker_id])
            history[speaker_id] = []
