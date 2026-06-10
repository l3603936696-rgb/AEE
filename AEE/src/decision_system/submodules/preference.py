"""
8. Preference (人格偏好)

v3 改造：

职责：从 params 读取人格底色偏好，静态查表。

perceive() 映射：
    内向 → avoid_drive +（对外部刺激不敏感，更想退缩）
    外向 → approach_drive +（对外部刺激敏感，更想连接）

输入：state_snapshot, params
输出：
    - evaluate(): 1-2 个 DriveSignal（向后兼容）
    - perceive(): 直接修改 entity_core 的 approach_drive / avoid_drive
"""

from typing import Any, List
from .base import DriveSignal, _clamp, _get_somatic_weight


class Preference:

    # =========================================================================
    # v3 新接口：perceive() — 直接修改 EntityCore
    # =========================================================================

    def perceive(self, inputs: dict, entity_core: Any) -> None:
        """
        根据人格偏好，直接修改 entity_core 的驱动力。
        """
        params = inputs.get("params", {})
        personality = params.get("personality", {}) if isinstance(params, dict) else {}

        try:
            introverted = float(personality.get("introverted_bias", 0.0))
            if introverted > 0.3:
                # 内向 → 回避驱动力增加
                entity_core.adjust("avoid_drive", introverted * 0.2)

            extroverted = float(personality.get("extroverted_bias", 0.0))
            if extroverted > 0.3:
                # 外向 → 趋近驱动力增加
                entity_core.adjust("approach_social", extroverted * 0.2)

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
            personality = (params or {}).get("personality", {}) if isinstance(params, dict) else {}

            introverted = float(personality.get("introverted_bias", 0.0))
            if introverted > 0.3:
                signals.append(DriveSignal(
                    signal_type="avoid",
                    strength=min(1.0, introverted * 0.3),
                    source="Preference",
                    residue_cost_flag=True,
                    payload_draft={
                        "reason": f"人格偏好内向（{introverted:.2f}），外部刺激不敏感",
                        "context_id": "personality_introverted",
                    }
                ))

            extroverted = float(personality.get("extroverted_bias", 0.0))
            if extroverted > 0.3:
                signals.append(DriveSignal(
                    signal_type="seek",
                    strength=min(1.0, extroverted * 0.3),
                    source="Preference",
                    pressure_flag=False,
                    payload_draft={
                        "reason": f"人格偏好外向（{extroverted:.2f}），倾向外部刺激",
                        "context_id": "personality_extroverted",
                    }
                ))
        except Exception:
            pass
        return signals
