"""
compute_load.py — 统一算力账本引擎（算力账本 v2.0）

接收状态快照和 InfoQueue，返回 energy 变化量（delta）。
不直接写状态，只产生 delta，由调用方通过 adjust() 写入。

算力账本逻辑：
    energy = 总算力(1.0)
              - social_occupancy      (社交信息缺失评估)
              - cognitive_occupancy   (认知负荷)
              - info_occupancy        (信息缺口评估)
              - meta_occupancy        (元信息处理，极低)
              - emotional_occupancy   (负面情绪额外线程)
              - stress_occupancy      (高优先级中断通道)
              - fatigue_occupancy     (处理延迟：队列长 → 延迟大)
              - frontload_occupancy   (前台对话占用)
              - idle_baseline         (基础运转开销)

返回：
    energy_delta : 负数（占用），通过 entity.adjust("energy", delta) 写入
    load_breakdown : 各维度的占用分解（用于调试日志）
"""

from __future__ import annotations

from typing import Any, Dict, Optional

# ============================================================================
# 算力账本参数
# ============================================================================

# 基础运转开销（就算什么都不干，也需要占用的算力）
IDLE_BASELINE: float = 0.05

# 前台对话占用系数（与对话复杂度成正比，与可用算力成反比）
FRONTLOAD_BASE: float = 0.10   # 基础对话占用
FRONTLOAD_INTENSITY_BONUS: float = 0.05  # 高强度输入额外占用

# fatigue → 处理延迟占用系数
# fatigue 高时，同等工作需要更多算力 → 实际可用算力降低
FATIGUE_PROCESS_DELAY_FACTOR: float = 0.15  # fatigue=1.0 时额外占用 15%

# 最小可用算力下限（保证任何情况下至少留 5% 给基础运转）
MIN_ENERGY_FLOOR: float = 0.05


# ============================================================================
# 主函数
# ============================================================================

def compute_energy_delta(
    info_queue: Any,
    stress: float,
    fatigue: float,
    somatic_tone: float,
    idle_seconds: float,
    is_rest: bool,
    has_social_input: bool,
    time_since_last_social: float,
    time_since_last_info: float,
) -> tuple[float, Dict[str, float]]:
    """
    计算本轮 energy 的变化量（delta）。

    公式：
        energy = 1.0 - sum(all_occupancies)
        energy_delta = energy - current_energy  （由调用方算）

    参数：
        info_queue        : InfoQueue 实例
        stress           : 当前压力 [0, 1]
        fatigue          : 当前疲劳 [0, 1]
        somatic_tone     : 当前躯体基调 [-1, 1]
        idle_seconds     : 距上次状态更新的秒数
        is_rest         : 本轮是否处于 rest 状态
        has_social_input : 本轮是否有社交输入
        time_since_last_social : 距上次社交输入的秒数
        time_since_last_info    : 距上次信息获取的秒数

    返回：
        (energy_delta, load_breakdown)
        energy_delta     : 本轮 energy 的变化量（负数 = 下降）
        load_breakdown  : 各维度占用的字典（调试用）
    """
    # ---- 1. 各维度算力占用 ----

    # 社交信息评估占用
    if has_social_input:
        social_occ = 0.0
    else:
        # 无社交输入：随沉默时长增长，最小占用 + 队列占用
        time_factor = min(time_since_last_social / 3600.0, 1.0)  # 最多按 1h 算
        social_occ = 0.02 + time_factor * 0.08  # [0.02, 0.10]

    # 认知负荷占用（cognitive 队列 + 基础开销）
    cognitive_occ = (
        info_queue.get_dim_occupancy("cognitive")
        + info_queue.min_occupancy.get("cognitive", 0.02)
    )

    # 信息缺口评估占用
    info_occ = (
        info_queue.get_dim_occupancy("info")
        + info_queue.min_occupancy.get("info", 0.01)
    )

    # 元信息处理占用（极低，不可消除）
    meta_occ = 0.005

    # 负面情绪额外线程占用
    if somatic_tone < -0.1:
        emotional_occ = info_queue.get_dim_occupancy("emotional") + 0.02
    else:
        emotional_occ = 0.0

    # stress 高优先级中断占用（直接占总算力的一定比例）
    stress_occ = info_queue.get_stress_occupancy(stress)

    # fatigue 处理延迟占用（队列越长，处理新任务的延迟越大）
    # fatigue 从 [0, 1] 映射到 [0, FATIGUE_PROCESS_DELAY_FACTOR]
    queue_backlog = info_queue.get_total_queue_occupancy()
    fatigue_delay_occ = fatigue * FATIGUE_PROCESS_DELAY_FACTOR * (1.0 + queue_backlog)

    # 前台对话占用（rest 时无前台占用）
    if is_rest:
        frontload_occ = 0.0
    else:
        frontload_occ = FRONTLOAD_BASE

    # ---- 2. 基础运转开销 ----
    idle_occ = IDLE_BASELINE

    # ---- 3. 汇总占用 ----
    total_occupancy = (
        social_occ
        + cognitive_occ
        + info_occ
        + meta_occ
        + emotional_occ
        + stress_occ
        + fatigue_delay_occ
        + frontload_occ
        + idle_occ
    )

    # clamp 到总算力范围
    total_occupancy = min(total_occupancy, 1.0 - MIN_ENERGY_FLOOR)

    # 本轮 energy = 总算力 - 占用
    energy = 1.0 - total_occupancy

    # energy_delta = energy - current_energy（由调用方提供 current_energy 后自行计算）
    # 这里只返回总占用，供外部计算 delta
    load_breakdown = {
        "social":      round(social_occ, 4),
        "cognitive":   round(cognitive_occ, 4),
        "info":        round(info_occ, 4),
        "meta":        round(meta_occ, 4),
        "emotional":   round(emotional_occ, 4),
        "stress":       round(stress_occ, 4),
        "fatigue_delay": round(fatigue_delay_occ, 4),
        "frontload":   round(frontload_occ, 4),
        "idle":        round(idle_occ, 4),
        "total":       round(total_occupancy, 4),
        "energy":      round(energy, 4),
    }

    return energy, load_breakdown


def compute_stress_delta(
    current_stress: float,
    prediction_error: float,
    is_rest: bool,
    is_comfort: bool,
    pending_surprises_count: int,
    surprise_resolved: bool,
) -> float:
    """
    计算本轮 stress 的变化量。

    stress = 未处理的意外信号数量（不走衰减，只通过处理而下降）

    积累：
        prediction_error > 0 → 产生新的 surprise

    恢复：
        is_rest or is_comfort → 每轮处理一个 pending surprise
        surprise_resolved = True → surprise 已被世界模型吸收，stress 下降
        surprise_resolved = False → 暂时无法解释，surprise 放回队列，stress 不变
    """
    stress = current_stress

    # ---- 积累：预测误差产生 surprise ----
    if prediction_error > 0.3:
        # 高预测误差 → 新增一个未处理的 surprise
        # magnitude 与 prediction_error 成正比
        stress += prediction_error * 0.1
    elif prediction_error < -0.2:
        # 负误差 → 预测偏高但实际正常（惊喜/意外正面）
        stress -= 0.05  # 轻微下降，正面意外有助于缓解压力

    # ---- 恢复：rest / comfort 期间处理一个 pending surprise ----
    if is_rest or is_comfort:
        if pending_surprises_count > 0:
            if surprise_resolved:
                # 世界模型成功吸收了这个 surprise
                stress -= 0.15  # 处理掉一个 surprise，stress 下降
            else:
                # 暂时无法解释，surprise 放回队列，stress 维持
                pass

    return max(0.0, min(1.0, stress))


def compute_queue_trigger_rest(
    info_queue: Any,
    available_energy: float,
    current_stress: float,
    threshold_ratio: float = 1.2,
) -> bool:
    """
    判断是否应该触发 rest（基于队列积压速率 vs 消化速率）。

    参数：
        info_queue       : InfoQueue 实例
        available_energy : 当前可用算力（0~1）
        current_stress   : 当前压力
        threshold_ratio  : 触发阈值（积累速率 > 消化速率 × threshold_ratio）

    返回：
        True = 应该触发 rest
    """
    growth_rate = info_queue.compute_growth_rate()
    process_rate = info_queue.compute_process_rate(
        available_capacity=available_energy,
        in_rest=False,
    )

    # 加上 stress 的高优先级占用，它会进一步压缩消化能力
    stress_shrink = 1.0 - current_stress * 0.5
    effective_process_rate = process_rate * stress_shrink

    return growth_rate > effective_process_rate * threshold_ratio
