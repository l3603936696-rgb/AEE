"""
State-Sensitive Weight Modulation — 状态敏感权重计算

根据实体当前状态（loneliness / stress / coherence）调制记忆浮出的阈值。
全部使用连续函数，无 if-else 阈值分支。
"""

from typing import Optional

# 默认参数
DEFAULT_STRESS_MOD: float = 0.30
DEFAULT_LONELINESS_MOD: float = 0.15
DEFAULT_COHERENCE_HIGH_THRESHOLD: float = 0.80
DEFAULT_COHERENCE_PENALTY: float = 0.10


def compute_state_sensitive_weight(
    loneliness: float,
    stress: float,
    coherence: float,
    *,
    stress_mod: float = DEFAULT_STRESS_MOD,
    loneliness_mod: float = DEFAULT_LONELINESS_MOD,
    coherence_high_thresh: float = DEFAULT_COHERENCE_HIGH_THRESHOLD,
    coherence_penalty: float = DEFAULT_COHERENCE_PENALTY,
) -> float:
    """
    根据当前状态计算记忆浮出的调制系数（阈值倍率）。

    调制逻辑：
        - stress 升高 → 阈值降低（更愿意回忆，更容易被打断）
        - loneliness 升高 → 阈值降低（渴望连接，主动检索相关记忆）
        - coherence 极高 → 阈值略微升高（状态稳定，不轻易被打断）

    参数：
        loneliness : 当前孤独感 [0, 1]
        stress    : 当前压力 [0, 1]
        coherence : 当前连贯性 [0, 1]

    返回：
        float : 阈值调制系数，范围 [0.45, 1.20]
            > 1.0 → 提高阈值，更难浮出
            < 1.0 → 降低阈值，更容易浮出
    """
    # 基准调制（从 1.0 开始）
    mod = 1.0

    # stress 升高 → 阈值降低（更容易浮出记忆）
    mod -= stress * stress_mod

    # loneliness 升高 → 阈值降低（渴望连接，主动回忆）
    mod -= loneliness * loneliness_mod

    # coherence 极高 → 阈值略微升高（稳定时不轻易被打断）
    if coherence > coherence_high_thresh:
        excess = coherence - coherence_high_thresh
        mod += excess * coherence_penalty

    # 钳制到安全范围（上下限）
    return max(0.45, min(1.20, mod))


def modulated_threshold(
    base_threshold: float,
    loneliness: float,
    stress: float,
    coherence: float,
    **kwargs,
) -> float:
    """
    计算调制后的浮出阈值。

    等价于：base_threshold * compute_state_sensitive_weight(...)
    """
    mod = compute_state_sensitive_weight(loneliness, stress, coherence, **kwargs)
    return base_threshold * mod


if __name__ == "__main__":
    print("=== 状态敏感调制测试 ===\n")

    test_cases = [
        ("基准状态",          {"loneliness": 0.2, "stress": 0.2, "coherence": 0.5}),
        ("高孤独",            {"loneliness": 0.8, "stress": 0.2, "coherence": 0.5}),
        ("高压力",            {"loneliness": 0.2, "stress": 0.8, "coherence": 0.5}),
        ("高连贯（稳定）",     {"loneliness": 0.2, "stress": 0.2, "coherence": 0.9}),
        ("高孤独+高压力",     {"loneliness": 0.8, "stress": 0.8, "coherence": 0.3}),
        ("全部高",            {"loneliness": 0.9, "stress": 0.9, "coherence": 0.9}),
        ("全部低",            {"loneliness": 0.0, "stress": 0.0, "coherence": 0.1}),
    ]

    base = 0.6
    print(f"基准阈值: {base}\n")
    for name, state in test_cases:
        w = compute_state_sensitive_weight(**state)
        t = modulated_threshold(base, **state)
        tag = "↓ 更容易浮出" if w < 1.0 else ("↑ 更难浮出" if w > 1.0 else "  无调制")
        print(f"  {name:20s}  mod={w:+.3f}  threshold={t:.3f}  {tag}")

    print("\n全部测试完成")
