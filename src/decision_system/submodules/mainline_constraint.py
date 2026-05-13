"""
5. MainlineConstraint (主线约束)

v3 改造：

职责：读取主线进度缺失度，转化为回避驱动力（偏离主线 = 回避）。

perceive() 映射：
    主线进度缺失 → avoid_drive +（压力驱动，更紧迫）
    缺失度高时 → 同时轻微增加 approach_drive（想完成任务）

输入：state_snapshot
输出：
    - evaluate(): 1 个 DriveSignal（向后兼容）
    - perceive(): 直接修改 entity_core 的 avoid_drive
"""

from typing import Any, List
from .base import DriveSignal, _clamp, _get_somatic_weight


class MainlineConstraint:

    # =========================================================================
    # v3 新接口：perceive() — 直接修改 EntityCore
    # =========================================================================

    def perceive(self, inputs: dict, entity_core: Any) -> None:
        """
        读取主线进度缺失度，直接修改 entity_core 的 avoid_drive。
        """
        state_snap = inputs.get("state_snapshot", {})
        somatic_weight = _get_somatic_weight(entity_core)

        try:
            deficit = float(state_snap.get("mainline_deficit", 0.0))
            if deficit <= 0:
                return

            delta = deficit * somatic_weight * 0.3
            entity_core.adjust("avoid_drive", delta)
            # 缺失度高时，同时轻微提升趋近驱动（想完成任务）
            if deficit > 0.6:
                entity_core.adjust("approach_urgency", deficit * 0.2)

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
            deficit = float(state_snapshot.get("mainline_deficit", 0.0))
            if deficit <= 0:
                return []
            return [DriveSignal(
                signal_type="seek",
                strength=min(1.0, deficit),
                source="MainlineConstraint",
                pressure_flag=True,
                payload_draft={
                    "reason": f"主线进度缺失（{deficit:.2f}），需推进",
                    "context_id": "mainline_deficit",
                }
            )]
        except Exception:
            return []
