"""
Stage 07a Integrity Tick — 完整性感知系统模块。

提取自 s07a_state_update.py（[接入点 8] Step 12 integrity 块）。
包含：access record + integrity_scan + integrity_update + drive_bias + harm→pain/soma。
"""

from __future__ import annotations


def run_integrity_tick(entity, tick: int) -> None:
    """
    运行完整性感知 tick，写入 entity fields：
    - integrity_drive_bias
    - integrity_behavior_bias
    - active_harm
    - pain
    - somatic_tone
    """
    from pathlib import Path
    from AEE.src.core.integrity_monitor import scan as _integrity_scan
    from AEE.src.core.integrity_signal import update as _integrity_update
    from AEE.src.core.integrity_signal import apply_drive_bias as _integrity_apply_drive_bias
    from AEE.src.core.self_binding import record_accesses as _record_accesses

    _INHABITED_ZONES = ("perception", "expression", "cognition", "continuity")
    _HARM_TO_PAIN = 0.30
    _HARM_TO_SOMA = 0.20

    _project_root = Path(__file__).parents[5]
    _data_dir = _project_root / "data"
    _record_accesses(_INHABITED_ZONES, _data_dir)
    _events = _integrity_scan(_data_dir, _project_root, tick)
    _ir = _integrity_update(_events, entity, _data_dir)
    entity.integrity_drive_bias = _integrity_apply_drive_bias(
        entity, _ir["drive_delta"], getattr(entity, "integrity_drive_bias", {}) or {}
    )
    entity.integrity_behavior_bias = _ir.get("behavior_bias", {})
    entity.active_harm = float(_ir.get("active_harm", 0.0))
    _harm_rise = float(_ir.get("harm_rise", 0.0))
    _cur_pain = float(getattr(entity, "pain", 0.0))
    entity.pain = max(0.0, min(1.0, _cur_pain + _harm_rise * _HARM_TO_PAIN))
    _cur_tone = float(getattr(entity, "somatic_tone", 0.0))
    entity.somatic_tone = max(-1.0, min(1.0, _cur_tone - _harm_rise * _HARM_TO_SOMA))
