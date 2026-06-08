"""
DriveVectorField — 驱动力场（拮抗 + 连续质变版）

从文档「拮抗力 + 连续质变」改造而来。

设计原则：
    - 驱动力不再做 argmax，所有维度完整保留
    - 拮抗矩阵决定量的相互抑制
    - 连续质变输出 fragmentation，让行为有质地而非硬切换
    - rule.effect 完全内生（从历史 snapshots 归纳，不是人工预设）

对外接口：
    compute_drive_field(entity_core, drive_vector, antagonism_matrix, alpha_k)
        → DriveFieldResult（含 raw_drives / net_drives / alpha / behavior_vector）

子模块：
    drive_tables.py — 常量表（DRIVE_DIMS, DEFAULT_ANTAGONISM_MATRIX, DEFAULT_ALPHA_K）
                     + 数学工具（_sigmoid, _sigmoid_k, _clamp）
                     + 数据提取（_raw_drives_from_entity, _drives_from_v1）
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Optional

from .drive_tables import (
    DRIVE_DIMS,
    DEFAULT_ANTAGONISM_MATRIX,
    DEFAULT_ALPHA_K,
    _sigmoid,
    _sigmoid_k,
    _clamp,
    _raw_drives_from_entity,
    _drives_from_v1,
)


# ============================================================================
# Step 2: 计算净力向量
# ============================================================================

def compute_net_drives(
    raw_drives: Dict[str, float],
    antagonism_matrix: Optional[Dict[str, Dict[str, float]]] = None,
) -> Dict[str, float]:
    """
    计算每个驱动力的净力（指数衰减抑制）。

    net[dst] = raw[dst] * exp(-Σ(src ≠ dst) raw[src] * weight[src][dst])

    指数衰减保证：
        - 信号被削弱但永远不会清零
        - 多源叠加是连续递减，不会断崖归零
        - 强信号在同等抑制下存活率更高
    """
    if antagonism_matrix is None:
        antagonism_matrix = DEFAULT_ANTAGONISM_MATRIX

    net_drives: Dict[str, float] = {}

    for dst in DRIVE_DIMS:
        raw_dst = raw_drives.get(dst, 0.0)
        inhibition_sum = 0.0

        for src in DRIVE_DIMS:
            if src == dst:
                continue
            raw_src = raw_drives.get(src, 0.0)
            weight = antagonism_matrix.get(src, {}).get(dst, 0.0)
            inhibition_sum += raw_src * weight

        net = raw_dst * math.exp(-inhibition_sum)
        net_drives[dst] = _clamp(net, 0.0, 1.0)

    return net_drives


# ============================================================================
# Step 3: 连续质变（force deformation）
# ============================================================================

def compute_fragmentation_coefficients(
    raw_drives: Dict[str, float],
    antagonism_matrix: Optional[Dict[str, Dict[str, float]]] = None,
    alpha_k: Optional[Dict[str, Dict[str, float]]] = None,
) -> Dict[str, float]:
    """
    对每个驱动力计算其质变系数 alpha（0=纯粹，1=高度变形）。

    alpha[dst] = clamp(
        Σ(src≠dst) sigmoid(k[src][dst] * raw[src] * weight[src][dst]) * raw[src]
        / max(1, Σ(src≠dst) raw[src])
        , 0, 1)
    """
    if antagonism_matrix is None:
        antagonism_matrix = DEFAULT_ANTAGONISM_MATRIX
    if alpha_k is None:
        alpha_k = DEFAULT_ALPHA_K

    alpha: Dict[str, float] = {}

    for dst in DRIVE_DIMS:
        weighted_sum = 0.0
        total_weight = 0.0

        for src in DRIVE_DIMS:
            if src == dst:
                continue
            raw_src = raw_drives.get(src, 0.0)
            if raw_src <= 0.0:
                continue
            weight = antagonism_matrix.get(src, {}).get(dst, 0.0)
            k = alpha_k.get(src, {}).get(dst, 1.0)
            contrib = _sigmoid_k(raw_src * weight, k)
            weighted_sum += contrib * raw_src
            total_weight += raw_src

        if total_weight > 1e-9:
            alpha[dst] = _clamp(weighted_sum / total_weight, 0.0, 1.0)
        else:
            alpha[dst] = 0.0

    return alpha


def compute_behavior_vector(
    raw_drives: Dict[str, float],
    net_drives: Dict[str, float],
    alpha: Dict[str, float],
) -> Dict[str, float]:
    """
    从 raw_drives / net_drives / alpha 生成 behavior_vector。

    behavior_vector[dst_intensity]     = net[dst] * (1 - alpha²)
    behavior_vector[dst_fragmentation] = net[dst] * alpha²
    """
    bv: Dict[str, float] = {}

    for dst in DRIVE_DIMS:
        net = net_drives.get(dst, 0.0)
        a = alpha.get(dst, 0.0)
        a_sq = a * a

        bv[f"{dst}_intensity"]     = net * (1.0 - a_sq)
        bv[f"{dst}_fragmentation"] = net * a_sq

    return bv


# ============================================================================
# 合并版主函数
# ============================================================================

def compute_drive_field(
    entity_core,
    drive_vector: Optional[Dict[str, float]] = None,
    antagonism_matrix: Optional[Dict[str, Dict[str, float]]] = None,
    alpha_k: Optional[Dict[str, Dict[str, float]]] = None,
) -> "DriveFieldResult":
    """
    驱动力场主入口。

    参数：
        entity_core: EntityCore 实例
        drive_vector: 可选，来自 v1 的驱动力向量 dict
        antagonism_matrix: 可选，自定义拮抗矩阵
        alpha_k: 可选，个体化 sigmoid 陡峭度参数

    返回：
        DriveFieldResult（dataclass）
    """
    if drive_vector is not None:
        raw_drives = _drives_from_v1(drive_vector)
    else:
        raw_drives = _raw_drives_from_entity(entity_core)
    net_drives  = compute_net_drives(raw_drives, antagonism_matrix)
    alpha       = compute_fragmentation_coefficients(raw_drives, antagonism_matrix, alpha_k)
    bv          = compute_behavior_vector(raw_drives, net_drives, alpha)

    return DriveFieldResult(
        raw_drives=raw_drives,
        net_drives=net_drives,
        alpha=alpha,
        behavior_vector=bv,
        antagonism_matrix=antagonism_matrix or DEFAULT_ANTAGONISM_MATRIX,
        alpha_k=alpha_k or DEFAULT_ALPHA_K,
    )


# ============================================================================
# 数据结构
# ============================================================================

@dataclass
class DriveFieldResult:
    """驱动力场的完整计算结果（7维）."""
    raw_drives:       Dict[str, float]
    net_drives:      Dict[str, float]
    alpha:            Dict[str, float]
    behavior_vector:  Dict[str, float]
    antagonism_matrix: Dict[str, Dict[str, float]]
    alpha_k:          Dict[str, Dict[str, float]]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "raw_drives":      {k: round(v, 4) for k, v in self.raw_drives.items()},
            "net_drives":      {k: round(v, 4) for k, v in self.net_drives.items()},
            "alpha":           {k: round(v, 4) for k, v in self.alpha.items()},
            "behavior_vector": {k: round(v, 4) for k, v in self.behavior_vector.items()},
        }

    def dominant_dim(self) -> str:
        """净力最大的维度."""
        return max(self.net_drives, key=lambda k: self.net_drives[k])

    def tension_level(self) -> float:
        """拮抗张力：净力分布的均衡程度 [0,1]，1=完全均衡."""
        vals = list(self.net_drives.values())
        if not vals:
            return 0.0
        total = sum(vals) + 1e-9
        max_v = max(vals)
        second_v = sorted(vals, reverse=True)[1] if len(vals) > 1 else 0.0
        return 1.0 - abs(max_v - second_v) / total


# ============================================================================
# 日志
# ============================================================================

def format_drive_field_log(result: DriveFieldResult, tick: int = 0) -> str:
    """生成单行日志，便于追踪."""
    dom = result.dominant_dim()
    tens = result.tension_level()
    lines = [
        f"[Tick {tick}] DriveField (7维)",
        f"  raw:    " + "  ".join(f"{k}={v:.3f}" for k, v in result.raw_drives.items()),
        f"  net:    " + "  ".join(f"{k}={v:.3f}" for k, v in result.net_drives.items()),
        f"  alpha:  " + "  ".join(f"{k}={v:.3f}" for k, v in result.alpha.items()),
        f"  BV:     " + "  ".join(f"{k}={v:.3f}" for k, v in result.behavior_vector.items()),
        f"  dominant={dom}  tension={tens:.3f}",
    ]
    return "\n".join(lines)
