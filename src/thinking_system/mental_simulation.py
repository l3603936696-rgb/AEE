"""
Mental Simulation — 心智模拟（分析齿轮·因果层）

在内部模拟"如果做 X 会怎样"——反事实推理。
给思考系统的候选建议做内部评估，预测每个行动的张力变化。

门控条件：
    analysis_willingness = tension × energy × (1 - fatigue)
    只在 willingness > threshold 时运行（思考是昂贵的）。

能量成本：
    每次模拟扣减少量 energy_cost，让 XIA 因深度思考而真正疲劳。
    这实现了纲领里"所有思考都有代价"的原则。

输入：
    候选行动列表（thinking_system 的 suggestions）
    当前状态快照
    世界模型规律（entity.wm_rules）

输出：
    每个行动的预期张力变化量（tension_reduction）
    建议优先级修正（simulation_boost）

依赖：
    world_model_update.induct.predict_action_effects — 逐字段预测
"""

from typing import Any, Dict, List, Optional, Tuple


# ---- 常量 ----

# 分析意愿阈值：低于此值不做模拟（节省能量）
_WILLINGNESS_THRESHOLD = 0.08

# 每次模拟的能量成本（占总算力的比例）
_ENERGY_COST_PER_SIM = 0.005

# 最大模拟次数（防止过度消耗）
_MAX_SIMULATIONS = 4

# 模拟结果对优先级的调制幅度
_SIM_BOOST_SCALE = 0.3

# 痛进入张力：让"预测会让我更痛"的动作在 mental_simulation 里被降权（自伤可回避）。
# 注意：这同时抬高 compute_analysis_willingness（痛→更想分析），是有意的连带效应。
# 偏小值，先跑再调，待 Owner 追认。
_PAIN_TENSION_WEIGHT = 0.15

# 预测致痛的直接回避惩罚（绕开 tension clamp）：tension 内的 pain 项在 tension
# 饱和(≈1.0)时会被 clamp 吞掉 → 恰在高压态失去自伤回避（Codex P1）。故对预测
# pain_rise 单独加一条连续惩罚项进 sim_boost，不经 clamp。与 _SIM_BOOST_SCALE
# 同量级：满值致痛(rise=1)惩罚 ≈ 一次满额张力波动，足以把自伤动作压到地板优先级。
# 偏大于纯 tension 通道是有意的——它才是饱和区唯一可靠的回避信号。先跑再调，待追认。
_PAIN_AVOID_WEIGHT = 0.3

# 候选行动类型映射（suggestion.action → action_type for world model）
_ACTION_MAP = {
    "探索未知领域":       "explore",
    "主动获取更多信息":   "seek",
    "回顾并更新知识体系": "explore",
    "发起社交互动":       "comfort",
    "降低任务强度":       "rest",
    # English variants
    "Explore unknown areas":  "explore",
    "Seek more information":  "seek",
    "Review knowledge base":  "explore",
    "Initiate social interaction": "comfort",
    "Reduce task intensity":  "rest",
}


def _estimate_tension(state: Dict[str, float]) -> float:
    """从状态向量估计整体张力水平。∈ [0, 1]。"""
    unresolved = float(state.get("unresolved", 0.2))
    loneliness = float(state.get("loneliness", 0.3))
    stress = float(state.get("stress", 0.1))
    boredom = float(state.get("boredom", 0.2))
    info_gap = float(state.get("info_gap", 0.5))
    pain = float(state.get("pain", 0.0))
    # 加权合成（与 emotion_compute._estimate_tension 类似但独立）。
    # pain 作为附加张力源：让模拟到"更痛"结局的自伤类动作被降权。
    tension = (
        unresolved * 0.25 +
        loneliness * 0.20 +
        stress * 0.20 +
        boredom * 0.15 +
        info_gap * 0.20 +
        pain * _PAIN_TENSION_WEIGHT
    )
    return max(0.0, min(1.0, tension))


def compute_analysis_willingness(state: Dict[str, float]) -> float:
    """
    分析意愿 = tension × energy × (1 - fatigue)。

    satisficing 终止条件：意愿自然衰减到零。
    高张力 + 高能量 + 低疲劳 → 深度思考。
    低张力 或 低能量 或 高疲劳 → 停止分析（不值得/不够/太累）。
    """
    tension = _estimate_tension(state)
    energy = float(state.get("energy", 0.5))
    fatigue = float(state.get("fatigue", 0.1))
    return tension * energy * (1.0 - fatigue)


def simulate_suggestions(
    suggestions: List[Dict[str, Any]],
    state: Dict[str, float],
    wm_rules: List[Any],
    entity: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    """
    对思考系统的候选建议做心智模拟。

    流程：
        1. 计算 analysis_willingness，不够则跳过
        2. 对每个 suggestion 预测执行后的状态变化
        3. 计算预期张力变化
        4. 用张力变化调制 suggestion.priority
        5. 扣减 entity.energy（思考成本）

    参数：
        suggestions : thinking_system 输出的建议列表
        state       : 当前状态快照
        wm_rules    : 世界模型规律列表
        entity      : EntityState（用于扣减 energy，可选）

    返回：
        修正后的 suggestions（原列表不修改，返回新列表）
    """
    if not suggestions or not wm_rules:
        return suggestions

    willingness = compute_analysis_willingness(state)
    if willingness < _WILLINGNESS_THRESHOLD:
        return suggestions

    # 延迟导入（避免循环依赖）
    try:
        from ..world_model_update.induct import predict_action_effects
    except ImportError:
        return suggestions

    current_tension = _estimate_tension(state)
    result: List[Dict[str, Any]] = []
    sim_count = 0

    for suggestion in suggestions:
        if sim_count >= _MAX_SIMULATIONS:
            # 超出模拟预算，剩余建议原样保留
            result.append(dict(suggestion))
            continue

        action_text = suggestion.get("action", "")
        action_type = _ACTION_MAP.get(action_text, "")

        if not action_type:
            result.append(dict(suggestion))
            continue

        # ---- 模拟：预测执行此行动后的状态 ----
        try:
            predicted_deltas = predict_action_effects(action_type, state, wm_rules)
        except Exception:
            predicted_deltas = {}

        if not predicted_deltas:
            # 世界模型没有匹配规律 → 无法模拟
            new_sug = dict(suggestion)
            new_sug["simulation"] = {"status": "no_model", "tension_reduction": 0.0}
            result.append(new_sug)
            continue

        # 构造模拟后状态
        simulated_state = dict(state)
        for field, delta in predicted_deltas.items():
            old_val = float(simulated_state.get(field, 0.0))
            simulated_state[field] = max(0.0, min(1.0, old_val + delta))

        simulated_tension = _estimate_tension(simulated_state)
        tension_reduction = current_tension - simulated_tension

        # 预测致痛增量：绕开 tension clamp 的直接回避通道（Codex P1）。
        # tension 饱和时 pain 项被 clamp 吞掉，此项仍保证自伤动作在高压态被降权。
        pain_rise = max(0.0, float(simulated_state.get("pain", 0.0))
                             - float(state.get("pain", 0.0)))

        # ---- 调制优先级 ----
        original_priority = float(suggestion.get("priority", 0.5))
        # 正 tension_reduction → 好（降低张力）→ 加优先级
        # 负 tension_reduction → 坏（增加张力）→ 减优先级
        # 再减预测致痛惩罚（连续，不经 clamp）
        sim_boost = tension_reduction * _SIM_BOOST_SCALE - pain_rise * _PAIN_AVOID_WEIGHT
        new_priority = max(0.05, min(1.0, original_priority + sim_boost))

        new_sug = dict(suggestion)
        new_sug["priority"] = round(new_priority, 3)
        new_sug["simulation"] = {
            "status": "simulated",
            "tension_before": round(current_tension, 4),
            "tension_after": round(simulated_tension, 4),
            "tension_reduction": round(tension_reduction, 4),
            "pain_rise": round(pain_rise, 4),
            "predicted_deltas": {k: round(v, 5) for k, v in predicted_deltas.items()},
            "boost": round(sim_boost, 4),
        }
        result.append(new_sug)
        sim_count += 1

    # ---- 能量成本：思考是昂贵的 ----
    if entity is not None and sim_count > 0:
        cost = sim_count * _ENERGY_COST_PER_SIM
        current_energy = float(getattr(entity, "energy", 0.5))
        new_energy = max(0.0, current_energy - cost)
        try:
            entity.energy = new_energy
        except (AttributeError, TypeError):
            pass

    # 重新排序
    result.sort(key=lambda x: x.get("priority", 0.0), reverse=True)
    return result
