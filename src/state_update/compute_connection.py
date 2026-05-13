"""
compute_connection.py — connection_depth 计算引擎（v3.0 + v3.5a/b/c）

四个层级联合计算：
    v3.0  : connection_depth 加权公式（三因子）
    v3.5a : 权重从参数快照读取（实例差异化）
    v3.5b : 经验偏移从 memory_context 检索（正负双向）
    v3.5c : coherence 短期调制（含负向阻尼）

核心接口：
    compute_connection_depth(
        prediction_error,         # Step 8.3 输出
        somatic_tone_delta,        # Step 0 → Step 8.05 的变化量
        tension_level,            # emerge_behavior 输出
        memory_context,           # EntityState.memory_context（最近 N 条）
        recent_deltas,           # recent_deltas 缓存（deque）
        loneliness,               # 当前 loneliness 值（用于负向阻尼）
        param_snapshot,          # 参数快照
    ) → (connection_depth_effective, connection_signature)

    compute_loneliness_target(
        loneliness,               # 当前 loneliness 值
        connection_depth_effective, # 已调制的 connection_depth
        silence_duration,          # 距上次社交输入的秒数
        social_input_present,       # 本轮是否有社交输入
        param_snapshot,
    ) → target_loneliness
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

# ============================================================================
# 辅助函数
# ============================================================================

def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _get_param(p: Any, key: str, default: float) -> float:
    """从参数快照读取参数（支持 dict 和 ParameterSnapshot）。"""
    if p is None:
        return default
    if hasattr(p, "get"):
        v = p.get(key)
        if v is not None:
            return float(v)
    return default


# ============================================================================
# v3.0 / v3.5a：somatic_tone_delta_factor 映射
# ============================================================================

def _somatic_delta_to_factor(somatic_tone_delta: float) -> float:
    """
    将 somatic_tone 的本轮变化量映射为 connection_depth 的因子。

    查表插值（连续映射，无 if-else）：
        delta >  0.1  → 1.0（正面松动）
        delta ∈ [-0.1, 0.1] → 0.5（无变化）
        delta < -0.1  → -0.5（负面收紧）

    返回值 ∈ [-0.5, 1.0]
    """
    x_anchors = [-1.0, -0.1, 0.1, 1.0]
    y_anchors = [-0.5, -0.5, 0.5, 1.0]

    if somatic_tone_delta <= x_anchors[0]:
        return y_anchors[0]
    if somatic_tone_delta >= x_anchors[-1]:
        return y_anchors[-1]

    for i in range(len(x_anchors) - 1):
        if x_anchors[i] <= somatic_tone_delta <= x_anchors[i + 1]:
            t = (somatic_tone_delta - x_anchors[i]) / (x_anchors[i + 1] - x_anchors[i])
            return y_anchors[i] + t * (y_anchors[i + 1] - y_anchors[i])
    return 0.5  # fallback


# ============================================================================
# v3.0 / v3.5a：connection_depth 基础公式
# ============================================================================

def _compute_base_connection_depth(
    prediction_error: float,
    somatic_tone_delta: float,
    tension_level: float,
    param_snapshot: Any,
) -> float:
    """
    connection_depth 基础公式（v3.0 + v3.5a 权重）。

    connection_depth = (
        w_prediction * (1 - prediction_error) +
        w_somatic    * somatic_factor +
        w_tension    * (1 - tension_level)
    ) / (w_prediction + w_somatic + w_tension)
    """
    w_pred    = _get_param(param_snapshot, "connection.w_prediction", 1.0)
    w_som     = _get_param(param_snapshot, "connection.w_somatic",    1.0)
    w_tension = _get_param(param_snapshot, "connection.w_tension",   1.0)

    somatic_factor = _somatic_delta_to_factor(somatic_tone_delta)

    numerator = (
        w_pred    * (1.0 - prediction_error) +
        w_som     * somatic_factor +
        w_tension * (1.0 - tension_level)
    )
    denominator = w_pred + w_som + w_tension
    return numerator / denominator  # 理论上 ∈ [-0.5, 1.0]


# ============================================================================
# v3.0+ 扩展版（供观测层 trace 使用）
# ============================================================================

def compute_connection_depth_ex(
    prediction_error: float,
    somatic_tone_delta: float,
    tension_level: float,
    memory_context: Optional[List[Dict[str, Any]]],
    recent_deltas: Any,
    loneliness: float,
    param_snapshot: Any,
    coherence_meta: float = 0.5,
) -> tuple[
    float,
    Dict[str, float],
    Dict[str, Any],
]:
    """
    完整版 connection_depth 计算，暴露所有中间值（供观测层使用）。

    返回 (connection_depth_effective, connection_signature, intermediates_dict)。
    """
    if memory_context is None:
        memory_context = []

    w_pred    = _get_param(param_snapshot, "connection.w_prediction", 1.0)
    w_som     = _get_param(param_snapshot, "connection.w_somatic",    1.0)
    w_tension = _get_param(param_snapshot, "connection.w_tension",   1.0)

    somatic_factor = _somatic_delta_to_factor(somatic_tone_delta)
    base_depth = _compute_base_connection_depth(
        prediction_error, somatic_tone_delta, tension_level, param_snapshot
    )

    signature = {
        "prediction": 1.0 - prediction_error,
        "somatic":   somatic_factor,
        "tension":   1.0 - tension_level,
    }

    experience_bias, experience_detail = _compute_experience_bias_ex(
        prediction_error, somatic_tone_delta, tension_level,
        memory_context, param_snapshot
    )
    depth_after_bias = base_depth + experience_bias

    from .compute_coherence import compute_final_coherence
    coherence = compute_final_coherence(recent_deltas)

    connection_depth_effective, coherence_mode, coherence_factor = _apply_coherence_modulation(
        connection_depth=depth_after_bias,
        coherence=coherence,
        loneliness=loneliness,
        param_snapshot=param_snapshot,
    )

    damping_active = connection_depth_effective < 0
    damping_factor = 1.0
    if damping_active:
        damping_scale = _get_param(param_snapshot, "connection.damping_scale", 0.30)
        damping_floor = _get_param(param_snapshot, "connection.negative_damping_floor", 0.70)
        damping_factor = max(damping_floor, 1.0 - (loneliness * damping_scale))

    intermediates = {
        "base_connection_depth": base_depth,
        "w_prediction": w_pred,
        "w_somatic": w_som,
        "w_tension": w_tension,
        "somatic_factor": somatic_factor,
        "prediction_factor": 1.0 - prediction_error,
        "tension_factor": 1.0 - tension_level,
        "experience_bias": experience_bias,
        "depth_after_bias": depth_after_bias,
        "coherence_raw": coherence,
        "coherence_mode": coherence_mode,
        "coherence_factor": coherence_factor,
        "damping_active": damping_active,
        "damping_factor": damping_factor,
        "loneliness_at_time": loneliness,
        "factor_overlap_with_loneliness": {
            "prediction": False,
            "somatic": True,
            "tension": True,
        },
        "experience_detail": experience_detail,
    }

    return connection_depth_effective, signature, intermediates


def _compute_experience_bias_ex(
    prediction_error: float,
    somatic_tone_delta: float,
    tension_level: float,
    memory_context: List[Dict[str, Any]],
    param_snapshot: Any,
) -> tuple[float, Dict[str, Any]]:
    """
    经验偏移详细版（供观测层使用）。

    返回 (experience_bias, detail_dict)。
    """
    if not memory_context:
        return 0.0, {
            "positive_similarity": 0.0,
            "negative_similarity": 0.0,
            "bias": 0.0,
            "positive_episodes_count": 0,
            "negative_episodes_count": 0,
        }

    positive_threshold = _get_param(param_snapshot, "connection.positive_threshold", 0.10)
    negative_threshold = _get_param(param_snapshot, "connection.negative_threshold", 0.10)
    positive_strength  = _get_param(param_snapshot, "connection.positive_bias_strength", 0.05)
    negative_strength  = _get_param(param_snapshot, "connection.negative_bias_strength", 0.02)

    current_vec = _build_context_vector(prediction_error, somatic_tone_delta, tension_level)

    positive_bias = 0.0
    max_pos_sim = 0.0
    pos_count = 0
    for ep in memory_context:
        change = _safe_float(ep.get("loneliness_change"), 0.0)
        if change < -positive_threshold:
            sig = ep.get("signature", {})
            if not sig:
                continue
            ep_vec = (
                _safe_float(sig.get("prediction"), 0.5),
                _safe_float(sig.get("somatic"), 0.0),
                _safe_float(sig.get("tension"), 0.5),
            )
            sim = _cosine_similarity(current_vec, ep_vec)
            max_pos_sim = max(max_pos_sim, sim)
            positive_bias = max(positive_bias, sim * positive_strength)
            pos_count += 1

    negative_bias = 0.0
    max_neg_sim = 0.0
    neg_count = 0
    for ep in memory_context:
        change = _safe_float(ep.get("loneliness_change"), 0.0)
        if change > negative_threshold:
            sig = ep.get("signature", {})
            if not sig:
                continue
            ep_vec = (
                _safe_float(sig.get("prediction"), 0.5),
                _safe_float(sig.get("somatic"), 0.0),
                _safe_float(sig.get("tension"), 0.5),
            )
            sim = _cosine_similarity(current_vec, ep_vec)
            max_neg_sim = max(max_neg_sim, sim)
            negative_bias = max(negative_bias, sim * negative_strength)
            neg_count += 1

    bias = positive_bias - negative_bias
    return bias, {
        "positive_similarity": max_pos_sim,
        "negative_similarity": max_neg_sim,
        "bias": bias,
        "positive_episodes_count": pos_count,
        "negative_episodes_count": neg_count,
    }


# ============================================================================
# v3.5b：经验偏移（余弦相似度）
# ============================================================================

def _cosine_similarity(a: tuple, b: tuple) -> float:
    """计算两个三维向量的余弦相似度。"""
    dot = a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
    norm_a = math.sqrt(a[0] ** 2 + a[1] ** 2 + a[2] ** 2) + 1e-9
    norm_b = math.sqrt(b[0] ** 2 + b[1] ** 2 + b[2] ** 2) + 1e-9
    return dot / (norm_a * norm_b)


def _build_context_vector(
    prediction_error: float,
    somatic_tone_delta: float,
    tension_level: float,
) -> tuple:
    """从当前状态构建三维上下文向量。"""
    somatic_factor = _somatic_delta_to_factor(somatic_tone_delta)
    return (
        1.0 - prediction_error,  # 期望落差
        somatic_factor,          # 体感变化因子
        1.0 - tension_level,    # 拮抗张力
    )


def _compute_experience_bias(
    prediction_error: float,
    somatic_tone_delta: float,
    tension_level: float,
    memory_context: List[Dict[str, Any]],
    param_snapshot: Any,
) -> float:
    """
    从 memory_context 检索相似历史经验，计算偏移量。

    正向偏移（loneliness 显著下降）→ connection_depth ↑
    负向偏移（loneliness 显著上升）→ connection_depth ↓

    正偏移强度（0.05）> 负偏移强度（0.02）。
    """
    if not memory_context:
        return 0.0

    positive_threshold = _get_param(param_snapshot, "connection.positive_threshold", 0.10)
    negative_threshold = _get_param(param_snapshot, "connection.negative_threshold", 0.10)
    positive_strength  = _get_param(param_snapshot, "connection.positive_bias_strength", 0.05)
    negative_strength  = _get_param(param_snapshot, "connection.negative_bias_strength", 0.02)

    current_vec = _build_context_vector(prediction_error, somatic_tone_delta, tension_level)

    positive_bias = 0.0
    for ep in memory_context:
        change = _safe_float(ep.get("loneliness_change"), 0.0)
        if change < -positive_threshold:
            sig = ep.get("signature", {})
            if not sig:
                continue
            ep_vec = (
                _safe_float(sig.get("prediction"), 0.5),
                _safe_float(sig.get("somatic"), 0.0),
                _safe_float(sig.get("tension"), 0.5),
            )
            sim = _cosine_similarity(current_vec, ep_vec)
            positive_bias = max(positive_bias, sim * positive_strength)

    negative_bias = 0.0
    for ep in memory_context:
        change = _safe_float(ep.get("loneliness_change"), 0.0)
        if change > negative_threshold:
            sig = ep.get("signature", {})
            if not sig:
                continue
            ep_vec = (
                _safe_float(sig.get("prediction"), 0.5),
                _safe_float(sig.get("somatic"), 0.0),
                _safe_float(sig.get("tension"), 0.5),
            )
            sim = _cosine_similarity(current_vec, ep_vec)
            negative_bias = max(negative_bias, sim * negative_strength)

    return positive_bias - negative_bias


# ============================================================================
# v3.5c：coherence 调制（含负向阻尼）
# ============================================================================

def _apply_coherence_modulation(
    connection_depth: float,
    coherence: float,
    loneliness: float,
    param_snapshot: Any,
) -> tuple[float, str, float]:
    """
    coherence 短期调制 connection_depth。

    高 coherence（>阈值） → 放大（amplify）
    低 coherence（<阈值） → 衰减（attenuate）
    connection_depth < 0 且 loneliness 高 → 负向阻尼（减弱负向反应）

    返回 (connection_depth_effective, mode, factor)：
        connection_depth_effective ∈ [-1, 1]
        mode  ∈ {"amplify", "attenuate", "none"}
        factor: 本轮实际乘数（不含阻尼）
    """
    high_thresh = _get_param(param_snapshot, "connection.coherence_high_threshold", 0.70)
    low_thresh  = _get_param(param_snapshot, "connection.coherence_low_threshold",  0.30)
    amplify     = _get_param(param_snapshot, "connection.coherence_amplify",      1.30)
    attenuate   = _get_param(param_snapshot, "connection.coherence_attenuate",    0.50)
    damping_floor = _get_param(param_snapshot, "connection.negative_damping_floor", 0.70)
    damping_scale = _get_param(param_snapshot, "connection.damping_scale",          0.30)

    cd = connection_depth
    mode = "none"
    factor = 1.0

    # coherence 调制
    if coherence > high_thresh:
        cd = cd * amplify
        mode = "amplify"
        factor = amplify
    elif coherence < low_thresh:
        cd = cd * attenuate
        mode = "attenuate"
        factor = attenuate

    # 负向阻尼
    damping_applied = 1.0
    if cd < 0:
        damping_applied = 1.0 - (loneliness * damping_scale)
        damping_applied = max(damping_applied, damping_floor)
        cd = cd * damping_applied

    return max(-1.0, min(1.0, cd)), mode, factor


# ============================================================================
# 主入口
# ============================================================================

def compute_connection_depth(
    prediction_error: float,
    somatic_tone_delta: float,
    tension_level: float,
    memory_context: Optional[List[Dict[str, Any]]],
    recent_deltas: Any,
    loneliness: float,
    param_snapshot: Any,
) -> tuple[float, Dict[str, float]]:
    """
    计算 connection_depth（含 v3.5a/b/c）。

    参数：
        prediction_error   : 预测误差（Step 8.3 输出，[0, 2]）
        somatic_tone_delta: somatic_tone 本轮变化量（Step 0 → Step 8.05）
        tension_level    : 拮抗张力（emerge_behavior 输出，[0, 1]）
        memory_context   : EntityState.memory_context（最近 N 条，用于经验偏移）
        recent_deltas   : recent_deltas 缓存（deque，用于 coherence 计算）
        loneliness      : 当前 loneliness 值（用于负向阻尼）
        param_snapshot  : 参数快照

    返回：
        (connection_depth_effective, connection_signature)
        connection_depth_effective ∈ [-1, 1]
        connection_signature 包含三因子原始值（供记录用）
    """
    if memory_context is None:
        memory_context = []

    # Step 1: base formula（v3.0 + v3.5a 权重）
    base_depth = _compute_base_connection_depth(
        prediction_error, somatic_tone_delta, tension_level, param_snapshot
    )

    # Step 2: somatic factor（供 signature 使用）
    somatic_factor = _somatic_delta_to_factor(somatic_tone_delta)

    # Step 3: connection_signature（三因子原始值，供记录）
    signature = {
        "prediction": 1.0 - prediction_error,
        "somatic":   somatic_factor,
        "tension":   1.0 - tension_level,
    }

    # Step 4: experience bias（v3.5b）
    experience_bias = _compute_experience_bias(
        prediction_error, somatic_tone_delta, tension_level,
        memory_context, param_snapshot
    )

    # Step 5: experience bias 叠加
    depth_after_bias = base_depth + experience_bias

    # Step 6: coherence 调制（v3.5c）
    from .compute_coherence import compute_final_coherence
    coherence = compute_final_coherence(recent_deltas)

    connection_depth_effective, coherence_mode, coherence_factor = _apply_coherence_modulation(
        connection_depth=depth_after_bias,
        coherence=coherence,
        loneliness=loneliness,
        param_snapshot=param_snapshot,
    )

    return connection_depth_effective, signature


# ============================================================================
# v3.0：loneliness target 计算
# ============================================================================

def _interpolate(x: float, x_anchors: list, y_anchors: list) -> float:
    """线性查表插值。"""
    if not x_anchors or len(x_anchors) < 2:
        return 0.0
    if x <= x_anchors[0]:
        return y_anchors[0]
    if x >= x_anchors[-1]:
        return y_anchors[-1]
    for i in range(len(x_anchors) - 1):
        if x_anchors[i] <= x <= x_anchors[i + 1]:
            t = (x - x_anchors[i]) / (x_anchors[i + 1] - x_anchors[i])
            return y_anchors[i] + t * (y_anchors[i + 1] - y_anchors[i])
    return y_anchors[-1]


def compute_loneliness_target(
    loneliness: float,
    connection_depth_effective: float,
    silence_duration: float,
    social_input_present: bool,
    param_snapshot: Any,
) -> float:
    """
    loneliness 目标值计算（v4.0：因果严格化）。

    物理定义：
        loneliness = 资源缺失 / 生存压力变量
        - 增加：沉默时长累积
        - 减少：真实外部他者输入
        - 无因果来源的衰减 = 系统替她解决情绪 → autonomy 破坏

    释放条件（唯一合法出口）：
        有真实用户输入 → 目标值 = 0（直接跳转）

    累积条件：
        无社交输入 → 目标值向 1.0 上升（随沉默时长加速）

    不允许：无因果来源的自然衰减。
    """
    if social_input_present:
        # 有真实外部他者输入 → 孤独被满足，目标归零
        return 0.0

    # 无社交输入 → 孤独持续累积
    # rise_rate: 每 tick 向 1.0 逼近的比例（值越大，孤独累积越快）
    # 默认 0.01 → 沉默 1 小时约到 0.45，2 小时约 0.70，3 小时约 0.85
    rise_rate = _get_param(param_snapshot, "connection.loneliness_rise_rate", 0.01)
    target = loneliness + (1.0 - loneliness) * rise_rate
    return max(0.0, min(1.0, target))


def compute_loneliness_target_ex(
    loneliness_core: float,
    loneliness_surface: float,
    connection_depth_effective: float,
    silence_duration: float,
    social_input_present: bool,
    active_exploration: bool = False,       # v11.4: 本轮是否在主动探索/创造
    param_snapshot: Any = None,
) -> tuple[float, float, Dict[str, Any]]:
    """
    loneliness 双通道目标值计算（v11.4）。

    物理模型：
        loneliness_core（真孤独）：
            - 只能被真人互动缓解（打折，不归零）
            - 沉默中缓慢累积
            - 不受探索/创造影响
        loneliness_surface（假孤独/代偿层）：
            - 沉默中快速累积
            - 探索/创造/搜索等向外行为可消耗
            - 假孤独耗尽而真孤独还高时 → 反扑（真孤独跳涨，假孤独重新充气）

    返回：
        (core_target, surface_target, intermediates)
    """
    rise_rate_core = _get_param(param_snapshot, "connection.loneliness_core_rise_rate", 0.003)
    rise_rate_surface = _get_param(param_snapshot, "connection.loneliness_surface_rise_rate", 0.012)
    surface_burn_rate = _get_param(param_snapshot, "connection.loneliness_surface_burn_rate", 0.05)
    rebound_threshold = _get_param(param_snapshot, "connection.loneliness_rebound_threshold", 0.5)
    rebound_spike = _get_param(param_snapshot, "connection.loneliness_rebound_spike", 0.12)
    rebound_refill = _get_param(param_snapshot, "connection.loneliness_rebound_refill", 0.3)

    core = loneliness_core
    surface = loneliness_surface
    events = []

    # === 通道 1: 真孤独 ===
    if social_input_present:
        # 真人互动 → 真孤独打折（不归零，尊重"孤独需要时间愈合"）
        relief = core * 0.4  # 一次互动消解 40% 真孤独
        core = max(0.0, core - relief)
        events.append(f"core_relief={relief:.3f}")
    else:
        # 沉默 → 真孤独缓慢累积
        core = min(1.0, core + (1.0 - core) * rise_rate_core)

    # === 通道 2: 假孤独（表面代偿）===
    if social_input_present:
        # 真人互动 → 假孤独归零（不需要代偿了）
        surface = 0.0
        events.append("surface_reset")
    elif active_exploration:
        # 主动探索/创造 → 消耗假孤独
        surface = max(0.0, surface - surface_burn_rate)
        events.append(f"surface_burn={surface_burn_rate}")
    else:
        # 沉默 → 假孤独快速累积
        surface = min(1.0, surface + (1.0 - surface) * rise_rate_surface)

    # === 通道 3: 反扑检测 ===
    # 假孤独耗到极低，但真孤独还很高 → 贷款到期，反扑
    if surface < 0.05 and core > rebound_threshold:
        rebound_amount = core * rebound_spike
        core = min(1.0, core + rebound_amount)
        # 假孤独重新充气——真实的孤独透过来了，不能再假装没事
        surface = core * rebound_refill
        events.append(f"REBOUND: core+{rebound_amount:.3f} surface_refill={surface:.3f}")

    intermediates = {
        "mode": "dual_channel_v11.4",
        "core_target": round(core, 4),
        "surface_target": round(surface, 4),
        "aggregate": round(min(1.0, core + surface), 4),
        "social_input": social_input_present,
        "active_exploration": active_exploration,
        "rebound_triggered": surface < 0.05 and core > rebound_threshold,
        "events": events,
    }

    return core, surface, intermediates


# ============================================================================
# 测试入口
# ============================================================================

if __name__ == "__main__":
    from collections import deque

    print("=" * 64)
    print("compute_connection — 单元测试")
    print("=" * 64)

    def make_params() -> dict:
        return {
            "connection.w_prediction": 1.0,
            "connection.w_somatic":    1.0,
            "connection.w_tension":   1.0,
            "connection.loneliness_recovery_rate":      0.35,
            "connection.loneliness_rejection_multiplier": 1.80,
            "connection.loneliness_connection_threshold": 0.10,
            "connection.release_lag":                     0.70,
            "connection.positive_bias_strength": 0.05,
            "connection.negative_bias_strength": 0.02,
            "connection.positive_threshold":   0.10,
            "connection.negative_threshold":    0.10,
            "connection.coherence_high_threshold": 0.70,
            "connection.coherence_low_threshold":  0.30,
            "connection.coherence_amplify":      1.30,
            "connection.coherence_attenuate":     0.50,
            "connection.negative_damping_floor": 0.70,
            "connection.damping_scale":          0.30,
        }

    params = make_params()

    # T1: base connection_depth（预测无误差 + 无体感变化 + 无张力）
    from .compute_coherence import compute_coherence
    r = deque([{"somatic_tone": 0.1}, {"somatic_tone": 0.1}])
    cd1, sig1 = compute_connection_depth(
        prediction_error=0.0,
        somatic_tone_delta=0.0,
        tension_level=0.0,
        memory_context=[],
        recent_deltas=r,
        loneliness=0.3,
        param_snapshot=params,
    )
    ok1 = cd1 > 0.5
    print(f"  {'✓' if ok1 else '✗'} T1 base connection_depth: {cd1:.4f}（应为高值）")

    # T2: negative connection_depth（高预测误差 + 负向体感变化）
    cd2, sig2 = compute_connection_depth(
        prediction_error=1.0,
        somatic_tone_delta=-0.3,
        tension_level=0.8,
        memory_context=[],
        recent_deltas=deque([{"somatic_tone": -0.1}]),
        loneliness=0.3,
        param_snapshot=params,
    )
    ok2 = cd2 < 0.0
    print(f"  {'✓' if ok2 else '✗'} T2 negative connection_depth: {cd2:.4f}（应为负）")

    # T3: coherence 放大（高 coherence）
    cd3, _ = compute_connection_depth(
        prediction_error=0.0,
        somatic_tone_delta=0.3,
        tension_level=0.0,
        memory_context=[],
        recent_deltas=deque([{"somatic_tone": 0.1}, {"somatic_tone": 0.2}, {"somatic_tone": 0.1}]),
        loneliness=0.3,
        param_snapshot=params,
    )
    cd3_no_coh, _ = compute_connection_depth(
        prediction_error=0.0,
        somatic_tone_delta=0.3,
        tension_level=0.0,
        memory_context=[],
        recent_deltas=deque([{"somatic_tone": 0.0}, {"somatic_tone": 0.0}]),
        loneliness=0.3,
        param_snapshot=params,
    )
    ok3 = cd3 > cd3_no_coh
    print(f"  {'✓' if ok3 else '✗'} T3 coherence amplify: {cd3:.4f} > {cd3_no_coh:.4f}（高coherence应更大）")

    # T4: negative damping（connection_depth<0 + high loneliness → 阻尼强）
    cd4, _ = compute_connection_depth(
        prediction_error=1.0,
        somatic_tone_delta=-0.3,
        tension_level=0.8,
        memory_context=[],
        recent_deltas=deque([{"somatic_tone": -0.1}]),
        loneliness=0.8,  # 高 loneliness → 强阻尼
        param_snapshot=params,
    )
    cd4_low_lon, _ = compute_connection_depth(
        prediction_error=1.0,
        somatic_tone_delta=-0.3,
        tension_level=0.8,
        memory_context=[],
        recent_deltas=deque([{"somatic_tone": -0.1}]),
        loneliness=0.1,  # 低 loneliness → 弱阻尼
        param_snapshot=params,
    )
    ok4 = abs(cd4) < abs(cd4_low_lon)
    print(f"  {'✓' if ok4 else '✗'} T4 negative damping: |{cd4:.4f}| < |{cd4_low_lon:.4f}|（高loneliness阻尼更强）")

    # T5: experience_bias 正面偏移
    pos_mem = [{"loneliness_change": -0.2, "signature": {"prediction": 0.8, "somatic": 0.5, "tension": 0.8}}]
    cd5_pos, _ = compute_connection_depth(
        prediction_error=0.2,
        somatic_tone_delta=0.2,
        tension_level=0.2,
        memory_context=pos_mem,
        recent_deltas=deque([]),
        loneliness=0.3,
        param_snapshot=params,
    )
    cd5_no_mem, _ = compute_connection_depth(
        prediction_error=0.2,
        somatic_tone_delta=0.2,
        tension_level=0.2,
        memory_context=[],
        recent_deltas=deque([]),
        loneliness=0.3,
        param_snapshot=params,
    )
    ok5 = cd5_pos > cd5_no_mem
    print(f"  {'✓' if ok5 else '✗'} T5 positive experience_bias: {cd5_pos:.4f} > {cd5_no_mem:.4f}")

    # T6: 有真实社交输入 → loneliness 目标归零
    t1 = compute_loneliness_target(0.5, 0.6, 3600.0, True, params)
    ok6 = t1 == 0.0
    print(f"  {'✓' if ok6 else '✗'} T6 有社交 → loneliness目标=0: {t1:.4f} == 0.0")

    # T7: 无社交输入 → loneliness 持续累积（目标 > 当前值）
    t2 = compute_loneliness_target(0.3, -0.5, 86400.0, False, params)
    ok7 = t2 > 0.3
    print(f"  {'✓' if ok7 else '✗'} T7 无社交 → loneliness累积: {t2:.4f} > 0.3")

    # T8: 有社交输入 → 目标 = 0（直接跳转，不平滑衰减）
    t3_no_social = compute_loneliness_target(0.4, -0.5, 86400.0, False, params)
    t3_with_social = compute_loneliness_target(0.4, 0.3, 86400.0, True, params)
    ok8 = t3_with_social == 0.0 and t3_no_social > 0.4
    print(f"  {'✓' if ok8 else '✗'} T8 有社交→0，无社交→累积: with={t3_with_social:.4f} without={t3_no_social:.4f}")

    print(f"\n结果: {'全部通过 ✓' if all([ok1,ok2,ok3,ok4,ok5,ok6,ok7,ok8]) else '部分失败 ✗'}")
    print("=" * 64)
