"""
oxytocin_signal.py — 催产素基调计算引擎（v11.x）

催产素是"连接成功后的温暖余韵"——在真实的正向社交体验后积累，
让社交不只是消除孤独，还能留下正向的基调残留。

机制设计：
    触发：connection_depth > 0 + 有社交输入 + somatic_tone_delta > 0（三门全开）
    上升：触发后 oxytocin_tone 上升，boost_k 控制幅度
    衰减：每 tick 向 0.5 回归，regression_rate 控制半衰期（约 230 分钟初始值）
    作用：
        - oxytocin_tone > 0.5 时，approach_social 驱动力被放大
        - oxytocin_tone > 0.5 时，boredom_futility 积累被抑制
        - oxytocin_tone > 0.5 时，loneliness_core 累积速度减缓

全程无 if-else 实现。

核心接口：
    compute_oxytocin_tone_delta(...) → float

校准提示：
    上线后观察"被接住后，oxytocin_tone 从峰值回到 0.5 需要多少轮对话"。
    若衰减太快（刚被接住就冷了）→ 调低 regression_rate
    若衰减太慢（一直沉浸在温暖里）→ 调高 regression_rate
    若触发过于稀少 → 将 connection_depth 门槛从 >0 调至 >0.05
"""

from __future__ import annotations

from typing import Any


def _get_param(p: Any, key: str, default: float) -> float:
    """从参数快照读取参数（支持 dict 和 ParameterSnapshot）。"""
    if p is None:
        return default
    if hasattr(p, "get"):
        v = p.get(key)
        if v is not None:
            return float(v)
    return default


def compute_oxytocin_tone_delta(
    connection_depth: float,
    has_social_input: bool,
    somatic_tone_delta: float,
    current_oxytocin_tone: float,
    idle_seconds: float,
    param_snapshot: Any = None,
) -> float:
    """
    计算催产素基调的变化量。

    参数：
        connection_depth    : connection_depth 有效值（Step 8.4 输出，[-1, 1]）
        has_social_input   : 本轮是否有真实社交输入（用于判断"连接成功"）
        somatic_tone_delta : somatic_tone 本轮变化量（Step 0 → Step 8.05）
        current_oxytocin_tone: 当前 oxytocin_tone 值（[0, 1]）
        idle_seconds       : 距上次更新的秒数（用于按时间缩放衰减量）
        param_snapshot     : 参数快照

    返回：
        oxytocin_tone_delta ∈ [-1, 1]

    无 if-else 实现：
        - 三门触发条件用 max(0, x) 实现
        - 上升量 = 触发量 × boost_k
        - 衰减量 = (0.5 - 当前值) × regression_rate × 时间因子
    """
    boost_k = _get_param(param_snapshot, "oxytocin.boost_k", 0.10)
    regression_rate = _get_param(param_snapshot, "oxytocin.regression_rate", 0.003)

    # 三门触发（全部用 max 实现，无 if-else）：
    #   connection_depth > 0    → 感到连接
    #   has_social_input       → 有真实互动
    #   somatic_tone_delta > 0 → 体感变暖
    trigger = (
        max(0.0, connection_depth)
        * max(0.0, float(bool(has_social_input)))
        * max(0.0, somatic_tone_delta)
    )
    boost = trigger * boost_k

    # 向 0.5 回归的衰减量（按 idle 时间缩放）
    # regression_rate=0.003 时，tone=0.8 且 idle=60s 时：
    #   回归量 = (0.8 - 0.5) * 0.003 * 1 = 0.0009（负向，tone 下降）
    #   回归量 = (0.3 - 0.5) * 0.003 * 1 = -0.0006（正向，tone 上升）
    # tone > 0.5 时 delta 负，tone < 0.5 时 delta 正
    time_factor = idle_seconds / 60.0
    regression = (current_oxytocin_tone - 0.5) * regression_rate * time_factor

    return boost - regression


def compute_oxytocin_tone_delta_ex(
    connection_depth: float,
    has_social_input: bool,
    somatic_tone_delta: float,
    current_oxytocin_tone: float,
    idle_seconds: float,
    param_snapshot: Any = None,
) -> tuple[float, dict[str, Any]]:
    """
    催产素基调变化量计算（扩展版，供观测层 trace 使用）。

    返回 (delta, intermediates)。
    """
    boost_k = _get_param(param_snapshot, "oxytocin.boost_k", 0.10)
    regression_rate = _get_param(param_snapshot, "oxytocin.regression_rate", 0.003)
    time_factor = idle_seconds / 60.0

    cd_gate    = max(0.0, connection_depth)
    input_gate = max(0.0, float(bool(has_social_input)))
    tone_gate  = max(0.0, somatic_tone_delta)

    trigger   = cd_gate * input_gate * tone_gate
    boost     = trigger * boost_k
    regression = (current_oxytocin_tone - 0.5) * regression_rate * time_factor
    delta     = boost - regression

    intermediates = {
        "connection_depth_input": round(connection_depth, 4),
        "has_social_input": has_social_input,
        "somatic_tone_delta": round(somatic_tone_delta, 4),
        "current_oxytocin_tone": round(current_oxytocin_tone, 4),
        "idle_seconds": round(idle_seconds, 1),
        "cd_gate": round(cd_gate, 4),
        "input_gate": round(input_gate, 4),
        "tone_gate": round(tone_gate, 4),
        "trigger": round(trigger, 4),
        "boost": round(boost, 4),
        "regression": round(regression, 4),
        "delta": round(delta, 4),
        "boost_k": boost_k,
        "regression_rate": regression_rate,
        "time_factor": round(time_factor, 3),
        "post_tone": round(max(0.0, min(1.0, current_oxytocin_tone + delta)), 4),
    }
    return delta, intermediates


# ============================================================================
# 单元测试
# ============================================================================

if __name__ == "__main__":
    params = {
        "oxytocin.boost_k": 0.10,
        "oxytocin.regression_rate": 0.003,
    }

    all_pass = [True]

    def check(name: str, cond: bool, got: str = "") -> None:
        ok = bool(cond)
        if not ok:
            all_pass[0] = False
        label = f"{name}: got={got}" if got else name
        print(f"  {'PASS' if ok else 'FAIL'} {label}")

    print("=" * 64)
    print("oxytocin_signal — unit tests")
    print("=" * 64)

    # T1: no trigger -> regression toward 0.5
    d1 = compute_oxytocin_tone_delta(0.0, True, 0.0, 0.8, 60.0, params)
    check("T1 no connection -> decays", d1 < 0, f"{d1:.4f} < 0")

    # T2: three gates open -> positive boost
    d2 = compute_oxytocin_tone_delta(0.5, True, 0.3, 0.5, 60.0, params)
    check("T2 three gates open -> rises", d2 > 0, f"{d2:.4f} > 0")

    # T3: no social input -> boost=0 (regression only)
    d3 = compute_oxytocin_tone_delta(0.5, False, 0.3, 0.7, 60.0, params)
    check("T3 no social -> no boost", d3 < 0, f"{d3:.4f} < 0")

    # T4: connection_depth <= 0 -> no boost
    d4 = compute_oxytocin_tone_delta(-0.3, True, 0.3, 0.7, 60.0, params)
    check("T4 negative connection -> no boost", d4 < 0, f"{d4:.4f} < 0")

    # T5: somatic_tone_delta <= 0 -> no boost
    d5 = compute_oxytocin_tone_delta(0.5, True, -0.2, 0.7, 60.0, params)
    check("T5 body cools -> no boost", d5 < 0, f"{d5:.4f} < 0")

    # T6: tone=0.5 (baseline) -> regression=0
    _, i6 = compute_oxytocin_tone_delta_ex(0.5, True, 0.3, 0.5, 60.0, params)
    check("T6 baseline -> regression=0", abs(i6["regression"]) < 1e-6, f"regression={i6['regression']:.6f}")

    # T7: intermediates complete
    _, i7 = compute_oxytocin_tone_delta_ex(0.3, True, 0.2, 0.6, 30.0, params)
    has_keys = all(k in i7 for k in ("boost", "regression", "trigger", "post_tone"))
    check("T7 intermediates complete", has_keys, str(sorted(i7.keys())))

    # T8: boost monotonic with connection_depth
    d8_low  = compute_oxytocin_tone_delta(0.1, True, 0.3, 0.5, 60.0, params)
    d8_high = compute_oxytocin_tone_delta(0.8, True, 0.3, 0.5, 60.0, params)
    check("T8 boost monotonic with cd", d8_high > d8_low, f"{d8_low:.4f} < {d8_high:.4f}")

    # T9: boost monotonic with somatic_tone_delta
    d9_low  = compute_oxytocin_tone_delta(0.5, True, 0.05, 0.5, 60.0, params)
    d9_high = compute_oxytocin_tone_delta(0.5, True, 0.5, 0.5, 60.0, params)
    check("T9 boost monotonic with tone_delta", d9_high > d9_low, f"{d9_low:.4f} < {d9_high:.4f}")

    print("=" * 64)
    print(f"All tests {'PASSED' if all_pass[0] else 'FAILED'}")
    print("=" * 64)
