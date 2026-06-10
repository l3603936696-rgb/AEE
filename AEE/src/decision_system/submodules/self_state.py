"""
7. SelfState (自我状态)

v3 改造：

职责：读取内部痛苦值/疲劳度/能量，直接修改 EntityCore 状态。

perceive() 映射：
    高痛苦 → avoid_drive +（历史遗留的沉没成本）
    能量极低 → avoid_drive +（需要休息）
    疲劳度高 → somatic_tone -（疲惫感降低整体基调）

输入：state_snapshot
输出：
    - evaluate(): 1-3 个 DriveSignal（向后兼容）
    - perceive(): 直接修改 entity_core 的 avoid_drive / somatic_tone
"""

from typing import Any, List
from .base import DriveSignal, _clamp, _get_somatic_weight


class SelfState:

    # =========================================================================
    # v3 新接口：perceive() — 直接修改 EntityCore
    # =========================================================================

    def perceive(self, inputs: dict, entity_core: Any) -> None:
        """
        读取内部状态，直接修改 entity_core 的 avoid_drive 和 somatic_tone。
        """
        state_snap = inputs.get("state_snapshot", {})
        somatic_weight = _get_somatic_weight(entity_core)

        try:
            pain = float(state_snap.get("pain", 0.0))
            energy = float(state_snap.get("energy", 1.0))
            fatigue = float(state_snap.get("fatigue", 0.0))

            # 高痛苦 → avoid_drive +
            if pain > 0.3:
                delta = min(1.0, pain) * somatic_weight * 0.4
                entity_core.adjust("avoid_drive", delta)
                # 同时降低 somatic_tone（痛苦=负面感受）
                entity_core.adjust("somatic_tone", -pain * 0.3)

            # 能量极低 → avoid_drive +
            if energy < 0.2:
                delta = min(1.0, 1.0 - energy) * somatic_weight * 0.4
                entity_core.adjust("avoid_drive", delta)
                # 能量极低时也会降低基调
                entity_core.adjust("somatic_tone", -(1.0 - energy) * 0.2)

            # 疲劳度高 → somatic_tone -（疲惫降低整体感受基调）
            if fatigue > 0.5:
                entity_core.adjust("somatic_tone", -fatigue * 0.2)

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
            pain = float(state_snapshot.get("pain", 0.0))
            energy = float(state_snapshot.get("energy", 1.0))
            fatigue = float(state_snapshot.get("fatigue", 0.0))

            if pain > 0.3:
                signals.append(DriveSignal(
                    signal_type="avoid",
                    strength=min(1.0, pain),
                    source="SelfState",
                    residue_cost_flag=True,
                    payload_draft={
                        "reason": f"内部痛苦值较高（{pain:.2f}）",
                        "context_id": "self_pain",
                    }
                ))

            if energy < 0.2:
                signals.append(DriveSignal(
                    signal_type="avoid",
                    strength=min(1.0, 1.0 - energy),
                    source="SelfState",
                    residue_cost_flag=True,
                    payload_draft={
                        "reason": f"能量极低（{energy:.2f}），需休息",
                        "context_id": "self_energy_low",
                    }
                ))

            if fatigue > 0.5:
                signals.append(DriveSignal(
                    signal_type="comfort",
                    strength=min(1.0, fatigue),
                    source="SelfState",
                    residue_cost_flag=False,
                    payload_draft={
                        "reason": f"疲劳度高（{fatigue:.2f}），建议休息",
                        "context_id": "self_fatigue",
                    }
                ))
        except Exception:
            pass
        return signals
