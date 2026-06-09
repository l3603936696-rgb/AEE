"""
Drive System Module (驱动力系统)

Pure sensor: computes drive intensity vector from entity state.
No behavior decisions, no signal suppression. No internal state.

Public API:
    compute_drive_vector(state_snapshot, params) -> dict
    apply_affect_multiplier(drive_vector, dopamine_tone, oxytocin_tone) -> dict

Submodules:
    drive_system_helpers.py — data structures, curves, drive computations
"""

from .drive_system_helpers import (
    DriveVector,
    ShapeTable,
    interpolate_lookup,
    sigmoid_curve,
    _compute_curiosity,
    _compute_info_hunger,
    _compute_loneliness_drive,
    _compute_fatigue_avoid,
    _compute_obsolescence_anxiety,
    apply_affect_multiplier,
    apply_dopamine_multiplier,
)


def compute_drive_vector(state_snapshot: dict, params: dict) -> dict:
    """
    驱动力系统主入口 — 唯一对外接口

    参数：
        state_snapshot: 当前实体状态快照
            - info_gap: float (0-1)
            - time_since_last_info: float (秒)
            - loneliness: float (0-1)
            - time_since_last_social: float (秒)
            - energy: float (0-1)
            - external_change_rate: float (0-1)
            - unresolved: float (0-1)

        params: 驱动力参数表
            - curiosity_param, max_info_gap_hours, max_social_gap_hours
            - info_hunger_time_shape, loneliness_shape, social_time_shape
            - fatigue_shape, change_shape, debt_shape

    返回：
        dict — 各驱动力已 clamp 到 [0, 1]
        {curiosity, info_hunger, obsolescence_anxiety, loneliness_drive, fatigue_avoid}
    """
    try:
        if not state_snapshot or not isinstance(state_snapshot, dict):
            return DriveVector().to_dict()
        if not params or not isinstance(params, dict):
            return DriveVector().to_dict()

        info_gap = state_snapshot.get("info_gap", 0.0)
        time_since_last_info = state_snapshot.get("time_since_last_info", 0.0)
        loneliness = state_snapshot.get("loneliness", 0.0)
        time_since_last_social = state_snapshot.get("time_since_last_social", 0.0)
        energy = state_snapshot.get("energy", 1.0)
        external_change_rate = state_snapshot.get("external_change_rate", 0.0)
        unresolved = state_snapshot.get("unresolved", 0.0)

        curiosity_param = params.get("curiosity_param")
        max_info_gap_hours = params.get("max_info_gap_hours", 24.0)
        max_social_gap_hours = params.get("max_social_gap_hours", 24.0)

        info_hunger_time_shape = params.get("info_hunger_time_shape", {})
        loneliness_shape = params.get("loneliness_shape", {})
        social_time_shape = params.get("social_time_shape", {})
        fatigue_shape = params.get("fatigue_shape", {})
        change_shape = params.get("change_shape", {})
        debt_shape = params.get("debt_shape", {})

        curiosity = _compute_curiosity(info_gap, curiosity_param)
        info_hunger = _compute_info_hunger(
            time_since_last_info, max_info_gap_hours, info_hunger_time_shape
        )
        loneliness_drive = _compute_loneliness_drive(
            loneliness, time_since_last_social,
            max_social_gap_hours, loneliness_shape, social_time_shape
        )
        fatigue = state_snapshot.get("fatigue", 0.0)
        fatigue_avoid = _compute_fatigue_avoid(energy, fatigue_shape, fatigue=fatigue)
        obsolescence_anxiety = _compute_obsolescence_anxiety(
            external_change_rate, unresolved, change_shape, debt_shape
        )

        result = DriveVector(
            curiosity=curiosity,
            info_hunger=info_hunger,
            obsolescence_anxiety=obsolescence_anxiety,
            loneliness_drive=loneliness_drive,
            fatigue_avoid=fatigue_avoid
        )

        return result.to_dict()

    except Exception:
        return DriveVector().to_dict()
