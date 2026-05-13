"""
2. ContextAwareness (上下文感知)

v3 改造：

职责：
    - 根据语义包极性生成趋近/回避信号
    - 必须推导 target 并附加在信号中
    - 负向情绪 → avoid_drive；正向情绪 → approach_drive

输入：semantic_packet_biased, state_snapshot, drive_vector, wm_context
输出：
    - evaluate(): 1-2 个 DriveSignal（向后兼容）
    - perceive(): 直接修改 entity_core 的 loneliness / approach_drive / avoid_drive
"""

import logging
from typing import Any, List
from .base import DriveSignal, _clamp, _get_somatic_weight

logger = logging.getLogger(__name__)


class ContextAwareness:

    def _infer_target(self, semantic_packet_biased: dict) -> str:
        """从语义包中推导目标：求助/指令 → observer_user，其他 → none"""
        intent = str(semantic_packet_biased.get("intent", ""))
        if intent in ("求助", "指令"):
            return "observer_user"
        return "none"

    # =========================================================================
    # v3 新接口：perceive() — 直接修改 EntityCore
    # =========================================================================

    def perceive(self, inputs: dict, entity_core: Any) -> None:
        """
        根据情绪极性，直接修改 entity_core 的驱动力状态。

        修改映射：
            正向情绪 → approach_drive +（被 somatic_tone 调制）
            负向情绪 → avoid_drive +（被 somatic_tone 调制）
            loneliness 高时 → loneliness 状态不变（由 state_update 负责），
                              但增加 approach_drive（想连接）
            求助/指令意图 → target_locked = "observer_user"
        """
        sp = inputs.get("semantic_packet_biased", {})
        somatic_weight = _get_somatic_weight(entity_core)

        # ---- 推导并写入 target ----
        target = self._infer_target(sp)
        if target and target != "none":
            try:
                entity_core.set_field("target_locked", target)
            except (ValueError, AttributeError):
                pass

        try:
            emotion = float(sp.get("emotion", 0.0))
            intensity = float(sp.get("intensity", 0.5))
            confidence = min(1.0, abs(emotion) * intensity)

            # loneliness 高 → 内生社交趋近（不依赖外部 emotion）
            _lon = getattr(entity_core, "loneliness", 0.0)
            if _lon > 0.3:
                _lon_delta = (_lon - 0.3) * somatic_weight * 0.10
                entity_core.adjust("approach_social", _lon_delta)
                logger.info(
                    f"[ContextAwareness] loneliness={_lon:.3f} → "
                    f"approach_social +{_lon_delta:.4f}"
                )

            if confidence < 0.1:
                return

            # 正向情绪 → 趋近（v3.1: 从 0.4 降为 0.08）
            if emotion > 0.1:
                delta = confidence * somatic_weight * 0.08
                entity_core.adjust("approach_social", delta)
                # loneliness 高时，正向情绪驱动更强烈地想连接
                if entity_core.loneliness > 0.5:
                    entity_core.adjust("approach_social", confidence * 0.05)

            # 负向情绪 → 回避
            elif emotion < -0.1:
                delta = confidence * somatic_weight * 0.25
                entity_core.adjust("avoid_drive", delta)
                # 同时轻微提升 danger_level（感到威胁）
                entity_core.adjust("danger_level", confidence * 0.2)

        except Exception:
            pass

    # =========================================================================
    # 旧接口：evaluate() — 向后兼容
    # =========================================================================

    def evaluate(
        self,
        semantic_packet_biased: dict,
        concept_tags: List[dict],
        wm_context: dict,
        drive_vector: dict,
        thought_packet: dict,
        state_snapshot: dict,
        params: dict,
    ) -> List[DriveSignal]:
        signals = []
        try:
            target = self._infer_target(semantic_packet_biased)
            emotion = float(semantic_packet_biased.get("emotion", 0.0))
            intensity = float(semantic_packet_biased.get("intensity", 0.5))

            if emotion > 0.1:
                signals.append(DriveSignal(
                    signal_type="seek",
                    strength=min(1.0, abs(emotion) * intensity),
                    source="ContextAwareness",
                    target_locked=target,
                    pressure_flag=False,
                    payload_draft={
                        "reason": f"正向情绪（{emotion:.2f}），倾向寻求连接",
                        "context_id": "ctx_positive_emotion",
                    }
                ))
            elif emotion < -0.1:
                signals.append(DriveSignal(
                    signal_type="avoid",
                    strength=min(1.0, abs(emotion) * intensity),
                    source="ContextAwareness",
                    target_locked=target,
                    residue_cost_flag=True,
                    payload_draft={
                        "reason": f"负向情绪（{emotion:.2f}），倾向回避",
                        "context_id": "ctx_negative_emotion",
                    }
                ))
        except Exception:
            pass
        return signals
