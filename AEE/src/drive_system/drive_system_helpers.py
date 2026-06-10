"""
Drive System Helpers — extracted from drive_system.py.

Public helpers: interpolate_lookup, sigmoid_curve, ShapeTable, DriveVector.
Drive computation functions: _compute_curiosity, _compute_info_hunger,
    _compute_loneliness_drive, _compute_fatigue_avoid, _compute_obsolescence_anxiety.
Affect multiplier: apply_affect_multiplier, apply_dopamine_multiplier.
"""

import bisect
import math
from dataclasses import dataclass
from typing import List, Optional


# =============================================================================
# Data Structures
# =============================================================================

@dataclass
class DriveVector:
    """驱动力向量输出结构"""
    curiosity: float = 0.0
    info_hunger: float = 0.0
    obsolescence_anxiety: float = 0.0
    loneliness_drive: float = 0.0
    fatigue_avoid: float = 0.0

    def to_dict(self) -> dict:
        return {
            "curiosity": round(self.curiosity, 3),
            "info_hunger": round(self.info_hunger, 3),
            "obsolescence_anxiety": round(self.obsolescence_anxiety, 3),
            "loneliness_drive": round(self.loneliness_drive, 3),
            "fatigue_avoid": round(self.fatigue_avoid, 3),
        }


@dataclass
class ShapeTable:
    """形态锚点表"""
    x_anchors: List[float]
    y_anchors: List[float]

    @classmethod
    def from_dict(cls, data: dict) -> "ShapeTable":
        return cls(
            x_anchors=data.get("x_anchors", []),
            y_anchors=data.get("y_anchors", [])
        )

    def is_valid(self) -> bool:
        return (
            len(self.x_anchors) >= 2 and
            len(self.y_anchors) >= 2 and
            len(self.x_anchors) == len(self.y_anchors)
        )


# =============================================================================
# Core Interpolation
# =============================================================================

def interpolate_lookup(x: float, x_anchors: List[float], y_anchors: List[float]) -> float:
    """
    Discrete table lookup with linear interpolation.

    - x <= x_anchors[0]: returns y_anchors[0]
    - x >= x_anchors[-1]: returns y_anchors[-1]
    - Otherwise: linear interpolation
    Returns float clamped to [0, 1].
    """
    try:
        if not x_anchors or not y_anchors:
            return 0.0
        if len(x_anchors) != len(y_anchors):
            return 0.0
        if len(x_anchors) < 2:
            return 0.0

        if x <= x_anchors[0]:
            return max(0.0, min(1.0, y_anchors[0]))
        if x >= x_anchors[-1]:
            return max(0.0, min(1.0, y_anchors[-1]))

        idx = bisect.bisect_right(x_anchors, x)
        x0, x1 = x_anchors[idx - 1], x_anchors[idx]
        y0, y1 = y_anchors[idx - 1], y_anchors[idx]

        if abs(x1 - x0) < 1e-10:
            return max(0.0, min(1.0, y0))

        t = (x - x0) / (x1 - x0)
        result = y0 + t * (y1 - y0)
        return max(0.0, min(1.0, result))

    except (TypeError, IndexError, ZeroDivisionError):
        return 0.0


# =============================================================================
# Generic Curve Functions
# =============================================================================

def sigmoid_curve(x: float, k: float = 1.0) -> float:
    """
    Sigmoid growth curve.

    formula: 1.0 / (1.0 + exp(-k * (x - 0.5)))
    - x=0.5: output=0.5
    - x=0: output~0.27 (baseline noise)
    - x=1: output~0.73
    """
    try:
        x = max(0.0, min(1.0, x))
        k = float(k) if k is not None else 1.0
        exp_val = -k * (x - 0.5)
        if exp_val > 700:
            return 1.0
        if exp_val < -700:
            return 0.0
        return 1.0 / (1.0 + math.exp(exp_val))
    except (TypeError, ValueError, OverflowError):
        return 0.0


# =============================================================================
# Drive Computation Functions
# =============================================================================

def _compute_curiosity(info_gap: float, curiosity_param: Optional[float] = None) -> float:
    """
    Curiosity drive (A-type, continuous).

    formula: curiosity = info_gap ^ (1/k)
    - info_gap=0 -> curiosity=0
    - info_gap=1 -> curiosity=1
    - k>1: more sensitive in low-gap region
    """
    try:
        info_gap = max(0.0, min(1.0, float(info_gap)))
        k = float(curiosity_param) if curiosity_param is not None else 1.0
        return math.pow(info_gap, 1.0 / max(0.1, k))
    except (TypeError, ValueError):
        return 0.0


def _compute_info_hunger(
    time_since_last_info: float,
    max_info_gap_hours: float,
    info_hunger_time_shape: dict
) -> float:
    """
    Information hunger drive (B-type, delay-truncated).

    formula: x = time / (max_hours * 3600)
             hunger = interpolate_lookup(x, anchors)
    """
    try:
        max_hours = float(max_info_gap_hours) if max_info_gap_hours else 24.0
        if max_hours <= 0:
            return 0.0

        x = float(time_since_last_info) / (max_hours * 3600.0)
        x = max(0.0, x)

        shape = ShapeTable.from_dict(info_hunger_time_shape)
        if not shape.is_valid():
            return 0.0

        return interpolate_lookup(x, shape.x_anchors, shape.y_anchors)
    except (TypeError, ValueError):
        return 0.0


def _compute_loneliness_drive(
    loneliness: float,
    time_since_last_social: float,
    max_social_gap_hours: float,
    loneliness_shape: dict,
    social_time_shape: dict
) -> float:
    """
    Loneliness drive (B-type, delay-truncated).

    formula: pressure = interpolate_lookup(loneliness, ...)
             time_factor = interpolate_lookup(time / (max_hours*3600), ...)
             drive = pressure * time_factor
    """
    try:
        loneliness = max(0.0, min(1.0, float(loneliness)))

        shape_s = ShapeTable.from_dict(loneliness_shape)
        if not shape_s.is_valid():
            return 0.0
        loneliness_pressure = interpolate_lookup(loneliness, shape_s.x_anchors, shape_s.y_anchors)

        max_hours = float(max_social_gap_hours) if max_social_gap_hours else 24.0
        if max_hours <= 0:
            return 0.0
        x_time = max(0.0, float(time_since_last_social) / (max_hours * 3600.0))

        shape_t = ShapeTable.from_dict(social_time_shape)
        if not shape_t.is_valid():
            return 0.0
        time_factor = interpolate_lookup(x_time, shape_t.x_anchors, shape_t.y_anchors)

        return max(0.0, min(1.0, loneliness_pressure * time_factor))
    except (TypeError, ValueError):
        return 0.0


def _compute_fatigue_avoid(energy: float, fatigue_shape: dict, fatigue: float = 0.0) -> float:
    """
    Fatigue avoidance drive (B-type, bounded).

    Dual signal: max(1.0-energy, fatigue)
    """
    try:
        energy = max(0.0, min(1.0, float(energy)))
        fatigue = max(0.0, min(1.0, float(fatigue)))
        x = max(1.0 - energy, fatigue)

        shape = ShapeTable.from_dict(fatigue_shape)
        if not shape.is_valid():
            return 0.0

        return interpolate_lookup(x, shape.x_anchors, shape.y_anchors)
    except (TypeError, ValueError):
        return 0.0


def _compute_obsolescence_anxiety(
    external_change_rate: float,
    unresolved: float,
    change_shape: dict,
    debt_shape: dict
) -> float:
    """
    Obsolescence anxiety drive (B-type, bounded).

    formula: change_pressure * debt_pressure
    """
    try:
        change_rate = max(0.0, min(1.0, float(external_change_rate)))
        unresolved_val = max(0.0, min(1.0, float(unresolved)))

        shape_c = ShapeTable.from_dict(change_shape)
        if not shape_c.is_valid():
            return 0.0
        change_pressure = interpolate_lookup(change_rate, shape_c.x_anchors, shape_c.y_anchors)

        shape_d = ShapeTable.from_dict(debt_shape)
        if not shape_d.is_valid():
            return 0.0
        debt_pressure = interpolate_lookup(unresolved_val, shape_d.x_anchors, shape_d.y_anchors)

        return max(0.0, min(1.0, change_pressure * debt_pressure))
    except (TypeError, ValueError):
        return 0.0


# =============================================================================
# Affect Multiplier
# =============================================================================

def apply_affect_multiplier(
    drive_vector: dict,
    dopamine_tone: float,
    oxytocin_tone: float,
) -> dict:
    """
    Dopamine tone + oxytocin tone continuous modulation (v11.x).

    dopamine formula: mult = 0.5 + dopamine_tone * 1.0
    oxytocin formula: mult = 0.5 + oxytocin_tone * 0.5

    All continuous, no if-else.
    """
    d_mult = 0.5 + dopamine_tone * 1.0
    for key in ("curiosity", "info_hunger", "approach_drive", "approach_explore"):
        if key in drive_vector:
            drive_vector[key] = min(1.0, drive_vector[key] * d_mult)

    o_mult = 0.5 + oxytocin_tone * 0.5
    if "approach_social" in drive_vector:
        drive_vector["approach_social"] = min(1.0, drive_vector["approach_social"] * o_mult)

    return drive_vector


def apply_dopamine_multiplier(
    drive_vector: dict,
    dopamine_tone: float,
) -> dict:
    """
    Dopamine tone modulation only (v11.x, backward compat).
    Prefer apply_affect_multiplier.
    """
    return apply_affect_multiplier(drive_vector, dopamine_tone, 0.5)
