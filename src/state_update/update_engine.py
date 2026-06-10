"""
State Update Engine (状态更新引擎) — 算力账本 v2.0

统一算力账本：energy = 总算力 - 所有当前负载。

负载来源（所有占用共享总算力 1.0）：
    social      : 社交信息缺失评估（有输入则归零）
    cognitive   : 认知负荷（预测误差驱动）
    info        : 信息缺口评估
    meta        : 元信息处理（极低，不可消除）
    emotional   : 负面情绪额外线程
    stress      : 高优先级中断通道
    fatigue_delay: 处理延迟（队列长则延迟大）
    frontload   : 前台对话占用
    idle        : 基础运转开销

核心概念：
    energy 是瞬时状态，不是累积量
    恢复 = 负载降低后算力自然回流，不是"充电"
    stress = 未处理的意外信号数量，不走半衰期

子模块：
    update_engine_helpers.py — 辅助函数 + 状态步进 helpers
    info_queue.py            — 信息队列
    compute_load.py          — 算力负载计算
    dopamine_tone.py         — 多巴胺音调
"""

import copy
import time as _time
from typing import Any, Dict, List, Optional

from .update_engine_helpers import (
    _safe_float, _clamp, _param,
    _is_avoid_action, _is_positive_action,
    process_pending_surprises, update_relief_debt,
    _step_loneliness, _step_unresolved,
    _step_boredom, _step_boredom_futility,
    _step_fatigue, _step_info_gap,
)
from .info_queue import InfoQueue
from .compute_load import compute_energy_delta, compute_stress_delta


# =============================================================================
# Global InfoQueue singleton
# =============================================================================

_global_info_queue: Optional[InfoQueue] = None


def get_info_queue() -> InfoQueue:
    global _global_info_queue
    if _global_info_queue is None:
        _global_info_queue = InfoQueue()
    return _global_info_queue


def reset_info_queue() -> None:
    global _global_info_queue
    _global_info_queue = None


# =============================================================================
# Main Entry Point
# =============================================================================

def update_state(
    current_state: Dict[str, Any],
    decision: Optional[Dict[str, Any]],
    idle_seconds: float,
    param_snapshot: Any,
    time_injected_fields: Optional[set] = None,
    wm_rules: Optional[List[Any]] = None,
    pending_surprises_episodes: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, float]:
    """
    状态更新引擎主入口（算力账本 v2.0）。

    参数：
        current_state        : 当前内部状态字典
        decision            : 本轮裁决结果
        idle_seconds        : 距离上次状态更新经过的秒数
        param_snapshot      : 参数只读快照
        time_injected_fields : 被沉默时间注入的维度集合
        wm_rules          : 世界模型规律列表（用于 stress 生命周期）
        pending_surprises_episodes : 收集 UNRESOLVABLE episode 的列表

    返回：
        new_state : 全新字典（深拷贝，不原地修改输入）
    """
    injected: set = time_injected_fields or set()

    # ---- 深拷贝输出字典 ----
    new_state: Dict[str, float] = {}
    for k, v in current_state.items():
        if isinstance(v, (int, float)):
            new_state[k] = float(v)
        elif isinstance(v, list):
            new_state[k] = list(v)
        else:
            new_state[k] = v

    # ---- 读取当前值 ----
    current_energy     = _safe_float(new_state.get("energy"), 0.5)
    current_loneliness = _safe_float(new_state.get("loneliness"), 0.3)
    current_unresolved = _safe_float(new_state.get("unresolved"), 0.2)
    current_boredom   = _safe_float(new_state.get("boredom"), 0.2)
    current_fatigue   = _safe_float(new_state.get("fatigue"), 0.1)
    current_stress    = _safe_float(new_state.get("stress"), 0.1)
    current_relief_debt = _safe_float(new_state.get("relief_debt"), 0.0)
    somatic_tone      = _safe_float(new_state.get("somatic_tone"), 0.0)
    info_gap          = _safe_float(new_state.get("info_gap"), 0.5)

    pending_surprises = new_state.get("pending_surprises", [])
    if not isinstance(pending_surprises, list):
        pending_surprises = []
    if len(pending_surprises) > 10:
        pending_surprises = pending_surprises[-10:]

    time_since_last_social = _safe_float(new_state.get("time_since_last_social"), 0.0)
    time_since_last_info = _safe_float(new_state.get("time_since_last_info"), 0.0)

    action_type = ""
    if decision is not None:
        action_type = str(decision.get("action_type", "")).strip().lower()

    has_social_input = bool(
        decision is not None
        and action_type in ("comfort", "seek", "social")
    )
    is_rest = (action_type == "rest")
    is_comfort = (action_type == "comfort")
    metabolic_seconds = max(idle_seconds, 1.0)

    # =========================================================================
    # Step 1: InfoQueue accumulate + process
    # =========================================================================
    info_queue = get_info_queue()
    if is_rest:
        info_queue.notify_rest_start()
    else:
        info_queue.notify_rest_end()
    if action_type == "explore":
        info_queue.notify_explore()

    tick_index = _safe_float(new_state.get("tick_index", 0), 0)
    info_queue.accumulate(
        idle_seconds=metabolic_seconds,
        loneliness=current_loneliness,
        unresolved=current_unresolved,
        somatic_tone=somatic_tone,
        info_gap=info_gap,
        has_social_input=has_social_input,
        time_since_last_social=time_since_last_social,
        time_since_last_info=time_since_last_info,
        tick_index=int(tick_index),
    )
    info_queue.process(action_type)

    # =========================================================================
    # Step 2: Compute energy delta via ledger
    # =========================================================================
    new_energy, load_breakdown = compute_energy_delta(
        info_queue=info_queue,
        stress=current_stress,
        fatigue=current_fatigue,
        somatic_tone=somatic_tone,
        idle_seconds=metabolic_seconds,
        is_rest=is_rest,
        has_social_input=has_social_input,
        time_since_last_social=time_since_last_social,
        time_since_last_info=time_since_last_info,
    )

    # =========================================================================
    # Step 3: Stress lifecycle management
    # =========================================================================
    prediction_error = _safe_float(new_state.get("_last_prediction_error"), 0.0)

    if prediction_error > 0.3:
        magnitude = prediction_error * 0.5
        pending_surprises = pending_surprises + [{
            "magnitude": magnitude,
            "created_at": _time.time(),
            "prediction_error": prediction_error,
        }]

    updated_surprises, surprise_resolved, should_remove, episode = process_pending_surprises(
        pending_surprises, wm_rules, current_state, param_snapshot
    )

    if should_remove and episode and pending_surprises_episodes is not None:
        pending_surprises_episodes.append(episode)

    new_stress = compute_stress_delta(
        current_stress=current_stress,
        prediction_error=prediction_error,
        is_rest=is_rest,
        is_comfort=is_comfort,
        pending_surprises_count=len(updated_surprises),
        surprise_resolved=surprise_resolved,
    )

    pending_surprises = updated_surprises

    # =========================================================================
    # Step 4: Independent dimension updates
    # =========================================================================
    new_loneliness = _step_loneliness(current_state, current_loneliness, injected, metabolic_seconds)
    new_unresolved = _step_unresolved(is_rest, current_unresolved, metabolic_seconds)
    new_boredom = _step_boredom(action_type, current_boredom, decision, metabolic_seconds)
    new_boredom_futility = _step_boredom_futility(new_state, param_snapshot, metabolic_seconds)
    new_fatigue = _step_fatigue(action_type, is_rest, is_comfort, current_fatigue,
                                  info_queue, param_snapshot, metabolic_seconds)
    new_info_gap = _step_info_gap(action_type, info_gap, info_queue, metabolic_seconds)

    # =========================================================================
    # Step 5: Relief debt evolution
    # =========================================================================
    try:
        relief_debt_p = {
            "pressure_threshold": _param(param_snapshot, "state.relief_debt_pressure_threshold", 0.5),
            "accum_rate":        _param(param_snapshot, "state.relief_debt_accum_rate", 0.05),
            "reduce_rate":       _param(param_snapshot, "state.relief_debt_reduce_rate", 0.08),
        }
        state_for_relief = {"boredom": new_boredom, "unresolved": new_unresolved}
        new_relief_debt = update_relief_debt(current_relief_debt, decision, state_for_relief, relief_debt_p)
    except Exception:
        new_relief_debt = current_relief_debt

    # =========================================================================
    # Step 6: Recovery damping (time-injected dims recover slower)
    # =========================================================================
    damping = 1.0 - _safe_float(
        _param(param_snapshot, "state.time_silence_recovery_damping_factor", 0.5),
        0.5,
    )
    if damping < 1.0 and damping > 0.0:
        if "loneliness" in injected:
            new_loneliness = min(1.0, new_loneliness + (1.0 - damping) * 0.06)
        if "boredom" in injected:
            new_boredom = min(1.0, new_boredom + (1.0 - damping) * 0.06)

    # =========================================================================
    # Step 7: Write back with clamping
    # =========================================================================
    new_state["energy"]       = _clamp(new_energy)
    new_state["loneliness"]  = _clamp(new_loneliness)
    new_state["loneliness_core"] = _clamp(float(current_state.get("loneliness_core", current_loneliness * 0.7)))
    new_state["loneliness_surface"] = _clamp(float(current_state.get("loneliness_surface", current_loneliness * 0.3)))
    new_state["unresolved"]  = _clamp(new_unresolved)
    new_state["boredom"]    = _clamp(new_boredom)
    new_state["boredom_futility"] = new_boredom_futility
    new_state["fatigue"]    = _clamp(new_fatigue)
    new_state["stress"]     = _clamp(new_stress)
    new_state["relief_debt"]= _clamp(new_relief_debt, 0.0, float("inf"))
    new_state["info_gap"]   = _clamp(new_info_gap)
    new_state["somatic_tone"] = max(-1.0, min(1.0, somatic_tone))
    new_state["pending_surprises"] = pending_surprises

    # Clear recovered time-injection markers
    cleared: set = set()
    if "loneliness" in injected and new_state["loneliness"] < 0.3:
        cleared.add("loneliness")
    if "boredom" in injected and new_state["boredom"] < 0.3:
        cleared.add("boredom")
    new_state["_time_injected_cleared"] = cleared
    new_state["_load_breakdown"] = load_breakdown

    return new_state
