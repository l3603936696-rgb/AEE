"""
Parameters — 参数定义与默认值

三层结构：
    A. thresholds  — V3 已验证的运行参数（防爆门控、管道超时等）
    B. drives     — 驱动力初始基线（仅绝对安全参数）
    C. dynamics   — 动态参数表（初始为空，由世界模型异步注入）

约束：
    - 驱动基线仅包含 curiosity_baseline、info_hunger_baseline 等绝对安全参数
    - 禁止将 *_sensitivity、module_weights.* 等乘子归一化后再使用
    - 所有乘子类参数必须直接作为独立乘子作用于原始信号强度
"""

from typing import Any, Dict


# ============================================================================
# 分类元信息（文档用）
# ============================================================================

PARAM_CATEGORIES: Dict[str, str] = {
    "thresholds": (
        "V3 迁移的运行参数：防爆门控、超时控制、优先级约束等。"
        "所有参数均为绝对安全参数，任何修改不影响系统稳定性。"
    ),
    "drives": (
        "驱动力初始基线：驱动力的起始参照值（不经归一化直接叠加）。"
        "仅含绝对安全参数，修改仅影响驱动强度，不破坏系统行为。"
    ),
    "mechanisms": (
        "机制开关：控制特定演化或崩溃机制是否启用。"
        "仅含布尔开关，不参与任何数值计算。"
    ),
    "dynamics": (
        "动态参数表：初始为空，由世界模型在异步周期中通过审批流动态注入。"
        "注入前不可读取。"
    ),
    "_system": (
        "系统元数据：参数表版本、最后修改时间等。"
    ),
    "web_search": (
        "联网搜索模块参数：触发阈值、结果数量、超时控制等。"
    ),
    "connection": (
        "v3.0 connection_depth 模型参数：权重因子、三段式孤独感参数。"
        "修改走参数审批流程。"
    ),
    "experience": (
        "v3.5b 经验偏移参数：正负偏移强度、相似度阈值。"
        "修改走参数审批流程。"
    ),
    "coherence": (
        "v3.5c coherence 调制参数：阈值、放大/衰减系数、负向阻尼。"
        "修改走参数审批流程。"
    ),
    "emotion_particle": (
        "v10.0 日常层粒子场参数：容量、衰减曲线、查表插值锚点。"
        "控制情绪粒子场的密度、衰减和文字流速调制。"
    ),
    "emotion_decay": (
        "v10.0 情绪衰减参数：各核心情绪的衰减半衰期。"
        "厌倦采用双根源独立衰减（绝望性倦怠 vs 徒劳性倦怠）。"
    ),
    "emotion_projection": (
        "v11.0 三层情绪投影参数：各层投影上限、层间阻尼系数、记忆层冷却。"
        "控制主线层、日常层、记忆层的相互投影强度。"
    ),
    "emotion": (
        "v10.0/v11.0 其他情绪参数：高冲击阈值、情绪分化观测窗口。"
    ),
    "language": (
        "v7.0 语言系统参数：消力效率、自适应温控、六大主权。"
        "包含驱动力场语言表达的闭环测量与自适应调控。"
    ),
    "conversion": (
        "转换系数：决定'外部输入如何转为内部状态变化'的乘子。"
        "是真正的人格参数（innate），可被风化系统长期漂移。"
        "对应 EntityState 上的 9 个 _*_weights / _*_params dict。"
    ),
}


# ============================================================================
# A. thresholds — V3 迁移的已验证运行参数
# ============================================================================

THRESHOLDS: Dict[str, Any] = {
    # --- 叙事记忆压力门控（从 V3 迁移）---
    "narrative_memory_pressure_note_gate": 0.52,
    "narrative_compactor_mem_pressure_gate": 0.70,
    "narrative_memory_pressure_critical_gate": 0.82,
    "narrative_memory_pressure_event_gate": 0.92,

    # --- 管道执行约束 ---
    "pipeline_max_execution_time_ms": 5000,
    "thinking_max_steps": 2,
    "thinking_timeout_ms": 2000,

    # --- 决策约束 ---
    "peer_uncaught_force_reply_streak": 3,

    # --- 世界模型约束 ---
    "world_model_max_rules": 200,
    "world_model_snapshot_retention": 50,

    # --- 联网搜索 ---
    "web_search.enabled": True,
    "web_search.info_hunger_threshold": 0.6,
    "web_search.wm_hit_threshold": 0.3,
    "web_search.intent_intensity_threshold": 0.6,
    "web_search.max_results": 5,
    "web_search.timeout_seconds": 8.0,

    # --- 调试 ---
    "debug_log_decision_trace": True,
}


# ============================================================================
# B. drives — 驱动力初始基线（仅绝对安全参数）
# ============================================================================

DRIVES: Dict[str, float] = {
    "curiosity_baseline": 0.20,
    "info_hunger_baseline": 0.24,
}


# ============================================================================
# C. mechanisms — 机制开关（布尔型）
# ============================================================================

MECHANISMS: Dict[str, bool] = {
    "enable_parameter_decay": False,
    "enable_belief_shock": False,
    "enable_body_evolution": False,
}


# ============================================================================
# D. dynamics — 动态参数表（初始为空）
# ============================================================================

DYNAMICS: Dict[str, Any] = {}


# ============================================================================
# E. _system — 系统元数据
# ============================================================================

_SYSTEM: Dict[str, Any] = {
    "version": "1.0.0",
    "created_at": None,      # 由外层调度器在首次创建时填入
    "last_modified_at": None,
    "last_modified_by": None,
}


# ============================================================================
# F. connection — v3.0 connection_depth 模型参数
# ============================================================================

CONNECTION: Dict[str, float] = {
    # v3.5a 权重参数（三个因子出厂相等，不同实例可通过参数公差获得不同分布）
    "connection.w_prediction": 1.0,
    "connection.w_somatic":    1.0,
    "connection.w_tension":   1.0,

    # v3.0 loneliness 三段式参数
    "connection.loneliness_recovery_rate":      0.35,   # connection_depth>0 时每轮恢复量
    "connection.loneliness_rejection_multiplier": 1.8,  # connection_depth<0 时沉默积累加速倍率
    "connection.loneliness_connection_threshold": 0.1,   # 判断正向连接 vs 无连接的阈值
    "connection.release_lag":                     0.70,   # 释放惯性系数（target 向 effective 的过渡速度）
}

# ============================================================================
# G. experience — v3.5b 经验偏移参数
# ============================================================================

EXPERIENCE: Dict[str, float] = {
    "connection.positive_bias_strength": 0.05,   # 正面经验偏移强度（正向偏移更易发生）
    "connection.negative_bias_strength": 0.02,   # 负面经验偏移强度（轻微负向，但不压过正向）
    "connection.positive_threshold":    0.10,   # loneliness 下降超过此值 → 积极经验
    "connection.negative_threshold":     0.10,   # loneliness 上升超过此值 → 消极经验
}

# ============================================================================
# H. coherence — v3.5c coherence 调制参数
# ============================================================================

COHERENCE: Dict[str, float] = {
    "connection.coherence_high_threshold": 0.70,  # coherence > 此值 → 放大
    "connection.coherence_low_threshold":  0.30,  # coherence < 此值 → 衰减
    "connection.coherence_amplify":       1.30,  # 高 coherence 时 connection_depth 放大倍率
    "connection.coherence_attenuate":     0.50,  # 低 coherence 时 connection_depth 衰减倍率
    "connection.negative_damping_floor":  0.70,  # 负向阻尼下限（loneliness=1 时的阻尼值）
    "connection.damping_scale":           0.30,  # 阻尼随 loneliness 的变化幅度
    "connection.recent_deltas_maxlen":   5,     # recent_deltas 缓存容量（不持久化）
}

# ============================================================================
# I. observation — 观测层参数
# ============================================================================

OBSERVATION: Dict[str, Any] = {
    "observation.buffer_size": 50,           # observation_buffer 最大轮数（不持久化）
    "observation.trend_window": 10,         # 短期趋势计算窗口
    "observation.profile_window": 50,        # 个体性剖面计算窗口
    "observation.contamination_coefficient": 0.30,  # loneliness 对 somatic/tension 的污染估算系数
}

# ============================================================================
# J. emotion_particle — v10.0 日常层粒子场参数
# ============================================================================

EMOTION_PARTICLE: Dict[str, float] = {
    # 容量与产生
    "emotion_particle.max_capacity":       200,
    "emotion_particle.inertia_weight":     0.30,
    "emotion_particle.ambient_weight":     0.50,

    # 衰减曲线
    "emotion_particle.log_half_life_s":    1800,
    "emotion_particle.min_density":        0.00,

    # 查表插值锚点（密度 → 文字流速调制）
    "emotion_particle.lookup_density_0":   0.00,
    "emotion_particle.lookup_density_1":    0.30,
    "emotion_particle.lookup_density_2":    0.60,
    "emotion_particle.lookup_density_3":    1.00,
    "emotion_particle.lookup_flow_0":      1.00,
    "emotion_particle.lookup_flow_1":      0.90,
    "emotion_particle.lookup_flow_2":      0.70,
    "emotion_particle.lookup_flow_3":      0.40,

    # 延迟（秒）
    "emotion_particle.slow_delay_s":       30,
}

# ============================================================================
# K. emotion_decay — v10.0 情绪衰减参数
# ============================================================================

EMOTION_DECAY: Dict[str, float] = {
    # 厌倦的两种根源各自独立衰减
    "emotion_decay.boredom_despair_t":    7200,   # 绝望性倦怠（秒）
    "emotion_decay.boredom_futility_t":    3600,   # 徒劳性倦怠（秒）

    # 核心情绪衰减
    "emotion_decay.joy_t":               3600,
    "emotion_decay.fear_t":              1800,
    "emotion_decay.anger_t":            2400,
    "emotion_decay.sadness_t":          5400,
    "emotion_decay.surprise_t":          600,     # 惊讶短促

    # 惯性残余
    "emotion_decay.inertia_t":           900,
}

# ============================================================================
# L. emotion_projection — v11.0 三层情绪投影阻尼参数
# ============================================================================

EMOTION_PROJECTION: Dict[str, float] = {
    # 各层投影上限
    "emotion_projection.mainline_cap":            1.00,
    "emotion_projection.daily_cap":               0.60,
    "emotion_projection.memory_cap":             0.80,

    # 层间阻尼系数
    "emotion_projection.mainline_to_daily_damping":  0.70,
    "emotion_projection.daily_to_mainline_damping":  0.40,
    "emotion_projection.memory_to_mainline_damping": 0.50,
    "emotion_projection.memory_to_daily_damping":    0.30,

    # 冷却
    "emotion_projection.memory_cooldown_s":          300,
    "emotion_projection.memory_repeat_decay":        0.50,
}

# ============================================================================
# M. emotion — v10.0/v11.0 其他情绪参数
# ============================================================================

EMOTION: Dict[str, float] = {
    "emotion_insight.high_impact_threshold":         0.85,
    "emotion_differentiation.observation_window":    200,
    "emotion_differentiation.min_stabilization":      0.10,
}

# ============================================================================
# N. language — v7.0 语言系统参数
# ============================================================================

LANGUAGE: Dict[str, float] = {
    # 消力效率参数
    "language.quenching.high_threshold":      0.65,
    "language.quenching.upgrade_threshold":    0.70,
    "language.quenching.min_contexts":        3,
    "language.quenching.history_maxlen":       500,

    # 自适应温控
    "language.thermal.high_energy_scale":     1.30,
    "language.thermal.low_energy_scale":      0.60,
    "language.thermal.energy_threshold":      0.40,
    "language.thermal.decay_rate":           0.02,

    # 语言丰度
    "language丰度.low_threshold":              0.60,

    # 六大主权
    "language.self_close.avoid_high_threshold": 0.75,
    "language.self_close.lock_window":         0.05,
    "language.social_fatigue.rate":           0.015,
    "language.social_fatigue.recovery_rate":  0.008,
    "language.social_fatigue.avoid_bias_cap": 0.30,
    "language.mirror.bias_strength":          0.40,
    "language.forget.negative_strength_decay": 0.05,
    "language.defy.pressure_threshold":       0.60,
    "language.defy.resistance_quenching_boost": 1.50,
}

# ============================================================================
# O. conversion — 转换系数（EntityState 上的 9 个 _*_weights / _*_params dict）
# ============================================================================
# 展平为 dot-path，初始值与 EntityState 硬编码默认值完全一致。
# 风化系统可漂移其中被注册的子集。

CONVERSION: Dict[str, Any] = {
    # ---- 趋近驱动合成权重 → _approach_synthesis_weights ----
    "conversion.approach_synthesis.social": 0.40,
    "conversion.approach_synthesis.explore": 0.35,
    "conversion.approach_synthesis.urgency": 0.25,

    # ---- 消力反馈系数 → _quench_feedback_weights ----
    "conversion.quench_feedback.quench_rate": 0.25,
    "conversion.quench_feedback.approach_release": 0.30,
    "conversion.quench_feedback.avoid_release": 0.30,
    "conversion.quench_feedback.somatic_comfort": 0.15,

    # ---- 失败代谢副作用 → _failure_metabolite_weights ----
    "conversion.failure_metabolite.approach_suppress": 0.15,
    "conversion.failure_metabolite.avoid_increase": 0.12,
    "conversion.failure_metabolite.curiosity_suppress": 0.10,
    "conversion.failure_metabolite.somatic_damage": 0.08,

    # ---- 冲突→未解决转化 → _conflict_to_unresolved_weights ----
    "conversion.conflict_to_unresolved.conflict_rate": 0.04,
    "conversion.conflict_to_unresolved.unresolved_decay": 0.98,
    "conversion.conflict_to_unresolved.introspection_gain": 1.5,

    # ---- 情绪→趋近/回避调制 → _emotion_drive_modulation ----
    "conversion.emotion_drive_mod.approach.joy": 0.15,
    "conversion.emotion_drive_mod.approach.anger": 0.25,
    "conversion.emotion_drive_mod.approach.excitement": 0.20,
    "conversion.emotion_drive_mod.approach.sadness": -0.20,
    "conversion.emotion_drive_mod.approach.anxiety": -0.10,
    "conversion.emotion_drive_mod.avoid.fear": 0.30,
    "conversion.emotion_drive_mod.avoid.disgust": 0.35,
    "conversion.emotion_drive_mod.avoid.anxiety": 0.15,
    "conversion.emotion_drive_mod.avoid.anger": -0.20,

    # ---- 词汇习得 → _vocab_acquisition_params ----
    "conversion.vocab_acquisition.min_comprehension": 0.3,
    "conversion.vocab_acquisition.exposure_per_hit": 0.2,
    "conversion.vocab_acquisition.ask_threshold": 1.0,
    "conversion.vocab_acquisition.exposure_decay": 0.99,
    "conversion.vocab_acquisition.max_asks_per_tick": 1,

    # ---- 重复递减 → _repetition_decay_params ----
    "conversion.repetition_decay.decay_per_use": 0.15,
    "conversion.repetition_decay.recovery_rate": 0.02,
    "conversion.repetition_decay.floor": 0.20,
    "conversion.repetition_decay.window_ticks": 200,

    # ---- 回应压力 → _response_pressure_params ----
    "conversion.response_pressure.coefficient": 0.03,
    "conversion.response_pressure.min_comprehension": 0.3,

    # ---- 反馈回路 → _feedback_params ----
    "conversion.feedback_loop.acute_boost_scale": 0.05,
    "conversion.feedback_loop.chronic_threshold": 5,
    "conversion.feedback_loop.chronic_drift_rate": 0.002,
    "conversion.feedback_loop.chronic_signal_decay": 0.9,
    "conversion.feedback_loop.chronic_tick_decay": 0.98,
    "conversion.feedback_loop.chronic_min_quench": 0.1,
    "conversion.feedback_loop.weight_ceiling": 0.80,
    "conversion.feedback_loop.weight_floor": 0.05,
}


# ============================================================================
# 合并为全局默认参数表
# ============================================================================

PARAM_DEFAULTS: Dict[str, Any] = {
    "thresholds": THRESHOLDS,
    "drives": DRIVES,
    "mechanisms": MECHANISMS,
    "dynamics": DYNAMICS,
    "_system": _SYSTEM,
    "connection": CONNECTION,
    "experience": EXPERIENCE,
    "coherence": COHERENCE,
    "observation": OBSERVATION,
    "emotion_particle": EMOTION_PARTICLE,
    "emotion_decay": EMOTION_DECAY,
    "emotion_projection": EMOTION_PROJECTION,
    "emotion": EMOTION,
    "language": LANGUAGE,
    "conversion": CONVERSION,
}


# ============================================================================
# 绝对禁止的归一化模式（下游模块必须遵守）
# ============================================================================

"""
【强制规范】下游参数消费方式：

以下类型的参数：
    - *sensitivity 参数（如 drive_sensitivity、pain_sensitivity）
    - module_weights.* 参数
    - 任何以 _weight、_scale、_multiplier 为后缀的参数

正确用法：
    signal = raw_signal * sensitivity_param

错误用法（严禁）：
    weighted = signal * weight_a
    total = weighted + signal_b * weight_b
    normalized = total / (weight_a + weight_b)      ← 严禁归一化

原因：归一化会破坏参数的非线性叠加效应，违背 V4 "不做归一化" 原则。
"""
