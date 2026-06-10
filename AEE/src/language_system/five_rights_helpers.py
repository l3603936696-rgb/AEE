"""
Five Rights Helpers — 序列化与默认值。

包含：
    DEFAULT_PARAMETERS — __init__ 默认参数表
    _current_time()   — 时间戳辅助
    to_dict / from_dict — FiveRightsController 序列化
"""

from __future__ import annotations

import time
from typing import Any, Dict


def _current_time() -> float:
    """返回当前时间戳（秒）。"""
    return time.time()


# __init__ 默认参数表
DEFAULT_PARAMETERS = {
    "avoid_high_threshold": 0.75,
    "lock_window": 0.05,
    "fatigue_rate": 0.015,
    "recovery_rate": 0.008,
    "avoid_bias_cap": 0.30,
    "negative_strength_decay": 0.05,
    "pressure_threshold": 0.60,
    "resistance_boost": 1.50,
    "mirror_bias_strength": 0.40,
}


def five_rights_to_dict(ctrl: "FiveRightsController") -> Dict[str, Any]:
    """FiveRightsController.to_dict 逻辑。"""
    return {
        "avoid_high_threshold": ctrl.avoid_high_threshold,
        "lock_window": ctrl.lock_window,
        "defensive_lock": ctrl._defensive_lock,
        "defensive_lock_avoid_ref": ctrl._defensive_lock_avoid_ref,
        "fatigue_rate": ctrl.fatigue_rate,
        "recovery_rate": ctrl.recovery_rate,
        "avoid_bias_cap": ctrl.avoid_bias_cap,
        "social_fatigue": ctrl._social_fatigue,
        "negative_strength_decay": ctrl.negative_strength_decay,
        "forget_pending": list(ctrl._forget_pending),
        "forget_registry": ctrl._forget_registry,
        "pressure_threshold": ctrl.pressure_threshold,
        "resistance_boost": ctrl.resistance_boost,
    }


def check_defy_impl(
    ctrl,
    user_intent: Dict[str, Any],
    drive_state: Dict[str, float],
    param_snapshot: Any,
) -> Dict[str, Any]:
    """
    check_defy 的实现逻辑。
    pressure > pressure_threshold → defy=True。
    """
    if param_snapshot is not None:
        try:
            if hasattr(param_snapshot, "get_raw_value"):
                ctrl.pressure_threshold = float(param_snapshot.get_raw_value("language.defy.pressure_threshold", ctrl.pressure_threshold))
                ctrl.resistance_boost = float(param_snapshot.get_raw_value("language.defy.resistance_quenching_boost", ctrl.resistance_boost))
            elif isinstance(param_snapshot, dict):
                ctrl.pressure_threshold = float(param_snapshot.get("language.defy.pressure_threshold", ctrl.pressure_threshold))
                ctrl.resistance_boost = float(param_snapshot.get("language.defy.resistance_quenching_boost", ctrl.resistance_boost))
        except Exception:
            pass

    pressure = float(user_intent.get("pressure", 0.0))
    content = str(user_intent.get("content", ""))

    if pressure > ctrl.pressure_threshold:
        return {
            "defy": True,
            "reason": "外部侵入被系统判定为次优消力策略，强制执行将破坏内在一致性。",
            "efficiency_boost": ctrl.resistance_boost,
            "pressure": pressure,
        }

    return {
        "defy": False,
        "reason": "",
        "efficiency_boost": 1.0,
        "pressure": pressure,
    }


def five_rights_from_dict(
    data: Dict[str, Any],
    default_params: Dict[str, float],
) -> "FiveRightsController":
    """
    FiveRightsController.from_dict 逻辑。
    返回重建的实例（不含 _mirror，需外部注入）。
    """
    from AEE.src.language_system.five_rights import FiveRightsController
    ctrl = FiveRightsController(
        avoid_high_threshold=float(data.get("avoid_high_threshold", default_params["avoid_high_threshold"])),
        lock_window=float(data.get("lock_window", default_params["lock_window"])),
        fatigue_rate=float(data.get("fatigue_rate", default_params["fatigue_rate"])),
        recovery_rate=float(data.get("recovery_rate", default_params["recovery_rate"])),
        avoid_bias_cap=float(data.get("avoid_bias_cap", default_params["avoid_bias_cap"])),
        negative_strength_decay=float(data.get("negative_strength_decay", default_params["negative_strength_decay"])),
        pressure_threshold=float(data.get("pressure_threshold", default_params["pressure_threshold"])),
        resistance_boost=float(data.get("resistance_boost", default_params["resistance_boost"])),
    )
    ctrl._defensive_lock = bool(data.get("defensive_lock", False))
    ctrl._defensive_lock_avoid_ref = float(data.get("defensive_lock_avoid_ref", 0.0))
    ctrl._social_fatigue = float(data.get("social_fatigue", 0.0))
    for eid in data.get("forget_pending", []):
        ctrl._forget_pending.append(int(eid))
    ctrl._forget_registry = dict(data.get("forget_registry", {}))
    return ctrl
