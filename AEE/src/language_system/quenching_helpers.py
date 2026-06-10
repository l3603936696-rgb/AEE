"""
Quenching Helpers — 哈希与序列化辅助。

包含：_hash_state() / record_to_dict() / record_from_dict()。
"""

from typing import Dict

from .quenching_schema import QuenchingRecord


def _hash_state(state: Dict[str, float]) -> str:
    """
    将驱动力场状态离散化为字符串哈希。只处理数值型 key。

    离散化方案：
    - 主维度（0.2 桶）: approach_drive, avoid_drive, loneliness,
      energy, somatic_tone, boredom, approach_social/explore/urgency
    - 沉寂维度（0.1 桶，精细区分低值域）:
      danger_level, fatigue, stress, pain, unresolved, relief_debt
    """
    _COARSE = ["L", "ML", "M", "MH", "H"]           # 0.2 桶
    _FINE = ["vL", "L", "LM", "M", "MH", "H", "H+", "VH", "VH+", "MAX"]  # 0.1 桶
    _FINE_KEYS = {
        "danger_level", "fatigue", "stress", "pain",
        "unresolved", "relief_debt",
    }
    parts = []
    for key in sorted(state.keys()):
        val = state[key]
        if not isinstance(val, (int, float)):
            continue
        if key in _FINE_KEYS:
            bucket = min(int(val / 0.1), 9)
            parts.append(f"{key}={_FINE[bucket]}")
        else:
            bucket = min(int(val / 0.2), 4)
            parts.append(f"{key}={_COARSE[bucket]}")
    return "|".join(parts)


def record_to_dict(r: QuenchingRecord) -> Dict:
    """QuenchingRecord -> dict（用于 QuenchingTracker.to_dict）。"""
    return {
        "drive_state_hash": r.drive_state_hash,
        "expression": r.expression,
        "delta_unresolved_before": r.delta_unresolved_before,
        "delta_unresolved_after": r.delta_unresolved_after,
        "quenching_efficiency": r.quenching_efficiency,
        "timestamp": r.timestamp,
        "tick": r.tick,
        "template_idx": r.template_idx,
    }


def record_from_dict(data: Dict) -> QuenchingRecord:
    """dict -> QuenchingRecord（用于 QuenchingTracker.from_dict）。"""
    return QuenchingRecord(
        drive_state_hash=str(data.get("drive_state_hash", "")),
        expression=str(data.get("expression", "")),
        delta_unresolved_before=float(data.get("delta_unresolved_before", 0.0)),
        delta_unresolved_after=float(data.get("delta_unresolved_after", 0.0)),
        quenching_efficiency=float(data.get("quenching_efficiency", 0.0)),
        timestamp=float(data.get("timestamp", 0.0)),
        tick=int(data.get("tick", 0)),
        template_idx=int(data.get("template_idx", -1)),
    )
