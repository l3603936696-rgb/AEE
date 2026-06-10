"""
3. ThoughtIntegration (思考融合)

v3 改造：

职责：遍历 thought_packet["suggestions"]，将 action 关键词翻译为趋近/回避信号。

perceive() 映射：
    探索类词 → approach_drive +（pressure=True → 更紧迫）
    恢复类词 → avoid_drive +（但实际上是被动的，故降低 approach_drive）

输入：thought_packet
输出：
    - evaluate(): 最多 max_suggestions 个 DriveSignal（向后兼容）
    - perceive(): 直接修改 entity_core 的 approach_drive / avoid_drive
"""

from typing import Any, List
from .base import DriveSignal, _clamp, _get_somatic_weight


class ThoughtIntegration:

    KEYWORD_SEEK_PRESSURE = ("加速", "紧迫", "冲刺", "赶时间", "马上")
    KEYWORD_SEEK         = ("探索", "获取", "发起", "更新", "社交")
    KEYWORD_COMFORT      = ("待机", "降低", "恢复", "休息")

    def _translate(self, action: str) -> tuple[str, bool]:
        for kw in self.KEYWORD_SEEK_PRESSURE:
            if kw in action:
                return ("seek", True)
        for kw in self.KEYWORD_SEEK:
            if kw in action:
                return ("seek", False)
        for kw in self.KEYWORD_COMFORT:
            if kw in action:
                return ("comfort", False)
        return ("seek", False)

    # =========================================================================
    # v3 新接口：perceive() — 直接修改 EntityCore
    # =========================================================================

    def perceive(self, inputs: dict, entity_core: Any) -> None:
        """
        根据思考建议，直接修改 entity_core 的驱动力。

        pressure=True 的 seek → 更强烈的 approach_drive
        无压力的 seek → 温和的 approach_drive
        comfort → 降低 approach_drive（倾向于保持现状）
        """
        thought = inputs.get("thought_packet", {})
        somatic_weight = _get_somatic_weight(entity_core)

        try:
            suggestions = thought.get("suggestions", [])
            if not suggestions:
                return

            max_sug = min(len(suggestions), int(inputs.get("params", {}).get("max_suggestions", 2)))

            for suggestion in suggestions[:max_sug]:
                if not isinstance(suggestion, dict):
                    continue
                action = str(suggestion.get("action", ""))
                priority = float(suggestion.get("priority", 0.5))
                sig_type, pressure_flag = self._translate(action)

                if sig_type == "seek":
                    base = priority * somatic_weight * 0.5
                    if pressure_flag:
                        # 压力驱动：更紧迫的趋近
                        entity_core.adjust("approach_urgency", base * 1.5)
                    else:
                        entity_core.adjust("approach_explore", base)
                elif sig_type == "comfort":
                    # 舒适状态 → 降低趋近驱动力
                    entity_core.adjust("approach_social", -priority * 0.3)

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
            suggestions = thought_packet.get("suggestions", [])
            if not suggestions:
                return []
            max_sug = int(params.get("max_suggestions", 2)) if isinstance(params, dict) else 2
            for suggestion in suggestions[:max_sug]:
                if not isinstance(suggestion, dict):
                    continue
                action = str(suggestion.get("action", ""))
                reason = str(suggestion.get("reason", ""))
                priority = float(suggestion.get("priority", 0.5))
                sig_type, pressure_flag = self._translate(action)
                signals.append(DriveSignal(
                    signal_type=sig_type,
                    strength=min(1.0, priority),
                    source="ThoughtIntegration",
                    pressure_flag=pressure_flag,
                    payload_draft={
                        "reason": reason or f"来自思考建议：{action}",
                        "context_id": "thought_suggestion",
                    }
                ))
        except Exception:
            pass
        return signals
