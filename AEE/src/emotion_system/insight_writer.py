"""
InsightWriter — 惊讶→Insights 写入（v10.0/v11.0）

负责高冲击力惊讶事件的认知重组：

触发条件：
    - prediction_error 波动幅度超过 emotion_insight.high_impact_threshold
    - 来自 Step 8.3（世界模型预测误差注入）

认知重组功能：
    - 强制开启一次显性层 Insights 表写入
    - 存储：高情绪冲击系数、事件前后的驱动力场快照、关联环境特征和概念标签
    - 这些高冲击力事件成为世界观的基石

设计原则：
    - 参数外置：所有阈值从 param_snapshot 读取
    - 写入失败不阻断主流程
"""

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class InsightWriter:
    """
    惊讶→Insights 写入器。

    当 prediction_error 波动幅度超过高冲击阈值时，
    将当前事件强制写入 Insights 表，形成顽固的世界观基石。
    """

    def __init__(
        self,
        high_impact_threshold: float = 0.85,
    ) -> None:
        self.high_impact_threshold = high_impact_threshold

    # -------------------------------------------------------------------------
    # 高冲击判定
    # -------------------------------------------------------------------------

    @staticmethod
    def compute_impact_magnitude(
        prediction_error: float,
        drive_change_magnitude: float = 0.0,
    ) -> float:
        """
        计算情绪冲击幅度。

        计算方式：
            magnitude = sqrt(prediction_error^2 + drive_change^2)

        参数：
            prediction_error   : 预测误差（[-1, 1]）
            drive_change_magnitude: 驱动力场变化幅度

        返回：
            magnitude : [0, 1]
        """
        magnitude = (prediction_error ** 2 + drive_change_magnitude ** 2) ** 0.5
        return min(1.0, magnitude)

    # -------------------------------------------------------------------------
    # 写入
    # -------------------------------------------------------------------------

    def check_and_write(
        self,
        entity_state: Any,
        episode: Optional[Any],
        prediction_error: float,
        drive_change_magnitude: float,
        param_snapshot: Optional[Dict[str, Any]] = None,
        semantic_packet: Optional[Dict[str, Any]] = None,
    ) -> Optional[int]:
        """
        检查是否满足高冲击条件，若满足则写入 Insights 表。

        参数：
            entity_state         : EntityCore 实例
            episode             : 当前 Episode 对象（可选，用于提取快照）
            prediction_error    : 预测误差（[-1, 1]）
            drive_change_magnitude: 驱动力场变化幅度
            param_snapshot      : 参数快照
            semantic_packet     : 语义包（可选，用于提取概念标签）

        返回：
            新写入的 Insights 记录 ID，若未触发则返回 None
        """
        # 从 param_snapshot 读取阈值
        threshold = self.high_impact_threshold
        if param_snapshot is not None:
            threshold = float(
                param_snapshot.get("emotion", {})
                .get("emotion_insight.high_impact_threshold", self.high_impact_threshold)
            )

        # 计算冲击幅度
        magnitude = self.compute_impact_magnitude(prediction_error, drive_change_magnitude)

        if magnitude < threshold:
            logger.debug(
                f"[InsightWriter] impact={magnitude:.3f} < threshold={threshold:.3f}, skipping"
            )
            return None

        # 构造 drive_snapshot
        drive_snapshot = self._extract_drive_snapshot(entity_state)

        # 提取概念标签
        labels = self._extract_labels(semantic_packet)

        # 推断认知类型
        insight_type = self._classify_insight(
            prediction_error, magnitude, semantic_packet
        )

        # 提取事件内容描述
        content = self._extract_event_content(episode, semantic_packet, prediction_error)

        # 构造写入数据
        insight_data = {
            "insight_type": insight_type,
            "content": content,
            "drive_snapshot": json.dumps(drive_snapshot, ensure_ascii=False, default=str),
            "source_episode_id": episode.iteration_id if episode else None,
            "confidence": float(magnitude),
            "labels": json.dumps(labels, ensure_ascii=False),
        }

        # 写入 Insights 表
        try:
            from ..memory_hub.episodes_db import write_insight
            insight_id = write_insight(insight_data)
            if insight_id:
                logger.info(
                    f"[InsightWriter] Insight written: id={insight_id}, "
                    f"type={insight_type}, magnitude={magnitude:.3f}"
                )
            return insight_id
        except Exception as e:
            logger.warning(f"[InsightWriter] write_insight failed: {e}")
            return None

    # -------------------------------------------------------------------------
    # 辅助方法
    # -------------------------------------------------------------------------

    def _extract_drive_snapshot(self, entity_state: Any) -> Dict[str, Any]:
        """从 entity_state 提取驱动力场快照。"""
        if entity_state is None:
            return {}

        # 优先使用 to_state_snapshot（包含所有字段）
        if hasattr(entity_state, "to_state_snapshot"):
            return entity_state.to_state_snapshot()

        # fallback：直接读取关键字段
        snapshot = {}
        fields = [
            "energy", "loneliness", "unresolved", "fatigue",
            "somatic_tone", "approach_drive", "avoid_drive",
            "curiosity", "danger_level", "info_gap",
            "boredom_despair", "boredom_futility",
        ]
        for field in fields:
            val = getattr(entity_state, field, None)
            if val is not None:
                snapshot[field] = float(val)

        return snapshot

    def _extract_labels(self, semantic_packet: Optional[Dict[str, Any]]) -> List[str]:
        """从 semantic_packet 提取概念标签。"""
        if semantic_packet is None:
            return []

        labels: List[str] = []

        # intent
        intent = semantic_packet.get("intent", "")
        if intent:
            labels.append(f"intent:{intent}")

        # concept_tags
        concept_tags = semantic_packet.get("concept_tags", [])
        if concept_tags:
            for tag in concept_tags:
                if isinstance(tag, str):
                    labels.append(tag)
                elif isinstance(tag, dict):
                    labels.append(str(tag.get("tag", "")))

        # anchors
        anchors = semantic_packet.get("anchors", [])
        if anchors:
            for anchor in anchors:
                if isinstance(anchor, str):
                    labels.append(anchor)

        return labels[:10]  # 最多10个标签

    def _classify_insight(
        self,
        prediction_error: float,
        magnitude: float,
        semantic_packet: Optional[Dict[str, Any]],
    ) -> str:
        """
        根据 prediction_error 的方向和强度推断认知类型。

        分类：
            - prediction_error > 0 且高：世界模型低估了某种影响
            - prediction_error < 0 且高：世界模型高估了某种影响
            - 极高 magnitude：关键教训
            - 低 magnitude：微调观察
        """
        if magnitude >= 0.9:
            if prediction_error > 0:
                return "关键教训（低估）"
            elif prediction_error < 0:
                return "关键教训（高估）"
            else:
                return "关键观察"

        if abs(prediction_error) >= 0.3:
            if prediction_error > 0:
                return "经验偏差"
            else:
                return "预期偏差"

        # 从语义包推断
        if semantic_packet:
            intent = str(semantic_packet.get("intent", ""))
            if intent in ("question", "seeking"):
                return "好奇探索"
            elif intent in ("share", "express"):
                return "感受记录"
            elif intent in ("clarify", "propose"):
                return "意图观察"

        return "一般观察"

    def _extract_event_content(
        self,
        episode: Optional[Any],
        semantic_packet: Optional[Dict[str, Any]],
        prediction_error: float,
    ) -> str:
        """
        提取事件的自然语言描述。

        用于写入 Insights 表的 content 字段。
        """
        parts: List[str] = []

        # 从 semantic_packet 提取
        if semantic_packet:
            raw_input = semantic_packet.get("raw_input", "")
            if raw_input:
                parts.append(f"用户说：「{raw_input.strip()[:50]}」")

            emotion = semantic_packet.get("emotion", 0.0)
            if emotion is not None:
                e = float(emotion)
                if e > 0.3:
                    parts.append("情绪正面")
                elif e < -0.3:
                    parts.append("情绪负面")

        # 从 episode 提取
        if episode:
            raw_input = getattr(episode, "raw_input", None)
            if raw_input and not parts:
                parts.append(f"事件：「{str(raw_input).strip()[:50]}」")

        # prediction_error 方向
        if prediction_error > 0:
            parts.append("世界模型低估了影响")
        elif prediction_error < 0:
            parts.append("世界模型高估了影响")

        if not parts:
            parts.append("高冲击力事件")

        return "；".join(parts)
