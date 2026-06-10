"""
1. SituationAssessment (情境评估)

v3 改造：

职责：读取 drive_vector 中的 curiosity 和 info_hunger，转化为趋近驱动。

perceive() 映射：
    curiosity 高 → approach_drive +（好奇心驱动）
    info_hunger 高 → approach_drive +（信息饥饿驱动）

输入：concept_tags, state_snapshot, drive_vector
输出：
    - evaluate(): 包含至多 2 个 DriveSignal 的列表（向后兼容）
    - perceive(): 直接修改 entity_core 的 approach_drive
"""

from typing import Any, List
from .base import DriveSignal, _clamp, _get_somatic_weight


class SituationAssessment:

    # =========================================================================
    # v3 新接口：perceive() — 直接修改 EntityCore
    # =========================================================================

    def perceive(self, inputs: dict, entity_core: Any) -> None:
        """
        读取驱动力向量，直接修改 entity_core 的 approach_drive。
        """
        dv = inputs.get("drive_vector", {})
        somatic_weight = _get_somatic_weight(entity_core)

        try:
            curiosity = float(dv.get("curiosity", 0.0))
            if curiosity > 0:
                entity_core.adjust("approach_explore", curiosity * somatic_weight * 0.10)  # v3.1: 从 0.5 降

            info_hunger = float(dv.get("info_hunger", 0.0))
            if info_hunger > 0:
                entity_core.adjust("approach_explore", info_hunger * somatic_weight * 0.06)  # v3.1: 从 0.3 降

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
            dv = drive_vector or {}

            curiosity = float(dv.get("curiosity", 0.0))
            if curiosity > 0:
                signals.append(DriveSignal(
                    signal_type="seek",
                    strength=min(1.0, curiosity),
                    source="SituationAssessment",
                    pressure_flag=True,
                    payload_draft={
                        "reason": "好奇心驱动，当前信息缺口较大",
                        "context_id": "drive_curiosity",
                    }
                ))

            info_hunger = float(dv.get("info_hunger", 0.0))
            if info_hunger > 0 and len(signals) < 2:
                signals.append(DriveSignal(
                    signal_type="seek",
                    strength=min(1.0, info_hunger),
                    source="SituationAssessment",
                    pressure_flag=True,
                    payload_draft={
                        "reason": "信息饥饿驱动，当前信息不足",
                        "context_id": "drive_info_hunger",
                    }
                ))
        except Exception:
            pass
        return signals
