"""
6. TemporalPressure (时间压力)

v3 改造：

职责：读取时间紧迫度，直接修改 entity_core 的疲劳度和趋近驱动。

perceive() 映射：
    时间紧迫 → fatigue +（感到压力）+ approach_drive +（紧迫时更想行动）

输入：state_snapshot
输出：
    - evaluate(): 1 个 DriveSignal（向后兼容）
    - perceive(): 直接修改 entity_core 的 fatigue / approach_drive
"""

from typing import Any, List
from .base import DriveSignal, _clamp, _get_somatic_weight


class TemporalPressure:

    # =========================================================================
    # v3 新接口：perceive() — 直接修改 EntityCore
    # =========================================================================

    def perceive(self, inputs: dict, entity_core: Any) -> None:
        """
        读取时间紧迫度，直接修改 entity_core 的疲劳度和趋近驱动。
        """
        state_snap = inputs.get("state_snapshot", {})
        somatic_weight = _get_somatic_weight(entity_core)

        try:
            pressure = float(state_snap.get("time_pressure", 0.0))
            if pressure <= 0:
                return

            # 时间紧迫 → 疲劳感增加
            entity_core.adjust("fatigue", pressure * somatic_weight * 0.3)
            # 同时增加趋近驱动（紧迫时更想行动）
            entity_core.adjust("approach_urgency", pressure * 0.3)

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
        try:
            pressure = float(state_snapshot.get("time_pressure", 0.0))
            if pressure <= 0:
                return []
            return [DriveSignal(
                signal_type="seek",
                strength=min(1.0, pressure),
                source="TemporalPressure",
                pressure_flag=True,
                payload_draft={
                    "reason": f"时间紧迫度较高（{pressure:.2f}），需加速",
                    "context_id": "time_pressure",
                }
            )]
        except Exception:
            return []
