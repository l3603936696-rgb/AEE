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

接口契约：
    输入：current_state(dict), decision, idle_seconds, param_snapshot, time_injected_fields
    输出：new_state(dict, 深拷贝，严禁原地修改 current_state)

红线约束：
    - 零硬编码：所有数值参数必须通过 get_param(param_snapshot, ...) 读取
    - 失败隔离：单维度异常必须 catch 住并保留原值
    - 强制限幅：所有状态字段最终必须 clamp(0, 1)
"""

import copy
import math
import time as _time
from typing import Any, Dict, List, Optional

from ..world_model_update.defaults import get_param
from .info_queue import InfoQueue, EXPLORE_INFO_INTAKE, INFO_DIGEST_TO_GAP_RATIO, EXPLORE_IMMEDIATE_GAP_REDUCTION
from .compute_load import (
    compute_energy_delta,
    compute_stress_delta,
    compute_queue_trigger_rest,
)
from .dopamine_tone import compute_boredom_futility_delta


# ============================================================================
# 辅助函数
# ============================================================================

def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _clamp(val: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, val))


def _param(p: Any, key: str, default: float) -> float:
    """从参数快照读取参数（支持 dict 和 ParameterSnapshot）。"""
    if p is None:
        return default
    if hasattr(p, "get"):
        v = p.get(key)
        if v is not None:
            return float(v)
    return default


# ============================================================================
# 行为类型判断
# ============================================================================

def _is_avoid_action(decision: Optional[Dict[str, Any]]) -> bool:
    if decision is None:
        return False
    action_type = str(decision.get("action_type", "")).strip().lower()
    return action_type in ("idle", "drift", "shallow_social", "avoid")


def _is_positive_action(decision: Optional[Dict[str, Any]]) -> bool:
    if decision is None:
        return False
    action_type = str(decision.get("action_type", "")).strip().lower()
    return action_type in ("explore", "resolve", "seek", "comfort")


# ============================================================================
# pending_surprises 管理（stress 生命周期）
# ============================================================================

# 单例 InfoQueue（跨轮次维持，但在 restart 时重置）
_global_info_queue: Optional[InfoQueue] = None


def get_info_queue() -> InfoQueue:
    """获取全局 InfoQueue 实例。"""
    global _global_info_queue
    if _global_info_queue is None:
        _global_info_queue = InfoQueue()
    return _global_info_queue


def reset_info_queue() -> None:
    """重置全局 InfoQueue（仅用于测试）。"""
    global _global_info_queue
    _global_info_queue = None


def _process_pending_surprises(
    pending_surprises: list,
    wm_rules: List[Any],
    current_state: Optional[Dict[str, Any]] = None,
    param_snapshot: Any = None,
) -> tuple[list, bool, bool, Optional[Dict[str, Any]]]:
    """
    处理 pending_surprises 队列（使用真实世界模型匹配逻辑）。

    每轮最多处理一个 surprise：
        - attempt_resolve() → resolved=True → surprise 出队，resolved=True
        - resolved=False 且超限 → surprise 出队，写入 episode，resolved=False
        - resolved=False 未超限 → surprise 放回队尾，resolved=False

    参数：
        pending_surprises : 当前 pending_surprises 列表
        wm_rules         : 世界模型规律列表（来自 entity.wm_rules）
        current_state    : 当前状态快照（用于规则匹配）
        param_snapshot   : 参数快照（用于读取阈值）

    返回：
        (updated_list, resolved_flag, should_remove, episode_to_write)
        resolved_flag     : True = surprise 被规则覆盖，stress 下降
        should_remove     : True = surprise 超限，应从队列移除
        episode_to_write  : 写入 episode 的记录（仅当 should_remove=True 时非 None）
    """
    if not pending_surprises:
        return [], False, False, None

    from ..world_model_update.resolve import attempt_resolve

    surprise = pending_surprises[0]
    resolved, should_remove, episode = attempt_resolve(
        surprise=surprise,
        wm_rules=wm_rules,
        current_state=current_state,
        param_snapshot=param_snapshot,
    )

    if resolved:
        return pending_surprises[1:], True, False, None
    elif should_remove:
        return pending_surprises[1:], False, True, episode
    else:
        return pending_surprises[1:] + [surprise], False, False, None


# ============================================================================
# relief_debt（独立于算力账本的另一套机制，保留）
# ============================================================================

def _update_relief_debt(
    current_relief_debt: float,
    decision: Optional[Dict[str, Any]],
    state: Dict[str, float],
    p: Dict[str, float],
) -> float:
    """
    舒适负债演化（与算力账本独立，不受影响）。

    欠债条件：压力状态下（boredom + unresolved 超过阈值）选择了逃避动作
    还债条件：直面问题（seek / resolve / explore）
    """
    try:
        pressure_threshold = p["pressure_threshold"]
        accum_rate = p["accum_rate"]
        reduce_rate = p["reduce_rate"]

        boredom = state.get("boredom", 0.0)
        unresolved = state.get("unresolved", 0.0)
        pressure = boredom + unresolved

        if pressure > pressure_threshold and _is_avoid_action(decision):
            relief_debt = current_relief_debt + accum_rate
        elif _is_positive_action(decision):
            relief_debt = current_relief_debt - reduce_rate
        else:
            relief_debt = current_relief_debt

        return max(0.0, relief_debt)
    except Exception:
        return current_relief_debt


# ============================================================================
# 主入口
# ============================================================================

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
        wm_rules          : 世界模型规律列表（用于 stress 生命周期判断 surprise 是否可解决）
        pending_surprises_episodes : 用于收集 UNRESOLVABLE surprise 产生的 episode 记录

    返回：
        new_state : 全新字典（深拷贝，不原地修改输入）
    """
    injected: set = time_injected_fields or set()

    # ---- 深拷贝输出字典（严禁原地修改输入）----
    new_state: Dict[str, float] = {}
    for k, v in current_state.items():
        if isinstance(v, (int, float)):
            new_state[k] = float(v)
        elif isinstance(v, list):
            # pending_surprises 列表透传（由本函数内部处理）
            new_state[k] = list(v)
        else:
            new_state[k] = v

    # ---- 读取当前值 ----
    current_energy   = _safe_float(new_state.get("energy"), 0.5)
    current_loneliness = _safe_float(new_state.get("loneliness"), 0.3)
    current_unresolved = _safe_float(new_state.get("unresolved"), 0.2)
    current_boredom  = _safe_float(new_state.get("boredom"), 0.2)
    current_fatigue  = _safe_float(new_state.get("fatigue"), 0.1)
    current_stress   = _safe_float(new_state.get("stress"), 0.1)
    current_relief_debt = _safe_float(new_state.get("relief_debt"), 0.0)
    somatic_tone     = _safe_float(new_state.get("somatic_tone"), 0.0)
    info_gap         = _safe_float(new_state.get("info_gap"), 0.5)

    # pending_surprises（未处理的意外信号队列）
    pending_surprises = new_state.get("pending_surprises", [])
    if not isinstance(pending_surprises, list):
        pending_surprises = []

    # pending_surprises 最多保留 10 个（防止无限膨胀）
    if len(pending_surprises) > 10:
        pending_surprises = pending_surprises[-10:]

    # 时间相关字段
    time_since_last_social = _safe_float(
        new_state.get("time_since_last_social"), 0.0
    )
    time_since_last_info = _safe_float(
        new_state.get("time_since_last_info"), 0.0
    )

    # ---- 行为类型 ----
    action_type = ""
    if decision is not None:
        action_type = str(decision.get("action_type", "")).strip().lower()

    has_social_input = bool(
        decision is not None
        and action_type in ("comfort", "seek", "social")
    )
    is_rest = (action_type == "rest")
    is_comfort = (action_type == "comfort")

    # ---- 最小代谢时间（保证每轮有可见漂移）----
    metabolic_seconds = max(idle_seconds, 1.0)

    # =========================================================================
    # Step 1: 获取/更新 InfoQueue
    # =========================================================================
    info_queue = get_info_queue()

    # rest 通知（紧急生效）
    if is_rest:
        info_queue.notify_rest_start()
    else:
        info_queue.notify_rest_end()

    # explore 通知
    if action_type == "explore":
        info_queue.notify_explore()

    # ---- 1a: 积累队列（先积累，再消化）----
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

    # ---- 1b: 消化队列 ----
    info_queue.process(action_type)

    # =========================================================================
    # Step 2: 算力账本 → 计算 energy 变化
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

    energy_delta = new_energy - current_energy

    # =========================================================================
    # Step 3: stress 生命周期管理
    # =========================================================================
    prediction_error = _safe_float(
        new_state.get("_last_prediction_error"), 0.0
    )

    # pending_surprises 积累：预测误差产生新的 surprise
    if prediction_error > 0.3:
        magnitude = prediction_error * 0.5
        pending_surprises = pending_surprises + [{
            "magnitude": magnitude,
            "created_at": _time.time(),
            "prediction_error": prediction_error,
        }]

    # rest / comfort 期间处理一个 pending surprise
    updated_surprises, surprise_resolved, should_remove, episode = _process_pending_surprises(
        pending_surprises, wm_rules, current_state, param_snapshot
    )

    # 超限的 surprise → 收集到 episode 列表
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
    # Step 4: 独立维度更新（不走算力账本的维度）
    # =========================================================================

    # ---- loneliness：v4.0 严格因果版 ----
    # ❗ 物理定义：loneliness = 资源缺失变量
    #   - 唯一释放出口：真实用户输入（raw_input 非空）
    #   - 无因果来源的衰减 = 系统替她解决情绪 → autonomy 破坏
    loneliness_override = current_state.get("_loneliness_target_override")
    if loneliness_override is not None:
        # 主路径：compute_loneliness_target 已按 v4.0 语义计算
        new_loneliness = float(loneliness_override)
    else:
        # Fallback：仅在管线异常时使用（应尽量不触发）
        # 规则：无真实用户输入 → loneliness 只能升，不能降
        has_user_input = (
            current_state.get("raw_input") is not None
            and str(current_state.get("raw_input", "")).strip() != ""
        )
        if has_user_input:
            # 真实用户说了话 → loneliness 可降至 0
            new_loneliness = _clamp(current_loneliness - 0.1)
        else:
            # 无用户输入 → loneliness 只能升或不变
            new_loneliness = _clamp(current_loneliness + 0.01 * metabolic_seconds / 60.0)

    # ---- unresolved：rest 时消化 ----
    # unresolved 主要由感知层注入（world_model_update），这里只处理 rest 时的消耗
    if is_rest:
        unresolved_delta = -0.10 * metabolic_seconds / 60.0
    else:
        unresolved_delta = 0.0
    new_unresolved = _clamp(current_unresolved + unresolved_delta)

    # ---- boredom：探索/直面降低，idle 轻微上升 ----
    try:
        boredom_natural = 0.002 * metabolic_seconds / 60.0
        if action_type in ("explore", "resolve", "seek", "comfort"):
            boredom_delta = -0.06
        elif action_type == "idle" or _is_avoid_action(decision):
            boredom_delta = 0.03
        else:
            boredom_delta = 0.0
        new_boredom = _clamp(current_boredom + boredom_delta + boredom_natural)
    except Exception:
        new_boredom = current_boredom

    # ---- boredom_futility：徒劳性倦怠积累（v11.x 多巴胺闭环）----
    # 多因子叠加：dopamine_tone（低时促进积累）+ stress（高时促进）+ somatic_tone（负面时促进）
    # 全程连续，无 if-else
    try:
        current_boredom_futility = _safe_float(new_state.get("boredom_futility"), 0.0)
        dopamine_tone = _safe_float(new_state.get("dopamine_tone"), 0.5)
        stress_val = _safe_float(new_state.get("stress"), 0.0)
        somatic_tone = _safe_float(new_state.get("somatic_tone"), 0.0)
        futility_delta = compute_boredom_futility_delta(
            current_boredom_futility=current_boredom_futility,
            dopamine_tone=dopamine_tone,
            stress=stress_val,
            somatic_tone=somatic_tone,
            idle_seconds=metabolic_seconds,
            param_snapshot=param_snapshot,
        )
        new_boredom_futility = min(1.0, max(0.0, current_boredom_futility + futility_delta))
        # ---- 催产素抑制倦怠积累（v11.x）----
        # oxytocin_tone > 0.5 时，减少 futility 积累（被接住的余韵缓解徒劳感）
        # 效果 bounded：oxytocin_tone=1.0 且 dt=1min 时最多减少 0.5% futility 积累
        # 不覆盖长期警觉，oxytocin_k 保持小值
        oxytocin_tone = _safe_float(new_state.get("oxytocin_tone"), 0.5)
        oxytocin_k = _param(param_snapshot, "boredom_futility.oxytocin_k", 0.005)
        oxytocin_benefit = max(0.0, oxytocin_tone - 0.5) * 2 * oxytocin_k * metabolic_seconds / 60.0
        new_boredom_futility = max(0.0, new_boredom_futility - oxytocin_benefit)
    except Exception:
        new_boredom_futility = _safe_float(new_state.get("boredom_futility"), 0.0)

    # ---- fatigue：探索积累，rest / comfort 恢复 ----
    try:
        fatigue_base = current_fatigue
        if action_type in ("explore", "seek"):
            fatigue_delta = 0.04 * metabolic_seconds / 60.0
        elif is_rest:
            # rest 时恢复更快（队列消化 → 处理延迟降低 → fatigue 下降）
            queue_backlog = info_queue.get_total_queue_occupancy()
            fatigue_delta = -0.06 * metabolic_seconds / 60.0 * (1.0 + queue_backlog)
        elif is_comfort:
            fatigue_delta = -0.02 * metabolic_seconds / 60.0
        else:
            fatigue_delta = 0.0
        new_fatigue = _clamp(fatigue_base + fatigue_delta)
    except Exception:
        new_fatigue = current_fatigue

    # ---- info_gap：自然积累，explore 即时微降，rest/comfort 消化队列时大幅下降 ----
    try:
        # 自然积累（沉默时长）
        info_gap_natural = 0.002 * metabolic_seconds / 60.0
        # 消化降低（rest/comfort 处理队列 → info_gap 下降）
        info_digested = info_queue.get_last_info_processed()
        info_gap_digest = info_digested * INFO_DIGEST_TO_GAP_RATIO
        # 探索即时反馈（"知道自己找到了东西"，连续信号无需 if/else）
        _is_explore = float(action_type == "explore")
        info_gap_explore = _is_explore * EXPLORE_IMMEDIATE_GAP_REDUCTION
        info_gap_delta = info_gap_natural - info_gap_digest - info_gap_explore
        new_info_gap = _clamp(info_gap + info_gap_delta)
    except Exception:
        new_info_gap = info_gap

    # =========================================================================
    # Step 5: relief_debt 演化（独立于算力账本）
    # =========================================================================
    try:
        relief_debt_p = {
            "pressure_threshold": get_param(param_snapshot, "state.relief_debt_pressure_threshold", 0.5),
            "accum_rate":        get_param(param_snapshot, "state.relief_debt_accum_rate", 0.05),
            "reduce_rate":       get_param(param_snapshot, "state.relief_debt_reduce_rate", 0.08),
        }
        state_for_relief = {
            "boredom":    new_boredom,
            "unresolved": new_unresolved,
        }
        new_relief_debt = _update_relief_debt(
            current_relief_debt, decision, state_for_relief, relief_debt_p
        )
    except Exception:
        new_relief_debt = current_relief_debt

    # =========================================================================
    # Step 6: 恢复阻尼（时间注入维度恢复速度减半）
    # =========================================================================
    damping = 1.0 - _safe_float(
        get_param(param_snapshot, "state.time_silence_recovery_damping_factor", 0.5),
        0.5,
    )

    if damping < 1.0 and damping > 0.0:
        if "loneliness" in injected:
            # 时间注入维度：恢复效果减半
            new_loneliness = min(1.0, new_loneliness + (1.0 - damping) * 0.06)
        if "boredom" in injected:
            new_boredom = min(1.0, new_boredom + (1.0 - damping) * 0.06)

    # =========================================================================
    # Step 7: 强制限幅
    # =========================================================================
    new_state["energy"]       = _clamp(new_energy)
    new_state["loneliness"]  = _clamp(new_loneliness)
    # v11.4 双通道透传（从输入状态继承，Step 8.4 已经计算好）
    new_state["loneliness_core"] = _clamp(float(current_state.get("loneliness_core", current_loneliness * 0.7)))
    new_state["loneliness_surface"] = _clamp(float(current_state.get("loneliness_surface", current_loneliness * 0.3)))
    new_state["unresolved"]  = _clamp(new_unresolved)
    new_state["boredom"]    = _clamp(new_boredom)
    new_state["boredom_futility"] = new_boredom_futility
    new_state["fatigue"]    = _clamp(new_fatigue)
    new_state["stress"]     = _clamp(new_stress)
    new_state["relief_debt"]= _clamp(new_relief_debt, 0.0, float("inf"))
    new_state["info_gap"]   = _clamp(new_info_gap)
    # somatic_tone 由 insula_hub 计算，update_engine 透传并 clamp 保护
    new_state["somatic_tone"] = max(-1.0, min(1.0, somatic_tone))
    new_state["somatic_tone"] = max(-1.0, min(1.0, somatic_tone))
    new_state["pending_surprises"] = pending_surprises

    # ---- 清除已恢复的时间注入标记 ----
    cleared: set = set()
    if "loneliness" in injected and new_state["loneliness"] < 0.3:
        cleared.add("loneliness")
    if "boredom" in injected and new_state["boredom"] < 0.3:
        cleared.add("boredom")
    new_state["_time_injected_cleared"] = cleared

    # ---- 调试信息（生产环境可删除）----
    new_state["_load_breakdown"] = load_breakdown

    return new_state


# ============================================================================
# 测试入口
# ============================================================================

if __name__ == "__main__":
    print("=" * 64)
    print("State Update Engine — 算力账本 v2.0 集成测试")
    print("=" * 64)

    reset_info_queue()  # 重置全局队列

    def make_params() -> dict:
        return {
            "state.relief_debt_pressure_threshold": 0.5,
            "state.relief_debt_accum_rate": 0.05,
            "state.relief_debt_reduce_rate": 0.08,
            "state.time_silence_recovery_damping_factor": 0.5,
        }

    params = make_params()

    def print_state(label: str, state: dict) -> None:
        numeric = {k: v for k, v in state.items() if isinstance(v, (int, float)) and not k.startswith("_")}
        print(f"  {label}: " + ", ".join(f"{k}={v:.4f}" for k, v in numeric.items()))

    # ---- 测试 1: 接口契约 — 深拷贝验证 ----
    print("\n【测试 1】接口契约 — 深拷贝验证")
    original = {"energy": 0.8, "loneliness": 0.3}
    result = update_state(original, None, 60.0, params)
    ok1 = result is not original and original.get("energy") == 0.8
    print(f"  {'✓' if ok1 else '✗'} 输出非原对象: {result is not original}")
    print(f"  {'✓' if original.get('energy') == 0.8 else '✗'} 原对象未被修改: energy={original.get('energy')}")

    # ---- 测试 2: rest 行为 — energy 下降（队列被消化，负载减轻，energy 回升）----
    print("\n【测试 2】rest 行为 → energy 因负载降低而回升")
    reset_info_queue()
    state2 = {"energy": 0.5, "loneliness": 0.5, "unresolved": 0.3, "boredom": 0.2,
               "fatigue": 0.7, "stress": 0.3, "relief_debt": 0.0, "somatic_tone": 0.0,
               "info_gap": 0.6, "time_since_last_social": 300.0, "time_since_last_info": 300.0,
               "pending_surprises": [], "_last_prediction_error": 0.0}
    decision2 = {"action_type": "rest", "target": "self"}
    result2 = update_state(state2, decision2, 60.0, params)
    delta2 = result2["energy"] - 0.5
    ok2 = result2["energy"] > 0.5  # rest 应该有更低的负载，energy 更高
    print(f"  {'✓' if ok2 else '✗'} energy: 0.5 → {result2['energy']:.4f}（delta={delta2:+.4f}，rest 应回升）")
    print(f"  负载分解: {result2.get('_load_breakdown', {})}")

    # ---- 测试 3: comfort 行为 → energy 因负载降低而回升（v2.0 语义）----
    print("\n【测试 3】comfort 行为 → 社交输入归零，负载降低，energy 回升")
    reset_info_queue()
    state3 = {"energy": 0.5, "loneliness": 0.5, "unresolved": 0.3, "boredom": 0.2,
               "fatigue": 0.3, "stress": 0.2, "relief_debt": 0.0, "somatic_tone": 0.3,
               "info_gap": 0.5, "time_since_last_social": 300.0, "time_since_last_info": 300.0,
               "pending_surprises": [], "_last_prediction_error": 0.0}
    decision3 = {"action_type": "comfort", "target": "user"}
    result3 = update_state(state3, decision3, 60.0, params)
    ok3 = result3["energy"] > 0.5  # v2.0：comfort 降低负载，energy 回升
    print(f"  {'✓' if ok3 else '✗'} energy: 0.5 → {result3['energy']:.4f}（v2.0：comfort 应回升）")
    print(f"  loneliness: {result3['loneliness']:.4f}（comfort 应降低孤独感）")

    # ---- 测试 4: pending_surprises 语义验证（world_model=None → surprise 无法解决）----
    print("\n【测试 4】pending_surprises → v2.0 语义验证（world_model=None → surprise 放回队尾）")
    reset_info_queue()
    state4 = {"energy": 0.5, "loneliness": 0.4, "unresolved": 0.3, "boredom": 0.2,
               "fatigue": 0.2, "stress": 0.5, "relief_debt": 0.0, "somatic_tone": 0.2,
               "info_gap": 0.5, "time_since_last_social": 60.0, "time_since_last_info": 60.0,
               "pending_surprises": [{"magnitude": 0.5, "created_at": _time.time()}],
               "_last_prediction_error": 0.0}
    decision4 = {"action_type": "comfort", "target": "user"}
    result4 = update_state(state4, decision4, 60.0, params, wm_rules=None)
    remaining = len(result4.get("pending_surprises", []))
    print(f"  pending_surprises: 1 → {remaining} 个（surprise 放回队尾，数量不变）")
    print(f"  stress: 0.5 → {result4['stress']:.4f}（world_model=None，surprise 无法解决）")
    ok4 = remaining == 1  # surprise 放回队尾，数量不变
    print(f"  {'✓' if ok4 else '✗'} surprise 放回队尾（需真实 world_model 才能解决 → stress 下降）")

    # ---- 测试 5: explore 不直接降低 info_gap（信息待消化），rest 才消化 ----
    print("\n【测试 5】explore → 队列积压，rest → info_gap 下降")
    reset_info_queue()
    state5 = {"energy": 0.5, "loneliness": 0.3, "unresolved": 0.2, "boredom": 0.2,
               "fatigue": 0.3, "stress": 0.1, "relief_debt": 0.0, "somatic_tone": 0.1,
               "info_gap": 0.8, "time_since_last_social": 60.0, "time_since_last_info": 600.0,
               "pending_surprises": [], "_last_prediction_error": 0.0}
    decision5 = {"action_type": "explore", "target": "information"}
    result5_explore = update_state(state5, decision5, 60.0, params)
    # explore 不直接降低 info_gap（只积压到队列），因此变化很小（仅自然积累）
    explore_delta = result5_explore["info_gap"] - 0.8
    ok5a = abs(explore_delta) < 0.05  # explore 后 info_gap 基本不变
    print(f"  {'✓' if ok5a else '✗'} explore info_gap: 0.8 → {result5_explore['info_gap']:.4f}（delta={explore_delta:+.4f}，explore 不直接降低）")
    # rest 后 info_gap 下降（队列被消化）
    result5_rest = update_state(result5_explore, {"action_type": "rest", "target": "self"}, 60.0, params)
    rest_delta = result5_rest["info_gap"] - 0.8
    ok5b = rest_delta < -0.05  # rest 后 info_gap 明显下降
    print(f"  {'✓' if ok5b else '✗'} rest info_gap: 0.8 → {result5_rest['info_gap']:.4f}（delta={rest_delta:+.4f}，rest 消化后下降）")
    ok5 = ok5a and ok5b

    # ---- 测试 6: 无决策时正常运行 ----
    print("\n【测试 6】decision=None 时正常运行")
    reset_info_queue()
    state6 = {"energy": 0.5, "loneliness": 0.3, "unresolved": 0.2, "boredom": 0.2,
               "fatigue": 0.1, "stress": 0.1, "relief_debt": 0.0, "somatic_tone": 0.0,
               "info_gap": 0.5, "time_since_last_social": 60.0, "time_since_last_info": 60.0,
               "pending_surprises": [], "_last_prediction_error": 0.0}
    result6 = update_state(state6, None, 60.0, params)
    ok6 = isinstance(result6, dict) and "energy" in result6
    print(f"  {'✓' if ok6 else '✗'} decision=None 不抛异常，energy={result6['energy']:.4f}")

    # ---- 测试 7: pending_surprises 积累（预测误差）----
    print("\n【测试 7】高预测误差 → pending_surprises 积累")
    reset_info_queue()
    state7 = {"energy": 0.5, "loneliness": 0.3, "unresolved": 0.2, "boredom": 0.2,
               "fatigue": 0.1, "stress": 0.2, "relief_debt": 0.0, "somatic_tone": 0.0,
               "info_gap": 0.5, "time_since_last_social": 60.0, "time_since_last_info": 60.0,
               "pending_surprises": [], "_last_prediction_error": 0.6}
    result7 = update_state(state7, None, 60.0, params)
    ok7 = len(result7.get("pending_surprises", [])) > 0
    print(f"  {'✓' if ok7 else '✗'} pending_surprises: {len(result7.get('pending_surprises', []))} 个（应增加）")

    # ---- 测试 8: clamp 边界 ----
    print("\n【测试 8】clamp 边界保护")
    reset_info_queue()
    state8 = {"energy": 2.0, "loneliness": -1.0, "unresolved": 5.0, "boredom": -0.5,
               "fatigue": 1.5, "stress": -0.1, "relief_debt": 0.0, "somatic_tone": 2.0,
               "info_gap": 3.0, "time_since_last_social": 60.0, "time_since_last_info": 60.0,
               "pending_surprises": [], "_last_prediction_error": 0.0}
    result8 = update_state(state8, None, 0.0, params)
    all_clamped = all(
        0.0 <= result8[k] <= 1.0
        for k in ("energy", "loneliness", "unresolved", "boredom", "fatigue", "stress", "info_gap")
    ) and -1.0 <= result8.get("somatic_tone", 0.0) <= 1.0
    tone_ok = -1.0 <= result8.get("somatic_tone", 0.0) <= 1.0
    print(f"  {'✓' if all_clamped else '✗'} 所有字段在合法范围内")
    print(f"    energy={result8['energy']:.4f}, somatic_tone={result8.get('somatic_tone', 0):.4f}{' (clamped)' if tone_ok else ' (NOT CLAMPED!)'}")

    # ---- 测试 9: 负面情绪 → emotional 占用推高 ----
    print("\n【测试 9】somatic_tone 偏负 → emotional 占用更高")
    reset_info_queue()
    state9a = {"energy": 0.5, "loneliness": 0.3, "unresolved": 0.2, "boredom": 0.2,
                "fatigue": 0.1, "stress": 0.1, "relief_debt": 0.0, "somatic_tone": 0.0,
                "info_gap": 0.5, "time_since_last_social": 60.0, "time_since_last_info": 60.0,
                "pending_surprises": [], "_last_prediction_error": 0.0}
    state9b = {"energy": 0.5, "loneliness": 0.3, "unresolved": 0.2, "boredom": 0.2,
                "fatigue": 0.1, "stress": 0.1, "relief_debt": 0.0, "somatic_tone": -0.7,
                "info_gap": 0.5, "time_since_last_social": 60.0, "time_since_last_info": 60.0,
                "pending_surprises": [], "_last_prediction_error": 0.0}
    result9a = update_state(state9a, None, 60.0, params)
    result9b = update_state(state9b, None, 60.0, params)
    load_a = result9a.get("_load_breakdown", {})
    load_b = result9b.get("_load_breakdown", {})
    emotional_a = load_a.get("emotional", 0.0)
    emotional_b = load_b.get("emotional", 0.0)
    ok9 = emotional_b > emotional_a  # 负面情绪 → emotional 占用更高
    print(f"  {'✓' if ok9 else '✗'} 情绪占用: neutral={emotional_a:.4f}, negative={emotional_b:.4f}（负面情绪应更高）")
    print(f"  energy: neutral={result9a['energy']:.4f}, negative={result9b['energy']:.4f}")

    # ---- 测试 10: rest 期间 fatigue 加速恢复 ----
    print("\n【测试 10】rest 期间 → fatigue 恢复加速")
    reset_info_queue()
    state10 = {"energy": 0.5, "loneliness": 0.3, "unresolved": 0.6, "boredom": 0.2,
               "fatigue": 0.6, "stress": 0.3, "relief_debt": 0.0, "somatic_tone": 0.0,
               "info_gap": 0.5, "time_since_last_social": 60.0, "time_since_last_info": 60.0,
               "pending_surprises": [], "_last_prediction_error": 0.0}
    decision10 = {"action_type": "rest", "target": "self"}
    result10 = update_state(state10, decision10, 120.0, params)
    ok10 = result10["fatigue"] < 0.6
    print(f"  {'✓' if ok10 else '✗'} fatigue: 0.6 → {result10['fatigue']:.4f}（rest 应恢复）")
    print(f"  unresolved: 0.6 → {result10['unresolved']:.4f}（rest 应消耗 unresolved）")

    print("\n" + "=" * 64)
    all_ok = all([ok1, ok2, ok3, ok4, ok5, ok6, ok7, all_clamped, ok9, ok10])
    print(f"测试结果: {'全部通过 ✓' if all_ok else '部分失败 ✗'}")
    print("=" * 64)
