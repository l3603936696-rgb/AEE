"""
9. WorldModel (世界模型)

v3 改造：

职责：
    - coverage.hit_rate < 0.3 → 认知盲区 → curiosity +
    - 高置信度SEEK规律（≥0.7） → approach_drive +（熟悉场景=有据可依）
    - 低置信度危险规律（<0.3） → avoid_drive +

perceive() 映射：
    hit_rate 低 → curiosity +（认知缺口驱动好奇心）
    高置信度 SEEK 命中 → approach_drive +（熟悉场景，主动行动）
    低置信度 AVOID 命中 → avoid_drive +（危险感）

输入：wm_context
输出：
    - evaluate(): 1-2 个 DriveSignal（向后兼容）
    - perceive(): 直接修改 entity_core 的 curiosity / approach_drive / avoid_drive
"""

from typing import Any, List
from .base import DriveSignal, _clamp, _get_somatic_weight


class WorldModel:

    COVERAGE_THRESHOLD = 0.3
    DANGER_CONFIDENCE_THRESHOLD = 0.3
    HIGH_CONFIDENCE_SEEK_THRESHOLD = 0.7

    # =========================================================================
    # v3 新接口：perceive() — 直接修改 EntityCore
    # =========================================================================

    def perceive(self, inputs: dict, entity_core: Any) -> None:
        """
        根据世界模型查询结果，直接修改 entity_core 的驱动力。
        """
        wm = inputs.get("wm_context", {})
        somatic_weight = _get_somatic_weight(entity_core)

        try:
            coverage = wm.get("coverage", {}) or {}
            hit_rate = float(coverage.get("hit_rate", 0.0))
            matched = wm.get("matched_rules", []) or []

            # ---- 认知盲区 → curiosity + ----
            if hit_rate < self.COVERAGE_THRESHOLD:
                gap = self.COVERAGE_THRESHOLD - hit_rate
                entity_core.adjust("curiosity", gap * somatic_weight * 0.5)

            # ---- 高置信度 SEEK 规律 → approach_drive + ----
            high_conf_seek = [
                r for r in matched
                if str(r.get("signal_type", "")).upper() == "SEEK"
                and float(r.get("confidence", 0.0)) >= self.HIGH_CONFIDENCE_SEEK_THRESHOLD
            ]
            if high_conf_seek:
                best = max(high_conf_seek, key=lambda r: float(r.get("confidence", 0.0)))
                conf = float(best.get("confidence", 0.0))
                # 熟悉场景 → approach_drive；confidence 越高，趋近越强烈（v3.1: 从 0.4 降为 0.08）
                entity_core.adjust("approach_explore", conf * somatic_weight * 0.08)

            # ---- 低置信度 AVOID 规律 → avoid_drive + ----
            for rule in matched:
                sig_type = str(rule.get("signal_type", "")).upper()
                confidence = float(rule.get("confidence", 1.0))
                if sig_type == "AVOID" and confidence < self.DANGER_CONFIDENCE_THRESHOLD:
                    entity_core.adjust("avoid_drive", (confidence + 0.1) * somatic_weight * 0.3)
                    break

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
            coverage = wm_context.get("coverage", {}) or {}
            hit_rate = float(coverage.get("hit_rate", 0.0))
            matched = wm_context.get("matched_rules", []) or []

            if hit_rate < self.COVERAGE_THRESHOLD:
                signals.append(DriveSignal(
                    signal_type="seek",
                    strength=min(1.0, 0.8 - hit_rate),
                    source="WorldModel",
                    pressure_flag=True,
                    payload_draft={
                        "reason": f"世界模型覆盖不足（命中率 {hit_rate:.2f}），需探索",
                        "context_id": "wm_low_coverage",
                    }
                ))

            high_conf_seek_rules = [
                r for r in matched
                if str(r.get("signal_type", "")).upper() == "SEEK"
                and float(r.get("confidence", 0.0)) >= self.HIGH_CONFIDENCE_SEEK_THRESHOLD
            ]
            if high_conf_seek_rules:
                best_rule = max(high_conf_seek_rules, key=lambda r: float(r.get("confidence", 0.0)))
                best_conf = float(best_rule.get("confidence", 0.0))
                strength = max(best_conf, 0.5)
                signals.append(DriveSignal(
                    signal_type="seek",
                    strength=min(1.0, strength),
                    source="WorldModel",
                    pressure_flag=False,
                    payload_draft={
                        "reason": f"高置信度SEEK规律命中（置信度 {best_conf:.2f}），熟悉场景驱动主动选择",
                        "context_id": best_rule.get("rule_id", "wm_high_conf_seek"),
                        "rule_id": best_rule.get("rule_id", ""),
                        "confidence": best_conf,
                    }
                ))

            for rule in matched:
                sig_type = str(rule.get("signal_type", "")).upper()
                confidence = float(rule.get("confidence", 1.0))
                if sig_type == "AVOID" and confidence < self.DANGER_CONFIDENCE_THRESHOLD:
                    signals.append(DriveSignal(
                        signal_type="avoid",
                        strength=min(1.0, confidence + 0.1),
                        source="WorldModel",
                        residue_cost_flag=True,
                        payload_draft={
                            "reason": f"低置信度危险规律 [{rule.get('rule_id', '')}]，置信度 {confidence:.2f}",
                            "context_id": rule.get("rule_id", "wm_danger_rule"),
                        }
                    ))
                    break

        except Exception:
            pass
        return signals
