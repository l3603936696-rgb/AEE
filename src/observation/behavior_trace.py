"""
behavior_trace.py — 单轮因果拆解、短期趋势、个体性剖面

不修改任何系统状态，只采集和计算。
"""

from __future__ import annotations

from collections import deque
from typing import Any, Deque, Dict, List, Optional


# ============================================================================
# 3.2 connection_trace
# ============================================================================

def build_connection_trace(
    tick: int,
    connection_depth_effective: float,
    connection_signature: Dict[str, float],
    intermediates: Dict[str, Any],
) -> Dict[str, Any]:
    """
    构造 connection_trace。

    参数全部来自 Step 8.4 的计算结果，采集后即凝固，不引用任何可变状态。
    """
    exp_detail = intermediates.get("experience_detail", {})

    return {
        "tick": tick,
        "base_components": {
            "prediction": intermediates.get("prediction_factor", 0.0),
            "somatic": intermediates.get("somatic_factor", 0.0),
            "tension": intermediates.get("tension_factor", 0.0),
            "weighted_sum": intermediates.get("base_connection_depth", 0.0),
            "w_prediction": intermediates.get("w_prediction", 1.0),
            "w_somatic": intermediates.get("w_somatic", 1.0),
            "w_tension": intermediates.get("w_tension", 1.0),
            "factor_overlap_with_loneliness": intermediates.get(
                "factor_overlap_with_loneliness",
                {"prediction": False, "somatic": True, "tension": True},
            ),
        },
        "experience": {
            "positive_similarity": exp_detail.get("positive_similarity", 0.0),
            "negative_similarity": exp_detail.get("negative_similarity", 0.0),
            "bias": exp_detail.get("bias", 0.0),
            "positive_episodes_count": exp_detail.get("positive_episodes_count", 0),
            "negative_episodes_count": exp_detail.get("negative_episodes_count", 0),
        },
        "coherence": {
            "raw_value": intermediates.get("coherence_raw", 0.5),
            "effective_value": connection_depth_effective,
            "mode": intermediates.get("coherence_mode", "none"),
            "factor": intermediates.get("coherence_factor", 1.0),
        },
        "damping": {
            "active": bool(intermediates.get("damping_active", False)),
            "factor": intermediates.get("damping_factor", 1.0),
            "loneliness_at_time": intermediates.get("loneliness_at_time", 0.0),
        },
        "final_connection_depth": connection_depth_effective,
        "signature": connection_signature,
    }


# ============================================================================
# 3.3 loneliness_trace
# ============================================================================

def build_loneliness_trace(
    tick: int,
    loneliness_before: float,
    loneliness_after: float,
    loneliness_target: Optional[float],
    recovery_component: float,
    accumulation_component: float,
    release_lag: float,
    reason: str,
) -> Dict[str, Any]:
    """
    构造 loneliness_trace。

    参数来自 Step 11（update_state 完成后）。
    """
    return {
        "tick": tick,
        "prev": loneliness_before,
        "recovery_component": recovery_component,
        "accumulation_component": accumulation_component,
        "target": loneliness_target,
        "release_lag": release_lag,
        "final": loneliness_after,
        "delta": loneliness_after - loneliness_before,
        "reason": reason,
    }


def _infer_loneliness_reason(
    recovery: float,
    accumulation: float,
    loneliness_before: float,
    loneliness_after: float,
    silence_duration: float,
    social_input_present: bool,
) -> str:
    """推断主导因素（用于 loneliness_trace.reason）。"""
    if social_input_present:
        return "recovery_dominant"

    delta = loneliness_after - loneliness_before

    if abs(delta) < 0.001:
        return "neutral"

    # 沉默很久但 loneliness 没涨 → recovery 主导
    if accumulation > 0.01 and delta <= 0.001 and recovery > accumulation:
        return "recovery_dominant"

    # 沉默期间涨了很多
    if accumulation > recovery:
        if silence_duration > 3600.0:
            return "silence_accumulation"
        return "accumulation_dominant"

    return "recovery_dominant"


# ============================================================================
# 3.4 短期趋势
# ============================================================================

def compute_trend(
    buffer: List[Dict[str, Any]],
    window: int = 10,
) -> Optional[Dict[str, Any]]:
    """
    从 observation_buffer 计算短期趋势。

    参数：
        buffer  : observation_buffer（deque/list of tick-dict）
        window  : 窗口大小（默认10）
    """
    if len(buffer) < window:
        return None

    recent = list(buffer)[-window:]

    conn_values = [t.get("connection_depth", t.get("connection_trace", {}).get("final_connection_depth", 0.0)) for t in recent]
    loneliness_values = [t.get("loneliness", t.get("loneliness_trace", {}).get("final", 0.0)) for t in recent]
    coherence_values = [t.get("connection_trace", {}).get("coherence", {}).get("raw_value", 0.5) for t in recent]
    exp_biases = [t.get("connection_trace", {}).get("experience", {}).get("bias", 0.0) for t in recent]

    # connection_depth 统计
    cd_mean = _mean(conn_values)
    cd_std = _std(conn_values)

    # loneliness 趋势（方向）
    if len(loneliness_values) >= 2:
        lon_diff = loneliness_values[-1] - loneliness_values[0]
        if lon_diff > 0.02:
            lon_trend = "increasing"
        elif lon_diff < -0.02:
            lon_trend = "decreasing"
        else:
            lon_trend = "stable"
    else:
        lon_trend = "stable"

    # coherence 趋势
    if len(coherence_values) >= 2:
        coh_diff = coherence_values[-1] - coherence_values[0]
        if coh_diff > 0.05:
            coh_trend = "increasing"
        elif coh_diff < -0.05:
            coh_trend = "decreasing"
        else:
            coh_trend = "stable"
    else:
        coh_trend = "stable"

    # 主导因子
    avg_exp = _mean(exp_biases)
    avg_coh = _mean(coherence_values)
    dominant = _dominant_factor(avg_exp, avg_coh)

    # 风险旗标
    risk_flags: List[str] = []
    neg_loop = all(
        t.get("connection_trace", {}).get("final_connection_depth", 0.0) < 0
        and t.get("connection_trace", {}).get("coherence", {}).get("raw_value", 0) > 0.7
        for t in recent[-3:]
    )
    if neg_loop:
        risk_flags.append("negative_loop")

    pos_loop = all(
        t.get("connection_trace", {}).get("final_connection_depth", 0.0) > 0.7
        and t.get("connection_trace", {}).get("coherence", {}).get("raw_value", 0) > 0.7
        for t in recent[-3:]
    )
    if pos_loop:
        risk_flags.append("positive_loop")

    # experience_lock: 连续5轮同向偏移
    if len(recent) >= 5:
        exp_deltas = [
            recent[i].get("connection_trace", {}).get("experience", {}).get("bias", 0.0)
            - recent[i - 1].get("connection_trace", {}).get("experience", {}).get("bias", 0.0)
            for i in range(1, min(5, len(recent)))
        ]
        if all(d > 0.001 for d in exp_deltas) or all(d < -0.001 for d in exp_deltas):
            risk_flags.append("experience_lock")

    return {
        "window": window,
        "connection_depth_mean": round(cd_mean, 4),
        "connection_depth_std": round(cd_std, 4),
        "loneliness_trend": lon_trend,
        "coherence_trend": coh_trend,
        "dominant_factor": dominant,
        "risk_flags": risk_flags,
    }


def _mean(values: List[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _std(values: List[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = _mean(values)
    variance = sum((v - m) ** 2 for v in values) / len(values)
    return variance ** 0.5


def _dominant_factor(avg_exp_bias: float, avg_coherence: float) -> str:
    """判断最近 window 轮的主导因子。"""
    if avg_exp_bias > 0.05 and avg_coherence < 0.6:
        return "experience_bias"
    if avg_coherence > 0.7 and abs(avg_exp_bias) < 0.05:
        return "coherence"
    if abs(avg_exp_bias) < 0.02 and avg_coherence < 0.5:
        return "base_input"
    return "mixed"


# ============================================================================
# 3.5 个体性剖面
# ============================================================================

def compute_profile(
    buffer: List[Dict[str, Any]],
    window: int = 50,
) -> Optional[Dict[str, Any]]:
    """
    从 observation_buffer 计算个体性剖面。

    参数：
        buffer  : observation_buffer
        window  : 窗口大小（默认50）
    """
    if len(buffer) < window:
        return None

    all_traces = [t["connection_trace"] for t in buffer if "connection_trace" in t]
    if not all_traces:
        return None

    pred_vals = [t.get("base_components", {}).get("prediction", 0.5) for t in all_traces]
    som_vals  = [t.get("base_components", {}).get("somatic", 0.0) for t in all_traces]
    tens_vals = [t.get("base_components", {}).get("tension", 0.5) for t in all_traces]

    pred_avg = _mean(pred_vals)
    som_avg  = _mean(som_vals)
    tens_avg = _mean(tens_vals)

    # 主导敏感度
    dominant_sens = "balanced"
    vals = {"prediction": pred_avg, "somatic": som_avg, "tension": tens_avg}
    top = max(vals, key=vals.get)
    if vals[top] - vals[min(vals, key=vals.get)] > 0.15:
        dominant_sens = top

    # bias 倾向
    exp_biases = [t.get("experience", {}).get("bias", 0.0) for t in all_traces]
    avg_bias = _mean(exp_biases)
    if avg_bias > 0.02:
        bias_tendency = "optimistic"
    elif avg_bias < -0.02:
        bias_tendency = "cautious"
    else:
        bias_tendency = "neutral"

    # coherence 模式
    coh_vals = [t.get("coherence", {}).get("raw_value", 0.5) for t in all_traces]
    coh_std = _std(coh_vals)
    if coh_std < 0.10:
        coherence_pattern = "high_stability"
    elif coh_std < 0.25:
        coherence_pattern = "moderate"
    else:
        coherence_pattern = "volatile"

    # loneliness 恢复速度（最近10轮有变化的 loneliness_delta）
    lon_deltas = [
        buffer[i].get("loneliness_trace", {}).get("delta", 0.0)
        for i in range(max(0, len(buffer) - 10), len(buffer))
        if "loneliness_trace" in buffer[i]
    ]
    if lon_deltas:
        avg_delta = _mean([abs(d) for d in lon_deltas])
        if avg_delta > 0.05:
            recovery_speed = "fast"
        elif avg_delta > 0.02:
            recovery_speed = "normal"
        else:
            recovery_speed = "slow"
    else:
        recovery_speed = "normal"

    # 风险状态（从最近5轮判断）
    recent5 = list(buffer)[-5:]
    neg_vals = [t.get("connection_trace", {}).get("final_connection_depth", 0.0) for t in recent5]
    if all(v < 0 for v in neg_vals):
        risk_state = "negative_loop"
    elif all(v > 0.7 for v in neg_vals):
        risk_state = "positive_loop"
    elif all(abs(neg_vals[i] - neg_vals[i - 1]) < 0.05 for i in range(1, len(neg_vals))):
        risk_state = "stable"
    else:
        risk_state = "diverging"

    return {
        "window": window,
        "sensitivity_profile": {
            "prediction_avg": round(pred_avg, 4),
            "somatic_avg": round(som_avg, 4),
            "tension_avg": round(tens_avg, 4),
            "dominant_sensitivity": dominant_sens,
        },
        "bias_tendency": bias_tendency,
        "coherence_pattern": coherence_pattern,
        "loneliness_recovery_speed": recovery_speed,
        "risk_state": risk_state,
    }


# ============================================================================
# 3.5 memory_trace — 双通道记忆检索归因（v2.0）
# ============================================================================


def build_memory_trace(
    mainline_result: Optional[Dict[str, Any]],
    branch_result: Optional[List[Dict[str, Any]]],
    entity_state: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    记录本轮记忆检索的完整信息，供行为剖析仪和反事实分析使用。

    参数：
        mainline_result : mainline_retrieval() 返回的结果字典
        branch_result   : branch_retrieval() 返回的浮出记忆列表
        entity_state    : EntityCore 实例（用于提取状态调制参数）

    返回：
        dict : 记忆检索归因记录
    """
    main_dict = {}
    if mainline_result and isinstance(mainline_result, dict):
        recalled = mainline_result.get("related_memories", []) or []
        main_dict = {
            "channel_type": "mainline",  # Patch 5：标注检索通道类型
            "query": mainline_result.get("query", ""),
            "recalled_count": len(recalled),
            "recent_summaries_count": len(mainline_result.get("recent_context", []) or []),
            "top_similarity": max(
                (getattr(ep, "importance", 0.0) for ep in recalled),
                default=0.0,
            ),
        }

    branch_dict = {}
    if branch_result and isinstance(branch_result, list):
        loneliness = float(getattr(entity_state, "loneliness", 0.0)) if entity_state else 0.0
        stress = float(getattr(entity_state, "stress", 0.0)) if entity_state else 0.0
        recent_deltas = getattr(entity_state, "recent_deltas", None) if entity_state else None

        def _compute_coherence(deltas):
            if not deltas:
                return 0.5
            try:
                vals = [abs(float(d.get("somatic_tone", 0.0))) for d in deltas]
                if not vals:
                    return 0.5
                mean = sum(vals) / len(vals)
                var = sum((v - mean) ** 2 for v in vals) / len(vals)
                return max(0.0, min(1.0, 1.0 / (1.0 + var * 10.0)))
            except Exception:
                return 0.5

        coherence = _compute_coherence(recent_deltas)

        from ..memory_retrieval.state_modulation import compute_state_sensitive_weight
        threshold_mod = compute_state_sensitive_weight(loneliness, stress, coherence)

        branch_dict = {
            "channel_type": "branch",  # Patch 5：标注检索通道类型
            "sampled_count": len(branch_result),
            "floated_count": len([m for m in branch_result if m.get("floated")]),
            "top_score": max((m.get("score", 0.0) for m in branch_result), default=0.0),
            "state_modulation": {
                "loneliness": round(loneliness, 3),
                "stress": round(stress, 3),
                "coherence": round(coherence, 3),
                "threshold_modifier": round(threshold_mod, 3),
            },
        }

    return {
        "mainline": main_dict if main_dict else None,
        "branch": branch_dict if branch_dict else None,
        "used_in_prompt": {
            "mainline_injected": main_dict.get("recalled_count", 0) > 0 or main_dict.get("recent_summaries_count", 0) > 0,
            "branch_injected": len(branch_result or []) > 0,
        },
    }


# ============================================================================
# 3.6 查询接口
# ============================================================================

def get_observation_summary(
    entity_state: Any,
) -> Dict[str, Any]:
    """
    供调试面板调用的聚合查询接口。

    参数：
        entity_state : EntityState 实例（含 observation_buffer）

    返回：
        {
            "latest_tick": int,
            "latest_connection_trace": dict,
            "latest_loneliness_trace": dict,
            "trend": dict | None,
            "profile": dict | None,
        }
    """
    buf = getattr(entity_state, "observation_buffer", None)
    if buf is None or len(buf) == 0:
        return {
            "latest_tick": getattr(entity_state, "tick", 0),
            "latest_connection_trace": {},
            "latest_loneliness_trace": {},
            "trend": None,
            "profile": None,
        }

    latest = buf[-1]

    trend = compute_trend(list(buf))
    profile = compute_profile(list(buf))

    return {
        "latest_tick": getattr(entity_state, "tick", 0),
        "latest_connection_trace": latest.get("connection_trace", {}),
        "latest_loneliness_trace": latest.get("loneliness_trace", {}),
        "trend": trend,
        "profile": profile,
    }
