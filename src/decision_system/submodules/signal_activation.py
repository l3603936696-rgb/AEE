"""
4. SignalActivation (信号激活)

v3 改造：

职责：读取 semantic_packet_biased 中的情绪分类，映射为细粒度信号。

perceive() 映射：
    anger / fear → avoid_drive +（residue_cost，冷处理）
    sadness / surprise → approach_drive +（pressure=True）
    joy / trust → somatic_tone +（舒适感）

输入：semantic_packet_biased（包含 emotion_categories 和 emotion_polarity）
输出：
    - evaluate(): 1 个 DriveSignal（向后兼容）
    - perceive(): 直接修改 entity_core 的 avoid_drive / approach_drive / somatic_tone
"""

from typing import Any, List, Optional
from .base import DriveSignal, _clamp, _get_somatic_weight


class SignalActivation:

    # 分类 → (target_field, target_key, 调制系数)
    # target_field: "avoid_drive" | "approach_drive" | "somatic_tone"
    CATEGORY_MAP = {
        "anger":    ("avoid_drive",  False, 1.5),
        "fear":     ("avoid_drive",  False, 1.0),
        "sadness":  ("approach_drive", True, 0.2),   # v3.1: 从 1.5 降为 0.2（悲伤→趋近适度而非过载）
        "surprise": ("approach_drive", True, 0.5),
        "joy":      ("somatic_tone",  False, 0.8),
        "trust":    ("somatic_tone",  False, 0.6),
    }

    # =========================================================================
    # v3 新接口：perceive() — 直接修改 EntityCore
    # =========================================================================

    def perceive(self, inputs: dict, entity_core: Any) -> None:
        """
        根据情绪分类，直接修改 entity_core 的驱动力或基调。
        """
        sp = inputs.get("semantic_packet_biased", {})
        somatic_weight = _get_somatic_weight(entity_core)

        try:
            categories: dict = sp.get("emotion_categories", {}) or {}
            emotion: float = float(sp.get("emotion", 0.0))
            intensity: float = float(sp.get("intensity", 0.5))

            # ---- 细粒度分类信号（优先级最高）----
            best_category: Optional[str] = None
            best_score: float = -1.0

            for cat_name, cat_confidence in categories.items():
                if cat_name not in self.CATEGORY_MAP:
                    continue
                conf = float(cat_confidence)
                _, _, weight_mult = self.CATEGORY_MAP[cat_name]
                score = conf * weight_mult
                if score > best_score:
                    best_score = score
                    best_category = cat_name

            if best_category is not None and best_score > 0.1:
                target_field, is_pressure, _ = self.CATEGORY_MAP[best_category]
                strength = min(1.0, best_score * intensity)

                if target_field == "avoid_drive":
                    entity_core.adjust("avoid_drive", strength * somatic_weight * 0.25)
                elif target_field == "approach_drive":
                    factor = 0.8 if is_pressure else 0.5   # v3.1: 从 1.5/1.0 降
                    entity_core.adjust("approach_social", strength * somatic_weight * 0.15 * factor)
                elif target_field == "somatic_tone":
                    entity_core.adjust("somatic_tone", strength * 0.2)
                return

            # ---- 极性信号兜底 ----
            if abs(emotion) < 0.05:
                return

            confidence = min(1.0, abs(emotion) * intensity)
            if emotion > 0:
                entity_core.adjust("somatic_tone", confidence * 0.15)
            else:
                entity_core.adjust("avoid_drive", confidence * somatic_weight * 0.4)

        except Exception:
            pass

    # =========================================================================
    # 旧接口：evaluate() — 向后兼容
    # =========================================================================

    CATEGORY_MAP_EVAL = {
        "anger":    ("avoid",   False, True,  2.0),
        "fear":     ("avoid",   False, True,  1.5),
        "sadness":  ("seek",    True,  False, 1.5),
        "surprise": ("seek",    True,  False, 1.0),
        "joy":      ("comfort", False, False, 1.0),
        "trust":    ("comfort", False, False, 0.8),
    }

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
        try:
            categories: dict = semantic_packet_biased.get("emotion_categories", {}) or {}
            emotion: float = float(semantic_packet_biased.get("emotion", 0.0))
            intensity: float = float(semantic_packet_biased.get("intensity", 0.5))

            best_category: Optional[str] = None
            best_score: float = -1.0

            for cat_name, cat_confidence in categories.items():
                if cat_name not in self.CATEGORY_MAP_EVAL:
                    continue
                conf = float(cat_confidence)
                _, _, _, weight_mult = self.CATEGORY_MAP_EVAL[cat_name]
                score = conf * weight_mult
                if score > best_score:
                    best_score = score
                    best_category = cat_name

            if best_category is not None and best_score > 0.1:
                sig_type, pressure_flag, residue_flag, _ = self.CATEGORY_MAP_EVAL[best_category]
                strength = min(1.0, best_score * intensity)
                reason = f"情绪分类【{best_category}】（置信度 {best_score:.2f}），驱动 {sig_type}"
                return [DriveSignal(
                    signal_type=sig_type,
                    strength=strength,
                    source="SignalActivation",
                    pressure_flag=pressure_flag,
                    residue_cost_flag=residue_flag,
                    payload_draft={
                        "reason": reason,
                        "context_id": f"cat_{best_category}",
                        "emotion_category": best_category,
                        "category_confidence": best_score,
                    }
                )]

            if abs(emotion) < 0.05:
                return []

            confidence = min(1.0, abs(emotion) * intensity)
            sig_type = "comfort" if emotion > 0 else "avoid"
            reason = f"情绪极性（{'正向' if emotion > 0 else '负向'} {emotion:.2f}）激活，强度 {intensity:.2f}"

            return [DriveSignal(
                signal_type=sig_type,
                strength=confidence,
                source="SignalActivation",
                pressure_flag=False,
                residue_cost_flag=(sig_type == "avoid"),
                payload_draft={
                    "reason": reason,
                    "context_id": "signal_activation",
                    "emotion_category": "polarity",
                }
            )]

        except Exception:
            return []
