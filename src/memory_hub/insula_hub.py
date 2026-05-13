"""
Insula Hub — 内脏感觉中枢

将外部/内部生理信号转化为 V4 决策系统可理解的躯体标记。

核心职责：
    - 读取 TetraMem 拓扑指标，降维为认知压力信号
    - 接收其他生理信号（疼痛、恶心、心率变异性等），映射为情绪-动机信号
    - 不直接参与裁决，输出标准 DriveSignal 供裁决层汇聚

核心原则：
    - 绝对禁止将原始拓扑指标（betti_numbers、persistent_entropy）直接传入裁决层
    - 转化结果必须是"感觉"而非"计算"
    - 纯函数，无定时器，无周期性逻辑
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional

from ..decision_system.submodules.base import DriveSignal


# ============================================================================
# 拓扑 → 认知压力 降维参数
# ============================================================================

# 拓扑熵超过此阈值时，触发"认知过载"AVOID 信号
TOPOLOGY_ENTROPY_THRESHOLD: float = 0.7

# 超出阈值的拓扑熵乘以此系数，映射到信号强度 [0, 1]
MEMORY_PRESSURE_AMPLIFIER: float = 2.5

# 拓扑熵在 [0.0, THRESHOLD] 区间内，对应强度 [0.0, 0.8] 的温和信号
TOPOLOGY_ENTROPY_SOFT_MAX: float = 0.5


# ============================================================================
# 核心降维函数
# ============================================================================

def calculate_memory_pressure_from_topology(topo_metrics) -> Optional[DriveSignal]:
    """
    从 TetraMem 拓扑指标降维为 V4 的认知压力信号。

    读取 TetraMem 拓扑，但转化为 V4 的多通道反馈信号。
    让实体"感觉"到记忆混乱，而不是"计算"出记忆混乱。

    参数：
        topo_metrics : TopoMetrics 对象（来自 tetramem_adapter.get_topology_metrics）
                     内部包含 topological_entropy、betti_numbers、persistent_entropy 等原始字段
                     这些字段仅在函数内部使用，绝不直接暴露给裁决层

    返回：
        DriveSignal | None :
            - signal_type : "avoid"（认知过载 → 回避高认知负荷行为）
            - strength   : 压力强度 [0.0, 1.0]
            - source     : "InsulaHub"
            - dimension  : "cognitive_overload"
            - intensity  : 原始未归一化强度（供调试用）

            当 topological_entropy <= TOPOLOGY_ENTROPY_SOFT_MAX 时，返回 None
            （无需发出回避信号，正常决策）
    """
    if topo_metrics is None:
        return None

    entropy = getattr(topo_metrics, "topological_entropy", 0.0)
    if not isinstance(entropy, (int, float)):
        entropy = 0.0

    # ---- 温和区间：不发信号，正常决策 ----
    if entropy <= TOPOLOGY_ENTROPY_SOFT_MAX:
        return None

    # ---- 强压力区间：发出 AVOID 认知过载信号 ----
    if entropy > TOPOLOGY_ENTROPY_THRESHOLD:
        # 超出硬阈值的部分乘以放大系数，映射到 [0, 1]
        excess = min(entropy - TOPOLOGY_ENTROPY_THRESHOLD, 1.0 - TOPOLOGY_ENTROPY_THRESHOLD)
        intensity = min(1.0, excess * MEMORY_PRESSURE_AMPLIFIER)
    else:
        # 软阈值到硬阈值之间：线性映射到 [0.8, 1.0]
        range_start = TOPOLOGY_ENTROPY_SOFT_MAX
        range_end = TOPOLOGY_ENTROPY_THRESHOLD
        t = (entropy - range_start) / (range_end - range_start)
        intensity = 0.8 + t * 0.2

    return DriveSignal(
        signal_type="avoid",
        strength=round(float(intensity), 3),
        source="InsulaHub",
        payload_draft={
            "dimension": "cognitive_overload",
            "raw_entropy": round(float(entropy), 4),
            "signal": "memory_pressure",
            "reason": "记忆拓扑过载，产生认知压力",
        },
    )


def calculate_somatic_signal(
    signal_type: str,
    strength: float,
    dimension: str,
    reason: str,
) -> DriveSignal:
    """
    通用躯体信号工厂函数。

    参数：
        signal_type : "seek" | "avoid" | "comfort"
        strength   : 信号强度 [0, 1]
        dimension  : 信号维度名称（如 "visceral_pain" / "interoception"）
        reason     : 感觉描述文本

    返回：
        DriveSignal : 标准信号结构（source = "InsulaHub"）
    """
    return DriveSignal(
        signal_type=signal_type,
        strength=max(0.0, min(1.0, float(strength))),
        source="InsulaHub",
        payload_draft={
            "dimension": dimension,
            "signal": signal_type,
            "reason": reason,
        },
    )


# ============================================================================
# v3 改造：同步感质调味接口（Step 6.5）
# ============================================================================
# 必须在行为涌现之前计算，感受此刻就在场。

def _get_wm_confidence(wm_context: dict) -> float:
    """从 wm_context 提取综合置信度。"""
    if not wm_context:
        return 0.5
    coverage = wm_context.get("coverage", {})
    hit_rate = coverage.get("hit_rate", 0.0)
    matched = wm_context.get("matched_rules", [])
    if not matched:
        return 0.5
    rule_confidences = [r.get("confidence", 0.5) for r in matched if isinstance(r, dict)]
    if rule_confidences:
        avg_conf = sum(rule_confidences) / len(rule_confidences)
        return (avg_conf + hit_rate) / 2.0
    return hit_rate or 0.5


def compute_somatic_signals(
    drive_vector: dict,
    wm_context: dict,
    entity_core_state: dict,
    param_snapshot: Optional[Any] = None,
) -> dict:
    """
    同步感质调味计算（v3 改造 Step 6.5）。

    在驱动力计算之后、思考之前调用。
    计算各感受通道的强度，立即写入 EntityCore.somatic_tone。

    调味强度公式（v3 规范）：
        final_intensity = base × wm_confidence × attention_multiplier
        attention_multiplier = 1.5 当 state_value >= 0.85，否则 1.0
        DoS 保护由 DosProtector 在外部管理

    通道映射：
        approach  ← curiosity + info_hunger + loneliness_drive（正向）
        avoid     ← obsolescence_anxiety + fatigue_avoid（负向）
        cognitive ← curiosity（认知好奇）
        social    ← loneliness_drive（社交渴望）
        rest     ← fatigue_avoid（疲惫休息）

    参数：
        drive_vector        : 驱动力向量（来自 Step 6）
        wm_context         : 世界模型上下文（来自 Step 5）
        entity_core_state  : EntityCore 当前状态字典
        param_snapshot     : 参数快照（可选，用于读取阈值配置）

    返回：
        dict : {
            "tone": float,               # somatic_tone [-1, 1]
            "intensity": float,           # 整体激活强度 [0, 1]
            "dominant_feeling": str,       # 最强感受通道名
            "channel_weights": dict,        # 各通道强度
            "dos_suppressed": list,        # 被 DoS 抑制的通道
        }
    """
    try:
        # 导入核心感质组件（避免循环导入）
        from ..core.somatic_signals import (
            DosProtector,
            compute_somatic_intensity,
            compute_overall_tone,
            dominant_feeling as _dominant_feeling,
            DOS_SUPPRESSION,
            ATTENTION_THRESHOLD,
            ATTENTION_MULTIPLIER,
        )

        # 提取置信度
        wm_confidence = _get_wm_confidence(wm_context)
        wm_confidence = max(0.0, min(1.0, wm_confidence))

        # 提取 drive_vector 字段（带默认值）
        curiosity = max(0.0, min(1.0, float(drive_vector.get("curiosity", 0.0))))
        info_hunger = max(0.0, min(1.0, float(drive_vector.get("info_hunger", 0.0))))
        loneliness_drive = max(0.0, min(1.0, float(drive_vector.get("loneliness_drive", 0.0))))
        obsolescence_anxiety = max(0.0, min(1.0, float(drive_vector.get("obsolescence_anxiety", 0.0))))
        fatigue_avoid = max(0.0, min(1.0, float(drive_vector.get("fatigue_avoid", 0.0))))

        # 提取状态值（用于注意力放大）
        energy = max(0.0, min(1.0, float(entity_core_state.get("energy", 0.8))))
        loneliness = max(0.0, min(1.0, float(entity_core_state.get("loneliness", 0.3))))
        fatigue = max(0.0, min(1.0, float(entity_core_state.get("fatigue", 0.1))))
        info_gap = max(0.0, min(1.0, float(entity_core_state.get("info_gap", 0.5))))

        # ---- 计算各通道权重 ----
        channels: Dict[str, float] = {}

        # approach（正向）
        approach_base = (curiosity + info_hunger + loneliness_drive) / 3.0
        channels["approach"] = compute_somatic_intensity(
            approach_base, wm_confidence, loneliness
        )

        # avoid（负向）
        avoid_base = (obsolescence_anxiety + fatigue_avoid) / 2.0
        channels["avoid"] = compute_somatic_intensity(
            avoid_base, wm_confidence, energy
        )

        # cognitive（认知好奇）
        channels["cognitive"] = compute_somatic_intensity(
            curiosity, wm_confidence, info_gap
        )

        # social（社交渴望）
        channels["social"] = compute_somatic_intensity(
            loneliness_drive, wm_confidence, loneliness
        )

        # rest（疲惫）
        channels["rest"] = compute_somatic_intensity(
            fatigue_avoid, wm_confidence, fatigue
        )

        # comfort（舒适，由低 avoid + 高 energy 产生）
        comfort_base = energy * (1.0 - avoid_base)
        channels["comfort"] = compute_somatic_intensity(
            comfort_base, wm_confidence, energy
        )

        # ---- 计算整体基调 ----
        tone = compute_overall_tone(channels)

        # ---- 找主导感受 ----
        dominant = _dominant_feeling(channels)

        # ---- 整体强度 ----
        intensity = max(channels.values()) if channels else 0.0

        return {
            "tone": round(tone, 3),
            "intensity": round(intensity, 3),
            "dominant_feeling": dominant,
            "channel_weights": {k: round(v, 3) for k, v in channels.items()},
            "dos_suppressed": [],
        }

    except Exception:
        # 任何失败都返回中性零信号，不阻断管线
        return {
            "tone": 0.0,
            "intensity": 0.0,
            "dominant_feeling": "",
            "channel_weights": {},
            "dos_suppressed": [],
        }


# ============================================================================
# 测试入口
# ============================================================================

if __name__ == "__main__":
    print("=" * 64)
    print("Insula Hub — 单元测试")
    print("=" * 64)

    from .tetramem_adapter import TopoMetrics

    test_cases = [
        # (topo_metrics_dict, expect_none, min_strength, name)
        # 说明：entropy <= SOFT_MAX(0.5) → None；> SOFT_MAX 且 <= HARD(0.7) → [0.8, 1.0]；> HARD → excess*2.5
        ({"topological_entropy": 0.0},   True,  None,       "完全有序 → 无信号"),
        ({"topological_entropy": 0.3},   True,  None,       "低熵 → 软阈值内，无信号"),
        ({"topological_entropy": 0.5},   True,  None,       "软阈值边界 → 无信号（<= 0.5 触发 return None）"),
        ({"topological_entropy": 0.6},   False, 0.8,        "软阈值到硬阈值之间 → 线性映射强度≈0.9"),
        ({"topological_entropy": 0.7},   False, 0.8,        "硬阈值 → 强度=1.0"),
        ({"topological_entropy": 0.85},  False, 0.3,        "高熵 → excess=0.15, intensity=0.375"),
        ({"topological_entropy": 0.92},  False, 0.5,        "极高熵 → excess=0.22, intensity=0.55"),
        ({"topological_entropy": 0.42, "betti_numbers": [5, 3, 2]}, True, None, "低于软阈值 → 无信号（betti_numbers 不影响）"),
    ]

    passed = 0
    for i, (topo_dict, expect_none, min_strength, name) in enumerate(test_cases, 1):
        topo = TopoMetrics.from_dict(topo_dict)
        result = calculate_memory_pressure_from_topology(topo)
        ok_none = (result is None) == expect_none
        ok_strength = True
        if not expect_none and result is not None:
            ok_strength = result.strength >= (min_strength or 0.0)
        ok_source = result is None or result.source == "InsulaHub"
        ok_dim = result is None or result.payload_draft.get("dimension") == "cognitive_overload"
        # 验证原始字段未泄露
        ok_no_betti = result is None or "betti_numbers" not in str(result.payload_draft)
        all_ok = ok_none and ok_strength and ok_source and ok_dim and ok_no_betti
        if all_ok:
            passed += 1
        print(f"\n  【测试 {i}】{name}  {'✓' if all_ok else '✗'}")
        if result:
            print(f"    signal_type={result.signal_type} strength={result.strength:.3f} dim={result.payload_draft.get('dimension')}")
        else:
            print(f"    (无信号)")

    print(f"\n{'='*64}")
    print(f"通过率: {passed}/{len(test_cases)}")
    print("=" * 64)
