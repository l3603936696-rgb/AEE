"""
Drive Tables — 驱动力场常量表与数学工具

供 drive_vector_field.py 的计算函数使用。
"""

from __future__ import annotations

import math
from typing import Dict, List


# ============================================================================
# 驱动力维度（状态层，7维）
# ============================================================================

DRIVE_DIMS: List[str] = [
    "curiosity",        # 好奇心（被疲惫/危险抑制）
    "info_hunger",      # 信息饥饿（被疲惫/危险抑制）
    "loneliness",       # 孤独感（疲惫时减弱）
    "fatigue",          # 疲惫感（抑制所有主动行为）
    "unresolved",       # 未闭合事项（疲惫/危险时减弱）
    "somatic_tone_p",  # 正向躯体基调（[-1,1] → [0,1]）
    "danger",           # 危险感（抑制探索）
]


# ============================================================================
# 拮抗矩阵（7×7）
# ============================================================================

DEFAULT_ANTAGONISM_MATRIX: Dict[str, Dict[str, float]] = {
    "curiosity": {
        "info_hunger":    0.20,
        "loneliness":     0.00,
        "fatigue":        0.15,
        "unresolved":     0.15,
        "somatic_tone_p": 0.00,
        "danger":         0.40,
    },
    "info_hunger": {
        "curiosity":      0.20,
        "loneliness":     0.15,
        "fatigue":        0.15,
        "unresolved":     0.15,
        "somatic_tone_p": 0.00,
        "danger":         0.35,
    },
    "loneliness": {
        "curiosity":      0.10,
        "info_hunger":    0.20,
        "fatigue":        0.15,
        "unresolved":     0.10,
        "somatic_tone_p": 0.00,
        "danger":         0.00,
    },
    "fatigue": {
        "curiosity":      0.70,
        "info_hunger":    0.70,
        "loneliness":     0.60,
        "unresolved":     0.50,
        "somatic_tone_p": 0.30,
        "danger":         0.25,
    },
    "unresolved": {
        "curiosity":      0.10,
        "info_hunger":    0.10,
        "loneliness":     0.10,
        "fatigue":        0.10,
        "somatic_tone_p": 0.00,
        "danger":         0.20,
    },
    "somatic_tone_p": {
        "curiosity":      0.00,
        "info_hunger":    0.00,
        "loneliness":     0.00,
        "fatigue":        0.20,
        "unresolved":     0.00,
        "danger":         0.35,
    },
    "danger": {
        "curiosity":      0.40,
        "info_hunger":    0.35,
        "loneliness":     0.15,
        "fatigue":        0.00,
        "unresolved":     0.20,
        "somatic_tone_p": 0.35,
    },
}


# ============================================================================
# alpha_k 个体化参数（连续质变平滑参数）
# ============================================================================

DEFAULT_ALPHA_K: Dict[str, Dict[str, float]] = {
    src: {dst: 1.0 for dst in DEFAULT_ANTAGONISM_MATRIX.get(src, {})}
    for src in DRIVE_DIMS
}


# ============================================================================
# 数学工具
# ============================================================================

def _sigmoid(x: float) -> float:
    """标准 sigmoid，输出 [0, 1]."""
    if x > 700:
        return 1.0
    if x < -700:
        return 0.0
    return 1.0 / (1.0 + math.exp(-x))


def _sigmoid_k(x: float, k: float) -> float:
    """带陡峭度参数的 sigmoid."""
    return _sigmoid(k * x)


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


# ============================================================================
# 数据提取
# ============================================================================

def _raw_drives_from_entity(entity_core) -> Dict[str, float]:
    """从 EntityCore 提取 raw_drives，每个维度归一化到 [0, 1]."""
    tone = getattr(entity_core, "somatic_tone", 0.0)
    return {
        "curiosity":       max(0.0, min(1.0, getattr(entity_core, "curiosity",       0.0))),
        "info_hunger":     max(0.0, min(1.0, getattr(entity_core, "info_hunger",     0.0))),
        "loneliness":     max(0.0, min(1.0, getattr(entity_core, "loneliness",     0.0))),
        "fatigue":        max(0.0, min(1.0, getattr(entity_core, "fatigue",          0.0))),
        "unresolved":     max(0.0, min(1.0, getattr(entity_core, "unresolved",     0.0))),
        "somatic_tone_p": max(0.0, min(1.0, (tone + 1.0) / 2.0)),
        "danger":         max(0.0, min(1.0, getattr(entity_core, "danger_level",    0.0))),
    }


def _drives_from_v1(drive_vector: Dict[str, float]) -> Dict[str, float]:
    """将 v1 的 drive_vector 字段名映射为 V6 的 raw_drives 字段名（1:1）."""
    return {
        "curiosity":       max(0.0, min(1.0, float(drive_vector.get("curiosity",             0.0)))),
        "info_hunger":    max(0.0, min(1.0, float(drive_vector.get("info_hunger",           0.0)))),
        "loneliness":     max(0.0, min(1.0, float(drive_vector.get("loneliness_drive",      0.0)))),
        "fatigue":        max(0.0, min(1.0, float(drive_vector.get("fatigue_avoid",          0.0)))),
        "unresolved":     max(0.0, min(1.0, float(drive_vector.get("unresolved_pressure",    0.0)))),
        "somatic_tone_p": max(0.0, min(1.0, (float(drive_vector.get("somatic_tone", 0.0)) + 1.0) / 2.0)),
        "danger":         max(0.0, min(1.0, float(drive_vector.get("obsolescence_anxiety",    0.0)))),
    }
