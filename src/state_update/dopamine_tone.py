"""
dopamine_tone.py — 多巴胺基调更新引擎（v11.x）

闭环核心：将 prediction_error 反向连接到驱动力系统。

设计原则：
    - 全程无 if-else，用 max(0, x) 和 clamp 实现条件逻辑
    - 惊喜（负向预测误差）→ dopamine_tone 上升，衰减慢
    - 失望（正向预测误差）→ dopamine_tone 下降，衰减快
    - 每 tick 自然向 0.5 回归

三个关键改进（v11.x 迭代版）：
    1. EMA 平滑 prediction_error，降低噪声，避免系统"情绪化"
    2. 初期空白状态保护：规则少时降低学习率 + 加快回归
    3. 多因子耦合：boredom_futility 同时受 stress + somatic_tone 调制

接口：
    compute_dopamine_tone_delta(
        prediction_error: float,   # Step 8.3 输出，负→惊喜，正→失望
        entity: EntityCore,
        idle_seconds: float,
        param_snapshot: Any,
        alpha: float = 0.3,        # EMA 平滑系数
    ) -> float: delta

    compute_boredom_futility_delta(
        current_boredom_futility: float,
        dopamine_tone: float,
        stress: float,
        somatic_tone: float,
        idle_seconds: float,
        param_snapshot: Any,
    ) -> float: delta
"""

from __future__ import annotations

from typing import Any


# ============================================================================
# 辅助
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
# 多巴胺基调更新
# ============================================================================


def compute_dopamine_tone_delta(
    prediction_error: float,
    entity: Any,
    idle_seconds: float,
    param_snapshot: Any,
    alpha: float = 0.3,
) -> float:
    """
    多巴胺基调（dopamine_tone）更新。

    公式：
        Step 1: EMA 平滑 prediction_error（降噪）
        Step 2: 初期保护（规则少时降低学习率）
        Step 3: 惊喜 / 失望信号提取（max(0, x) 实现条件）
        Step 4: 信号强度 × 系数 = delta
        Step 5: 动态回归（初期快，成熟后慢）

    参数：
        prediction_error : 世界模型预测误差，负→惊喜，正→失望
        entity          : EntityCore 实例（用于读写 _dopamine_pe_smoothed）
        idle_seconds    : 距离上次更新的秒数
        param_snapshot  : 参数快照
        alpha           : EMA 平滑系数，0.3 ≈ 3 轮有效窗口

    返回：
        dopamine_tone 的变化量（delta）
    """
    # ---- Step 1: EMA 平滑 prediction_error ----
    prev_smoothed = _safe_float(getattr(entity, "_dopamine_pe_smoothed", 0.0), 0.0)
    smoothed_error = alpha * prediction_error + (1.0 - alpha) * prev_smoothed
    entity._dopamine_pe_smoothed = smoothed_error

    # ---- Step 2: 初期保护系数 ----
    # 系统早期规则少，prediction_error 波动剧烈 → 降低学习率
    wm_rules = getattr(entity, "wm_rules", [])
    rule_count = len(wm_rules) if wm_rules else 0
    age_factor = min(1.0, rule_count / 20.0)  # 规则 < 20 时 age_factor < 1.0

    # ---- Step 3: 连续信号提取（无 if-else）----
    # 惊喜 = 负向预测误差（模型高估，真实结果更好）
    positive_signal = max(0.0, -smoothed_error)
    # 失望 = 正向预测误差（模型低估，真实结果更差）
    negative_signal = max(0.0, smoothed_error)

    # ---- Step 4: 受 age_factor 调制后的 boost / penalty ----
    # 基准系数（成熟期）
    boost_k   = _get_param(param_snapshot, "dopamine.positive_boost_k",   0.08)
    penalty_k = _get_param(param_snapshot, "dopamine.negative_penalty_k", 0.20)
    # 初期学习率折扣：age_factor 小 → 系数小（规则少时波动大）
    effective_boost   = boost_k   * (0.2 + age_factor * 0.8)
    effective_penalty = penalty_k * (0.2 + age_factor * 0.8)

    positive_boost   = positive_signal * effective_boost
    negative_penalty = negative_signal * effective_penalty

    # ---- Step 5: 动态回归速率 ----
    # 初期（age_factor 低）→ 回归速率更高 → 更快速回到 baseline
    base_regression_rate = _get_param(param_snapshot, "dopamine.regression_rate", 0.002)
    regression_rate = base_regression_rate + (1.0 - age_factor) * 0.008
    # 基准值 0.5，向其回归
    current_tone = _safe_float(getattr(entity, "dopamine_tone", 0.5), 0.5)
    regression = (0.5 - current_tone) * regression_rate * idle_seconds / 60.0

    return positive_boost - negative_penalty + regression


# ============================================================================
# boredom_futility 多因子耦合更新
# ============================================================================


def compute_boredom_futility_delta(
    current_boredom_futility: float,
    dopamine_tone: float,
    stress: float,
    somatic_tone: float,
    idle_seconds: float,
    param_snapshot: Any,
) -> float:
    """
    boredom_futility（徒劳性倦怠）积累速度计算。

    多因子叠加（都是加法，不是乘法，方向由符号决定）：
        dopamine_tone : 低时促进积累（连续乘数调制积累速率）
        stress        : 高时促进积累（直接加法叠加）
        somatic_tone  : 负时促进积累（max(0, -somatic_tone) 提取负面强度）

    无 if-else，全程连续函数。

    参数：
        current_boredom_futility : 当前值 [0, 1]
        dopamine_tone           : 多巴胺基调 [0, 1]，基准 0.5
        stress                  : 当前 stress 值 [0, 1]
        somatic_tone            : 躯体基调 [-1, 1]
        idle_seconds            : 距上次更新的秒数
        param_snapshot          : 参数快照

    返回：
        boredom_futility 的变化量
    """
    dt = idle_seconds / 60.0  # 标准化到分钟

    # dopamine_tone 调制积累速率（倍率）
    # dopamine_tone=1.0 → rate=0.5（高多巴胺，不容易倦怠）
    # dopamine_tone=0.0 → rate=1.0（低多巴胺，容易倦怠）
    futility_rate = 1.0 - dopamine_tone * 0.5

    # 基础积累（受多巴胺调制）
    base_k = _get_param(param_snapshot, "boredom_futility.base_k", 0.003)
    base_delta = futility_rate * current_boredom_futility * base_k * dt

    # stress 加速度（stress 高 → 倦怠更快）
    stress_k = _get_param(param_snapshot, "boredom_futility.stress_k", 0.01)
    stress_delta = stress * stress_k * dt

    # 负面体感加速度（somatic_tone 负 → max 提取强度）
    somatic_k = _get_param(param_snapshot, "boredom_futility.somatic_k", 0.005)
    somatic_negative = max(0.0, -somatic_tone)  # [-1,1] → [0,1]
    somatic_delta = somatic_negative * somatic_k * dt

    # 基础倦怠积累（独立于现有 futility 值）
    natural_k = _get_param(param_snapshot, "boredom_futility.natural_k", 0.0002)
    natural_delta = natural_k * dt

    return base_delta + stress_delta + somatic_delta + natural_delta


# ============================================================================
# 测试入口
# ============================================================================

if __name__ == "__main__":
    print("=" * 64)
    print("dopamine_tone — 单元测试")
    print("=" * 64)

    class MockEntity:
        def __init__(self):
            self.wm_rules = []
            self.dopamine_tone = 0.5
            self._dopamine_pe_smoothed = 0.0

    params = {}

    def make_entity(rules: int = 0, tone: float = 0.5) -> MockEntity:
        e = MockEntity()
        e.wm_rules = list(range(rules)) if rules else []
        e.dopamine_tone = tone
        return e

    # T1: 惊喜（负向预测误差）→ dopamine_tone 上升
    e1 = make_entity(rules=20, tone=0.5)
    delta1 = compute_dopamine_tone_delta(-0.5, e1, 60.0, params)
    ok1 = delta1 > 0
    print(f"  {'✓' if ok1 else '✗'} T1 惊喜(-0.5) → delta={delta1:+.4f}（应 > 0）")

    # T2: 失望（正向预测误差）→ dopamine_tone 下降
    e2 = make_entity(rules=20, tone=0.5)
    delta2 = compute_dopamine_tone_delta(0.5, e2, 60.0, params)
    ok2 = delta2 < 0
    print(f"  {'✓' if ok2 else '✗'} T2 失望(+0.5) → delta={delta2:+.4f}（应 < 0）")

    # T3: EMA 平滑（连续惊喜 → 累积）
    e3 = make_entity(rules=20, tone=0.5)
    for _ in range(5):
        compute_dopamine_tone_delta(-0.3, e3, 60.0, params)
    ok3 = 0.3 < e3._dopamine_pe_smoothed < -0.1  # EMA 后应显著平滑
    print(f"  {'✓' if ok3 else '✗'} T3 EMA 平滑: raw=-0.3×5, smoothed={e3._dopamine_pe_smoothed:+.4f}")

    # T4: 初期保护（规则少 → 学习率低）
    e4_young = make_entity(rules=0, tone=0.5)
    e4_mature = make_entity(rules=20, tone=0.5)
    d4_young   = compute_dopamine_tone_delta(-0.5, e4_young, 60.0, params)
    d4_mature  = compute_dopamine_tone_delta(-0.5, e4_mature, 60.0, params)
    ok4 = abs(d4_young) < abs(d4_mature)
    print(f"  {'✓' if ok4 else '✗'} T4 初期保护: young={d4_young:+.4f} < mature={d4_mature:+.4f}")

    # T5: 自然回归（无信号 → 向 0.5 回归）
    e5 = make_entity(rules=20, tone=0.7)
    delta5 = compute_dopamine_tone_delta(0.0, e5, 60.0, params)
    ok5 = delta5 < 0  # tone > 0.5 时应被拉回
    print(f"  {'✓' if ok5 else '✗'} T5 自然回归: tone=0.7 → delta={delta5:+.4f}（应 < 0）")

    # T6: boredom_futility — 高多巴胺抑制积累
    delta6_high = compute_boredom_futility_delta(0.3, 0.9, 0.3, 0.0, 60.0, params)
    delta6_low  = compute_boredom_futility_delta(0.3, 0.1, 0.3, 0.0, 60.0, params)
    ok6 = delta6_high < delta6_low
    print(f"  {'✓' if ok6 else '✗'} T6 多巴胺抑制: high={delta6_high:+.4f} < low={delta6_low:+.4f}")

    # T7: boredom_futility — stress 促进积累
    delta7_high_stress = compute_boredom_futility_delta(0.3, 0.5, 0.8, 0.0, 60.0, params)
    delta7_low_stress  = compute_boredom_futility_delta(0.3, 0.5, 0.1, 0.0, 60.0, params)
    ok7 = delta7_high_stress > delta7_low_stress
    print(f"  {'✓' if ok7 else '✗'} T7 stress 促进: high_stress={delta7_high_stress:+.4f} > low={delta7_low_stress:+.4f}")

    # T8: boredom_futility — 负面 somatic 促进积累
    delta8_neg = compute_boredom_futility_delta(0.3, 0.5, 0.3, -0.5, 60.0, params)
    delta8_neu = compute_boredom_futility_delta(0.3, 0.5, 0.3,  0.0, 60.0, params)
    ok8 = delta8_neg > delta8_neu
    print(f"  {'✓' if ok8 else '✗'} T8 负面 somatic: tone=-0.5→{delta8_neg:+.4f} > tone=0→{delta8_neu:+.4f}")

    # T9: boredom_futility — 已有 futility 越高积累越快
    delta9_high_f = compute_boredom_futility_delta(0.8, 0.5, 0.3, 0.0, 60.0, params)
    delta9_low_f  = compute_boredom_futility_delta(0.1, 0.5, 0.3, 0.0, 60.0, params)
    ok9 = delta9_high_f > delta9_low_f
    print(f"  {'✓' if ok9 else '✗'} T9 高 futility 积累更快: 0.8→{delta9_high_f:+.4f} > 0.1→{delta9_low_f:+.4f}")

    print(f"\n结果: {'全部通过 ✓' if all([ok1,ok2,ok3,ok4,ok5,ok6,ok7,ok8,ok9]) else '部分失败 ✗'}")
    print("=" * 64)
