"""
counterfactual_probe.py — 反事实分析器

五个平行世界重算逻辑 + 自动分析标签生成。

绝对不参与主决策——输出只写入探针日志。
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional


# ============================================================================
# 5.2 平行世界重算
# ============================================================================

def _recompute_base(
    intermediates: Dict[str, Any],
    param_snapshot: Any,
    clean_somatic: Optional[float] = None,
    clean_tension: Optional[float] = None,
) -> float:
    """
    重新计算 base_connection_depth（可覆盖 somatic_factor 或 tension_factor）。

    参数：
        intermediates : compute_connection_depth_ex 返回的 intermediates dict
        param_snapshot : 参数快照
        clean_somatic : 若非 None，用此值替代 somatic_factor
        clean_tension : 若非 None，用此值替代 tension_factor
    """
    w_pred    = intermediates.get("w_prediction", _get_param(param_snapshot, "connection.w_prediction", 1.0))
    w_som     = intermediates.get("w_somatic",    _get_param(param_snapshot, "connection.w_somatic",    1.0))
    w_tension = intermediates.get("w_tension",   _get_param(param_snapshot, "connection.w_tension",   1.0))

    pred_f  = intermediates.get("prediction_factor", 0.0)
    som_f   = clean_somatic if clean_somatic is not None else intermediates.get("somatic_factor", 0.0)
    tens_f  = clean_tension if clean_tension is not None else intermediates.get("tension_factor", 0.0)

    numerator = w_pred * pred_f + w_som * som_f + w_tension * tens_f
    denominator = w_pred + w_som + w_tension
    return numerator / denominator


def _apply_coherence_once(
    base_depth: float,
    loneliness: float,
    param_snapshot: Any,
    skip: bool = False,
) -> float:
    """
    对 base_depth 施或不施 coherence 调制（使用中性 coherence = 0.5）。

    skip=True 时跳过 coherence 调制，等价于 no_coherence 平行世界。
    """
    if skip:
        return base_depth

    high_thresh = _get_param(param_snapshot, "connection.coherence_high_threshold", 0.70)
    low_thresh  = _get_param(param_snapshot, "connection.coherence_low_threshold",  0.30)
    amplify     = _get_param(param_snapshot, "connection.coherence_amplify",      1.30)
    attenuate   = _get_param(param_snapshot, "connection.coherence_attenuate",    0.50)
    damping_floor = _get_param(param_snapshot, "connection.negative_damping_floor", 0.70)
    damping_scale = _get_param(param_snapshot, "connection.damping_scale",          0.30)

    coherence = 0.5  # 中性 coherence = 无调制效果
    cd = base_depth

    if coherence > high_thresh:
        cd = cd * amplify
    elif coherence < low_thresh:
        cd = cd * attenuate

    damping_applied = 1.0
    if cd < 0:
        damping_applied = 1.0 - (loneliness * damping_scale)
        damping_applied = max(damping_applied, damping_floor)
        cd = cd * damping_applied

    return max(-1.0, min(1.0, cd))


def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _get_param(p: Any, key: str, default: float) -> float:
    if p is None:
        return default
    if hasattr(p, "get"):
        v = p.get(key)
        if v is not None:
            return float(v)
    return default


# ============================================================================
# 5.3 五个平行世界
# ============================================================================

def run_counterfactual_probe(
    tick: int,
    connection_depth_real: float,
    loneliness_target_real: float,
    intermediates: Dict[str, Any],
    loneliness: float,
    tension_level: float,
    somatic_tone_delta: float,
    param_snapshot: Any,
    contamination_coefficient: float = 0.3,
) -> Dict[str, Any]:
    """
    运行反事实探针，构造五个平行世界。

    参数：
        tick                    : 当前 tick
        connection_depth_real  : 真实 connection_depth_effective
        loneliness_target_real : 真实 loneliness_target
        intermediates           : compute_connection_depth_ex 返回的 intermediates
        loneliness              : 当前 loneliness（用于 no_contamination 估算）
        tension_level           : 本轮 tension_level
        somatic_tone_delta      : 本轮 somatic_tone_delta
        param_snapshot          : 参数快照
        contamination_coefficient : loneliness 对 somatic/tension 的污染系数

    返回：
        counterfactual_report（含五组 connection_depth + delta + 自动分析）
    """
    real_conn = connection_depth_real

    # ---- no_experience ----
    # 关闭经验偏移层：depth_after_bias = base_depth（无 experience_bias）
    base_no_exp = _recompute_base(intermediates, param_snapshot)
    conn_no_exp = _apply_coherence_once(
        base_no_exp, loneliness, param_snapshot, skip=False
    )

    # ---- no_coherence ----
    # 跳过 coherence 调制：直接用 depth_after_bias
    depth_after_bias = intermediates.get("depth_after_bias", base_no_exp)
    conn_no_coh = _apply_coherence_once(
        depth_after_bias, loneliness, param_snapshot, skip=True
    )

    # ---- no_contamination ----
    # 估算污染并重建"干净"因子
    contam_est = loneliness * contamination_coefficient
    contam_est = max(0.0, min(0.9, contam_est))

    raw_somatic = intermediates.get("somatic_factor", 0.0)
    raw_tension = intermediates.get("tension_factor", 0.0)

    # 干净 somatic：原值 / (1 + contam_est)（正向污染降低连接感）
    if contam_est > 0:
        clean_som = raw_somatic / (1.0 + contam_est)
    else:
        clean_som = raw_somatic

    # 干净 tension：原值 / (1 - contam_est * 0.5)（降低回避感）
    if contam_est > 0:
        clean_tens = raw_tension / (1.0 + contam_est * 0.5)
    else:
        clean_tens = raw_tension

    clean_base = _recompute_base(intermediates, param_snapshot, clean_som, clean_tens)
    conn_no_contam = _apply_coherence_once(
        clean_base, loneliness, param_snapshot, skip=False
    )

    # ---- pure_input ----
    # 只保留 prediction_error 因子，极低权重给其他项
    pred_f = intermediates.get("prediction_factor", 0.0)
    som_f  = intermediates.get("somatic_factor", 0.0)
    tens_f = intermediates.get("tension_factor", 0.0)
    conn_pure = 0.9 * pred_f + 0.05 * som_f + 0.05 * tens_f
    conn_pure = max(-1.0, min(1.0, conn_pure))

    # ---- 分析标签 ----
    deltas = {
        "experience": abs(conn_no_exp - real_conn),
        "coherence": abs(conn_no_coh - real_conn),
        "contamination": abs(conn_no_contam - real_conn),
        "pure_gap": abs(conn_pure - real_conn),
    }

    dominant = max(deltas, key=deltas.get)
    sorted_keys = sorted(deltas, key=deltas.get, reverse=True)
    secondary = sorted_keys[1] if len(sorted_keys) > 1 else dominant

    interpretations: List[str] = []
    if deltas["contamination"] > 0.15:
        interpretations.append("当前低连接主要由内部状态驱动")
    if deltas["experience"] > 0.05:
        interpretations.append("历史经验显著影响当前感知")
    if deltas["coherence"] > 0.1:
        interpretations.append("时间结构放大效应明显")
    if deltas["pure_gap"] > 0.2:
        if conn_pure > 0.4:
            interpretations.append("外部交互本身质量中等偏上")
        else:
            interpretations.append("外部交互本身质量偏低")

    if conn_no_contam > real_conn + 0.1:
        interpretations.append("系统存在负向自强化趋势")

    analysis = {
        "dominant_distortion": dominant,
        "secondary": secondary,
        "interpretations": interpretations,
    }

    return {
        "tick": tick,
        "baseline": {
            "connection_depth": round(real_conn, 4),
            "loneliness_target": round(loneliness_target_real, 4),
        },
        "no_experience": {
            "connection_depth": round(conn_no_exp, 4),
            "delta_from_baseline": round(conn_no_exp - real_conn, 4),
        },
        "no_coherence": {
            "connection_depth": round(conn_no_coh, 4),
            "delta_from_baseline": round(conn_no_coh - real_conn, 4),
        },
        "no_contamination": {
            "connection_depth": round(conn_no_contam, 4),
            "delta_from_baseline": round(conn_no_contam - real_conn, 4),
            "contamination_estimate": round(contam_est, 4),
        },
        "pure_input": {
            "connection_depth": round(conn_pure, 4),
            "delta_from_baseline": round(conn_pure - real_conn, 4),
        },
        "analysis": analysis,
    }


# ============================================================================
# 4.4 自动分析标签（独立入口，供外部调用）
# ============================================================================

def _generate_counterfactual_analysis(report: Dict[str, Any]) -> Dict[str, Any]:
    """
    根据已生成的 counterfactual_report 生成自动分析标签。

    参数：
        report : run_counterfactual_probe 返回的完整报告

    返回：
        analysis dict（含 dominant_distortion, secondary, interpretations）
    """
    baseline_conn = _safe_float(report.get("baseline", {}).get("connection_depth"), 0.0)

    deltas = {
        "experience": abs(_safe_float(report.get("no_experience", {}).get("delta_from_baseline"))),
        "coherence": abs(_safe_float(report.get("no_coherence", {}).get("delta_from_baseline"))),
        "contamination": abs(_safe_float(report.get("no_contamination", {}).get("delta_from_baseline"))),
        "pure_gap": abs(_safe_float(report.get("pure_input", {}).get("delta_from_baseline"))),
    }

    dominant = max(deltas, key=deltas.get)
    sorted_keys = sorted(deltas, key=deltas.get, reverse=True)
    secondary = sorted_keys[1] if len(sorted_keys) > 1 else dominant

    interpretations: List[str] = []
    if deltas["contamination"] > 0.15:
        interpretations.append("当前低连接主要由内部状态驱动")
    if deltas["experience"] > 0.05:
        interpretations.append("历史经验显著影响当前感知")
    if deltas["coherence"] > 0.1:
        interpretations.append("时间结构放大效应明显")
    if deltas["pure_gap"] > 0.2:
        conn_pure = _safe_float(report.get("pure_input", {}).get("connection_depth"), 0.0)
        if conn_pure > 0.4:
            interpretations.append("外部交互本身质量中等偏上")
        else:
            interpretations.append("外部交互本身质量偏低")

    no_contam_conn = _safe_float(report.get("no_contamination", {}).get("connection_depth"), 0.0)
    if no_contam_conn > baseline_conn + 0.1:
        interpretations.append("系统存在负向自强化趋势")

    return {
        "dominant_distortion": dominant,
        "secondary": secondary,
        "interpretations": interpretations,
    }
