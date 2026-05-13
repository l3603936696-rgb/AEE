"""
compute_coherence.py — coherence 状态一致性计算（v3.5c）

coherence：状态变化方向的一致性（不评判好坏）。

计算逻辑：
    - 从 recent_deltas 缓存中提取 somatic_tone 的变化方向
    - 计算相邻方向相同的比例（不含零变化）
    - 一直上升 → 1，一直下降 → 1，来回摇摆 → 0，静止 → 0.5（不足数据）

接口：
    compute_coherence(recent_deltas) → float [0, 1]
"""

from __future__ import annotations

from collections import deque
from typing import Any, Deque, Dict, List

# ============================================================================
# 常量（来自 parameters.py，可在模块内引用默认值）
# ============================================================================

# coherence 低值时返回的默认值（数据不足时）
COHERENCE_DEFAULT: float = 0.5

# somatic_tone 零变化的判定阈值
SOMATIC_CHANGE_DEADZONE: float = 0.01


# ============================================================================
# 核心计算
# ============================================================================

def compute_coherence(recent_deltas: Any) -> float:
    """
    从状态变化缓存计算 coherence（方向一致性）。

    参数：
        recent_deltas : deque/list of dict，或任何支持 len() 和下标访问的对象
                       每项包含 "somatic_tone": float（Δsomatic_tone）

    返回：
        float : coherence ∈ [0, 1]
        1.0   = 所有非零方向一致（全是正向或全是负向）
        0.0   = 方向完全对立（每次反转）
        0.5   = 数据不足（<2个有效方向）或全部静止
    """
    # 支持 deque / list / 任意序列
    if hasattr(recent_deltas, "__len__"):
        items = list(recent_deltas)
    else:
        items = []

    if len(items) < 2:
        return COHERENCE_DEFAULT

    # 提取有效方向
    directions: List[int] = []
    for d in items:
        if isinstance(d, dict):
            delta = float(d.get("somatic_tone", 0.0))
        else:
            continue  # 非字典项跳过

        if abs(delta) < SOMATIC_CHANGE_DEADZONE:
            continue  # 零变化不计入方向
        directions.append(1 if delta > 0 else -1)

    if len(directions) < 2:
        return COHERENCE_DEFAULT

    # 计算相邻方向一致的比例
    same_count = sum(
        1 for i in range(1, len(directions))
        if directions[i] == directions[i - 1]
    )
    total_transitions = len(directions) - 1
    return same_count / total_transitions  # ∈ [0, 1]


def append_delta(
    recent_deltas: Any,
    somatic_tone_delta: float,
    energy_delta: float,
    tension_delta: float,
    timestamp: float,
) -> None:
    """
    向 recent_deltas 追加本轮 delta。

    参数：
        recent_deltas : deque（maxlen 已设置，写入即自动丢弃最旧项）
        somatic_tone_delta : 本轮 somatic_tone 变化量（Step 11 新值 - Step 0 旧值）
        energy_delta       : 本轮 energy 变化量
        tension_delta     : 本轮 tension_level 变化量
        timestamp         : 当前时间戳
    """
    entry = {
        "somatic_tone": somatic_tone_delta,
        "energy": energy_delta,
        "tension": tension_delta,
        "timestamp": timestamp,
    }
    recent_deltas.append(entry)


# ============================================================================
# coherence_meta 接入（v1.0 元认知层）
# ============================================================================
# 元认知一致性：叙事预测验证是否成功（coherence_meta）
# 接入方式：悄悄混入 coherence_raw，不改变行为，只影响 stress 恢复
# 权重固定为 0.0（默认不接入）；开启需在参数系统中配置 coherence_meta_weight

COHERENCE_META_WEIGHT: float = 0.0  # 默认关闭，隐藏行为影响


def compute_final_coherence(
    recent_deltas: Any,
    coherence_meta: float = 0.5,
) -> float:
    """
    混合 coherence_raw（方向一致性）和 coherence_meta（元认知一致性）。

    权重 0.0 时，结果等价于 compute_coherence(recent_deltas)。

    参数：
        recent_deltas  : deque of dict（用于 compute_coherence）
        coherence_meta : [0, 1]，来自 SelfBodyMap.get_coherence_meta()

    返回：
        float : 最终 coherence ∈ [0, 1]
    """
    coherence_raw = compute_coherence(recent_deltas)
    return (
        coherence_raw * (1.0 - COHERENCE_META_WEIGHT)
        + coherence_meta * COHERENCE_META_WEIGHT
    )


# ============================================================================
# 测试入口
# ============================================================================

if __name__ == "__main__":
    from collections import deque

    print("=" * 64)
    print("compute_coherence — 单元测试")
    print("=" * 64)

    # T1: 数据不足
    r1 = deque([{"somatic_tone": 0.1}])
    ok1 = abs(compute_coherence(r1) - 0.5) < 1e-9
    print(f"  {'✓' if ok1 else '✗'} 数据不足 → 0.5: {compute_coherence(r1):.4f}")

    # T2: 全上升
    r2 = deque([{"somatic_tone": 0.1}, {"somatic_tone": 0.2}, {"somatic_tone": 0.15}])
    ok2 = abs(compute_coherence(r2) - 1.0) < 1e-9
    print(f"  {'✓' if ok2 else '✗'} 全上升 → 1.0: {compute_coherence(r2):.4f}")

    # T3: 全下降
    r3 = deque([{"somatic_tone": -0.1}, {"somatic_tone": -0.2}])
    ok3 = abs(compute_coherence(r3) - 1.0) < 1e-9
    print(f"  {'✓' if ok3 else '✗'} 全下降 → 1.0: {compute_coherence(r3):.4f}")

    # T4: 来回摇摆（up/down/up）
    r4 = deque([{"somatic_tone": 0.1}, {"somatic_tone": -0.2}, {"somatic_tone": 0.1}])
    ok4 = abs(compute_coherence(r4) - 0.0) < 1e-9
    print(f"  {'✓' if ok4 else '✗'} 来回摇摆 → 0.0: {compute_coherence(r4):.4f}")

    # T5: 零变化 + 方向混合（只计入有方向的）
    r5 = deque([{"somatic_tone": 0.0}, {"somatic_tone": 0.1}, {"somatic_tone": 0.2}])
    ok5 = abs(compute_coherence(r5) - 1.0) < 1e-9
    print(f"  {'✓' if ok5 else '✗'} 零变化不计入 → 1.0: {compute_coherence(r5):.4f}")

    # T6: 空队列
    r6 = deque()
    ok6 = abs(compute_coherence(r6) - 0.5) < 1e-9
    print(f"  {'✓' if ok6 else '✗'} 空队列 → 0.5: {compute_coherence(r6):.4f}")

    # T7: append_delta 正确写入
    r7: deque = deque(maxlen=3)
    append_delta(r7, 0.1, -0.05, 0.0, 1000.0)
    append_delta(r7, 0.2, -0.03, 0.0, 1001.0)
    ok7 = len(r7) == 2 and r7[0]["somatic_tone"] == 0.1
    print(f"  {'✓' if ok7 else '✗'} append_delta 写入: len={len(r7)}, first_somatic={r7[0]['somatic_tone']:.2f}")

    # T8: maxlen 自动丢弃旧项
    r8: deque = deque(maxlen=3)
    for i in range(5):
        append_delta(r8, float(i), 0.0, 0.0, float(i))
    ok8 = len(r8) == 3 and r8[0]["somatic_tone"] == 2.0
    print(f"  {'✓' if ok8 else '✗'} maxlen=3 自动丢弃: len={len(r8)}, first={r8[0]['somatic_tone']:.1f}")

    all_ok = all([ok1, ok2, ok3, ok4, ok5, ok6, ok7, ok8])
    print(f"\n结果: {'全部通过 ✓' if all_ok else '部分失败 ✗'}")
    print("=" * 64)
