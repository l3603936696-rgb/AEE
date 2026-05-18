"""实体状态模块 — EntityState、持久化、全局单例

从 entity_zero_iteration.py 拆分。所有相对导入保持不变。
"""

import asyncio
import copy
import json
import logging
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

# ============================================================================
# 持久化路径
# ============================================================================

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
ENTITY_CORE_PATH = DATA_DIR / "entity_core.json"

from .memory_hub import (
    ExperienceLog,
    StateSnapshot,
    log_experience_with_context,
    execute_sleep_cycle,
    get_topology_metrics,
    calculate_memory_pressure_from_topology,
    build_episode,
    write_episode_async,
)
from .memory_hub.insula_hub import compute_somatic_signals as _compute_somatic_signals
from .core import emerge_behavior as _emerge_behavior, build_system_prompt as _build_system_prompt, derive_rendering_params as _derive_rendering_params
from .core.action_dispatcher import dispatch_async_action as _dispatch_async_action, select_primitive_candidate as _select_primitive_candidate
from .core.entity_core import EntityCore


# ---- v11.2 逐字段预测误差计算 ----

def _compute_prediction_error_map(entity: Any, pre_state: Dict[str, float]) -> Dict[str, float]:
    """
    计算逐字段预测误差 = actual_delta - predicted_delta。

    在 Step 12 快照记录时调用，post_state 来自 entity.to_state_snapshot()，
    prediction 来自 Step 8.3b 写入 entity._last_prediction。

    返回 {field: error}，错误=0 的字段不包含在结果中（节省空间）。
    """
    try:
        prediction = getattr(entity, "_last_prediction", {})
        if not prediction:
            return {}

        post_state = entity.to_state_snapshot() if hasattr(entity, "to_state_snapshot") else {}
        if not post_state:
            return {}

        error_map: Dict[str, float] = {}
        for field, predicted in prediction.items():
            pre_val = float(pre_state.get(field, 0.0))
            post_val = float(post_state.get(field, pre_val))
            actual = post_val - pre_val
            error = round(actual - predicted, 5)
            if abs(error) > 0.0001:  # 过滤纯零
                error_map[field] = error

        return error_map
    except Exception:
        return {}


def _build_experience_log(
    output_text: Optional[str],
    decision: Dict[str, Any],
    semantic_packet_biased: Dict[str, Any],
    concept_tags: List[Any],
) -> ExperienceLog:
    """
    从管线输出构造 ExperienceLog（供异步经验沉淀使用）。

    参数：
        output_text          : 生成的回复文本
        decision             : 裁决输出
        semantic_packet_biased : 偏置后的语义包
        concept_tags         : 概念标签列表

    返回：
        ExperienceLog : TetraMem 适配器所需的经验日志结构
    """
    content = output_text or ""
    tags = [t.get("tag", "") for t in concept_tags if isinstance(t, dict)]
    # 从决策添加标签
    action = decision.get("action_type", "")
    if action:
        tags.append(f"action:{action}")
    # 高情绪标记
    emotion = semantic_packet_biased.get("emotion", 0.0)
    if abs(emotion) > 0.5:
        tags.append("high_emotion")
    # 失败决策标记
    if decision.get("was_override"):
        tags.append("failed_decision")

    weight = float(decision.get("priority", 0.5))
    if abs(emotion) > 0.7:
        weight *= 1.2

    return ExperienceLog(content=content, tags=tags, weight=min(weight, 1.0))
from .world_model_update import (
    run_update_cycle as _wmu_run_update_cycle,
    induct_only as _wmu_induct_only,
    decay_only as _wmu_decay_only,
    verify_only as _wmu_verify_only,
    merge_only as _wmu_merge_only,
    CycleStats as _WMUCycleStats,
)
from .parameter_system.access import create_snapshot, get_param, apply_staged, stage_changes
from .parameter_system.snapshot import ParameterSnapshot

from .semantic.semantic_understanding import analyze_semantic
from .memory_bias.memory_bias import apply_memory_bias
from .concept_tags.concept_tags import generate_concept_tags
from .world_model_reader.world_model_reader import query_world_model
from .drive_system.drive_system import compute_drive_vector
from .thinking_system.thinking_system import think as thinking_think
from .decision_system.decision_system import perceive_all as _perceive_all, DEFAULT_PARAMS as DECISION_DEFAULT_PARAMS
from .decision_system.submodules.web_search import (
    drain_pending_searches,
    clear_pending_searches,
)
from .intent_encoder.intent_encoder import encode_intent
from .output_layer.output_layer import generate_response
from .state_update.update_engine import update_state
from .state_update.compute_connection import (
    compute_connection_depth,
    compute_connection_depth_ex,
    compute_loneliness_target,
    compute_loneliness_target_ex,
)
from .state_update.compute_coherence import append_delta as append_coherence_delta
from .state_update import reset_info_queue
from .observation.behavior_trace import (
    build_connection_trace,
    build_loneliness_trace,
    compute_trend,
    compute_profile,
    _infer_loneliness_reason,
)
from .observation.counterfactual_probe import run_counterfactual_probe
from .observation.probe_logger import get_probe_logger
from .emotion_system import (
    ParticleField,
    ProjectionController,
    DecayEngine,
    InsightWriter,
    compute_emotions,
)
from .language_system import (
    QuenchingTracker,
    StrategyMap,
    ThermalController,
    MirrorLearner,
    FiveRightsController,
    SemanticAnalyzer,
    CandidateGenerator,
    LinguisticAbundanceMonitor,
)
from .behavior_profiler import BehaviorProfiler


logger = logging.getLogger(__name__)


# ============================================================================
# 行为涌现适配器（兼容层）
# ============================================================================


class _CoreWrapper:
    """
    将管线内的 EntityState 适配为 core/emergent_behavior.emerge_behavior() 所需接口。

    支持两种输入：
        - dict: 旧模式，直接取 key
        - EntityCore 实例：直接透传属性访问
    """
    __slots__ = ("_state", "_wm_rules", "_snapshots", "_is_entity_core")

    def __init__(self, state: Any, wm_rules: List[Any], snapshots: List[Any]) -> None:
        self._is_entity_core = not isinstance(state, dict)
        self._state = state  # dict 或 EntityCore
        self._wm_rules = wm_rules
        self._snapshots = snapshots

    def take_snapshot(self) -> Dict[str, Any]:
        if self._is_entity_core:
            return self._state.take_snapshot()
        return dict(self._state)

    @property
    def target_locked(self) -> str:
        if self._is_entity_core:
            return getattr(self._state, "target_locked", "none")
        return str(self._state.get("target_locked", "none"))

    @property
    def energy(self) -> float:
        if self._is_entity_core:
            return float(getattr(self._state, "energy", 0.8))
        return float(self._state.get("energy", 0.8))

    @property
    def loneliness(self) -> float:
        if self._is_entity_core:
            return float(getattr(self._state, "loneliness", 0.3))
        return float(self._state.get("loneliness", 0.3))

    @property
    def unresolved(self) -> float:
        if self._is_entity_core:
            return float(getattr(self._state, "unresolved", 0.2))
        return float(self._state.get("unresolved", 0.2))

    @property
    def fatigue(self) -> float:
        if self._is_entity_core:
            return float(getattr(self._state, "fatigue", 0.1))
        return float(self._state.get("fatigue", 0.1))

    @property
    def info_gap(self) -> float:
        if self._is_entity_core:
            return float(getattr(self._state, "info_gap", 0.5))
        return float(self._state.get("info_gap", 0.5))

    @property
    def somatic_tone(self) -> float:
        if self._is_entity_core:
            return float(getattr(self._state, "somatic_tone", 0.0))
        return float(self._state.get("somatic_tone", 0.0))

    @property
    def danger_level(self) -> float:
        if self._is_entity_core:
            return float(getattr(self._state, "danger_level", 0.0))
        return float(self._state.get("danger_level", 0.0))

    @property
    def approach_drive(self) -> float:
        if self._is_entity_core:
            return float(getattr(self._state, "approach_drive", 0.0))
        return float(self._state.get("approach_drive", 0.0))

    @property
    def avoid_drive(self) -> float:
        if self._is_entity_core:
            return float(getattr(self._state, "avoid_drive", 0.0))
        return float(self._state.get("avoid_drive", 0.0))

    @property
    def stress(self) -> float:
        if self._is_entity_core:
            return float(getattr(self._state, "stress", 0.1))
        return float(self._state.get("stress", 0.1))

    @property
    def pending_surprises_count(self) -> int:
        """pending_surprises 数量（供 emergent_behavior 使用）。"""
        ps = getattr(self._state, "pending_surprises", [])
        if not isinstance(ps, list):
            return 0
        return len(ps)

    @property
    def last_action_result(self) -> Dict[str, Any]:
        """上次异步动作的执行结果（成功/失败反馈）。"""
        if self._is_entity_core:
            return getattr(self._state, "_last_action_result", {"success": None, "detail": ""})
        return self._state.get("_last_action_result", {"success": None, "detail": ""})

    @property
    def time_since_last_social(self) -> float:
        if self._is_entity_core:
            return float(getattr(self._state, "time_since_last_social", 0.0))
        return float(self._state.get("time_since_last_social", 0.0))

    @property
    def time_since_last_info(self) -> float:
        if self._is_entity_core:
            return float(getattr(self._state, "time_since_last_info", 0.0))
        return float(self._state.get("time_since_last_info", 0.0))

    @property
    def curiosity(self) -> float:
        if self._is_entity_core:
            return float(getattr(self._state, "curiosity", 0.5))
        return float(self._state.get("curiosity", 0.5))

    @property
    def failure_metabolite(self) -> float:
        if self._is_entity_core:
            return float(getattr(self._state, "failure_metabolite", 0.0))
        # EntityState has this as a field
        return float(getattr(self._state, "failure_metabolite", 0.0))

    @property
    def pending_failures(self) -> list:
        return getattr(self._state, "pending_failures", [])

    @property
    def boredom(self) -> float:
        if self._is_entity_core:
            return float(getattr(self._state, "boredom", 0.2))
        return float(self._state.get("boredom", 0.2))

    @property
    def last_action_timestamp(self) -> float:
        """最近一次主动行动时间（epoch 秒），供触发器冷却检查用。"""
        if self._is_entity_core:
            return float(getattr(self._state, "last_action_timestamp", 0.0))
        return float(self._state.get("last_action_timestamp", 0.0))

    @property
    def consecutive_reaches_without_response(self) -> int:
        """连续敲门未得到回应的次数。"""
        if self._is_entity_core:
            return int(getattr(self._state, "consecutive_reaches_without_response", 0))
        return int(self._state.get("consecutive_reaches_without_response", 0))

    @property
    def _forced_action(self) -> Optional[str]:
        """强制动作类型（测试场景用）。"""
        if self._is_entity_core:
            return getattr(self._state, "_forced_action", None)
        return None

    @property
    def _last_prediction_error(self) -> float:
        if self._is_entity_core:
            return float(getattr(self._state, "_last_prediction_error", 0.0))
        return float(self._state.get("_last_prediction_error", 0.0))

    @property
    def wm_rules(self) -> List[Any]:
        if self._is_entity_core:
            return getattr(self._state, "wm_rules", self._wm_rules)
        return self._wm_rules

    @property
    def snapshots(self) -> List[Any]:
        if self._is_entity_core:
            return getattr(self._state, "snapshots", self._snapshots)
        return self._snapshots


def _make_core_wrapper(entity_or_state: Any):
    """
    构建 _CoreWrapper 实例。

    参数：
        entity_or_state : EntityCore 实例 或 dict
    """
    if hasattr(entity_or_state, "wm_rules"):
        return _CoreWrapper(
            entity_or_state,
            entity_or_state.wm_rules,
            getattr(entity_or_state, "snapshots", [])[-10:],
        )
    return _CoreWrapper(
        entity_or_state,
        entity_or_state.get("wm_rules", []),
        entity_or_state.get("snapshots", [])[-10:],
    )



@dataclass
class PipelineTrace:
    """同步管线执行追踪"""
    step: str = ""
    elapsed_ms: float = 0.0
    ok: bool = True
    data: Dict[str, Any] = field(default_factory=dict)
    error: str = ""


@dataclass
class EntityState:
    """
    实体内核状态。

    跨轮次持久化，包含：
    - 当前内部状态（energy, fatigue 等）
    - 已有的世界模型规律列表
    - 最近 N 轮的经验快照（用于世界模型归纳）
    - 记忆上下文（用于记忆偏置）
    - tick 计数器
    - 上次更新时间戳
    """
    # 内部状态向量
    energy: float = 0.8
    loneliness: float = 0.3
    loneliness_core: float = 0.2
    loneliness_surface: float = 0.1
    unresolved: float = 0.2
    boredom: float = 0.2
    fatigue: float = 0.1
    stress: float = 0.1
    relief_debt: float = 0.0
    pain: float = 0.0
    info_gap: float = 0.5

    # v3 细菌主体新增字段
    somatic_tone: float = 0.0    # 躯体基调 [-1, 1]
    danger_level: float = 0.0    # 当前危险感 [0, 1]
    approach_drive: float = 0.0   # 趋近驱动 [0, 1]（v11: 加权合成）
    avoid_drive: float = 0.0      # 回避驱动 [0, 1]

    # v11 子驱动力分家（独立注入源 + 独立衰减 + 独立拮抗）
    approach_social: float = 0.0   # 社交趋近: loneliness, sadness, preference(外向)
    approach_explore: float = 0.0  # 探索趋近: curiosity, info_hunger, boredom, world_model SEEK
    approach_urgency: float = 0.0  # 紧迫趋近: temporal_pressure, mainline_constraint

    # v11 消力效率滚动均值（boredom 独立激活源）
    quenching_eff_rolling: float = 0.5

    # v11 训练随机化开关（手动控制，遍历状态空间积累词汇）
    _training_randomize: bool = False
    _freeze_state: bool = False          # v11.4: 手动训练时冻结状态，跳过 TrainingMC + AntiLock

    # 辅助状态（用于驱动力计算）
    time_since_last_info: float = 0.0
    time_since_last_social: float = 0.0
    external_change_rate: float = 0.0

    # 世界模型
    wm_rules: List[Dict[str, Any]] = field(default_factory=list)

    # 经验快照（最近 N 轮）
    snapshots: List[Dict[str, Any]] = field(default_factory=list)
    max_snapshots: int = 50

    # 记忆上下文（最近 N 条）
    memory_context: List[Dict[str, Any]] = field(default_factory=list)
    max_memory_context: int = 20

    # tick 计数
    tick: int = 0
    created_at: float = field(default_factory=time.time)
    last_update_time: float = field(default_factory=time.time)

    # 时间锚点（用于沉默期注入）
    last_interaction_timestamp: float = 0.0  # epoch 秒
    last_interaction_context: Dict[str, Any] = field(default_factory=dict)
    # 结构: {"emotion": float, "intensity": float, "action_type": str}

    # 运行时标记：哪些维度主要由沉默时间注入（不持久化，每轮重算）
    _time_injected_fields: set = field(default_factory=set)

    # 行为冷却追踪（持久化）
    last_action_timestamp: float = 0.0       # epoch 秒，最近一次主动行动时间
    consecutive_reaches_without_response: int = 0  # 连续敲门未得到回应的次数

    # pending_surprises（未处理的意外信号队列，stress 生命周期）
    pending_surprises: list = field(default_factory=list)

    # pending_failures（工具执行失败队列，V4 新增）
    pending_failures: list = field(default_factory=list)

    # behavior_rules（行为规则，V6 新增）
    # 从 snapshot 自动归纳，含 effect / context_mean / strength
    behavior_rules: list = field(default_factory=list)

    # failure_metabolite（失败代谢物，V5 新增）
    # 每次失败累积，随时间衰减。连续抑制 approach_drive，
    # 迫使她撞墙后自然转向——不是决策，是物理约束。像乳酸。
    failure_metabolite: float = 0.0

    # ---- v7.0 语言系统持久化字段（to_dict/from_dict 序列化）----
    _quenching_data: dict = field(default_factory=dict)          # QuenchingTracker
    _strategy_map_data: dict = field(default_factory=dict)       # StrategyMap
    _thermal_data: dict = field(default_factory=dict)            # ThermalController
    _mirror_data: dict = field(default_factory=dict)             # MirrorLearner
    _five_rights_data: dict = field(default_factory=dict)        # FiveRightsController
    _semantic_analyzer_data: dict = field(default_factory=dict)  # SemanticAnalyzer (stateless, placeholder)
    _candidate_gen_data: dict = field(default_factory=dict)      # CandidateGenerator (stateless, placeholder)
    _behavior_profiler_data: dict = field(default_factory=dict)  # BehaviorProfiler (stateless, placeholder)
    _decay_engine_data: dict = field(default_factory=dict)       # DecayEngine (stateless, placeholder)

    # ---- v10.0 体感帮助事件 ----
    # 每次她准确描述自己的状态获得帮助后，这里记录一个可观测事件
    # 让她能归因"我说了X → 系统识别了 → 我变好了"
    _last_help_event: Optional[Dict[str, Any]] = None
    # v10.0 元认知事件
    _last_meta_event: Optional[Dict[str, Any]] = None

    # ---- v10.0/v11.0 情绪系统持久化字段 ----
    # 厌倦双根源（独立衰减）
    boredom_despair: float = 0.0   # 绝望性倦怠
    boredom_futility: float = 0.0   # 徒劳性倦怠
    # 情绪粒子场状态
    emotion_particle_field: dict = field(default_factory=dict)
    # 各层投影累计值
    emotion_accumulators: dict = field(default_factory=dict)
    # 上次情绪更新的 unix timestamp
    last_emotion_tick: float = field(default_factory=time.time)

    # ---- 脐带脱落标志（v7.0 语言系统）----
    _umbilical_detached: bool = False  # True=已脱离外部辅助，切换自我积累

    # ---- v11.3 永久词汇表：解锁后不因记录挤出而丢失 ----
    _unlocked_vocabulary: list = field(default_factory=list)  # 永久解锁的 ≤2 字词

    # ---- v11.3 体感聚类权重：长词修正锚点影响力 ----
    _cluster_weights: dict = field(default_factory=dict)  # {anchor_word: cumulative_weight}

    # ---- 趋近驱动合成权重：初始倾向，可随经验漂移 ----
    _approach_synthesis_weights: dict = field(default_factory=lambda: {
        "social": 0.40, "explore": 0.35, "urgency": 0.25,
    })

    # ---- 消力反馈系数：表达成功后各维度的释放比例 ----
    _quench_feedback_weights: dict = field(default_factory=lambda: {
        "quench_rate": 0.25,
        "approach_release": 0.3,
        "avoid_release": 0.3,
        "somatic_comfort": 0.15,
    })

    # ---- 失败代谢副作用系数 ----
    _failure_metabolite_weights: dict = field(default_factory=lambda: {
        "approach_suppress": 0.15,
        "avoid_increase": 0.12,
        "curiosity_suppress": 0.10,
        "somatic_damage": 0.08,
    })

    # ---- 冲突→未解决 转化系数 ----
    _conflict_to_unresolved_weights: dict = field(default_factory=lambda: {
        "conflict_rate": 0.04,
        "unresolved_decay": 0.98,
        "introspection_gain": 1.5,
    })

    # ---- 情绪→趋近/回避 调制矩阵 ----
    _emotion_drive_modulation: dict = field(default_factory=lambda: {
        "approach": {
            "joy": 0.15, "anger": 0.25, "excitement": 0.20,
            "sadness": -0.20, "anxiety": -0.10,
        },
        "avoid": {
            "fear": 0.30, "disgust": 0.35, "anxiety": 0.15,
            "anger": -0.20,
        },
    })

    # ---- 词汇习得参数 ----
    _vocab_acquisition_params: dict = field(default_factory=lambda: {
        "min_comprehension": 0.3,
        "exposure_per_hit": 0.2,
        "ask_threshold": 1.0,
        "exposure_decay": 0.99,
        "max_asks_per_tick": 1,
    })
    _word_exposure_tracker: dict = field(default_factory=dict)

    # ---- 重复表达递减参数 ----
    _repetition_decay_params: dict = field(default_factory=lambda: {
        "decay_per_use": 0.15,
        "recovery_rate": 0.02,
        "floor": 0.20,
        "window_ticks": 200,
    })

    # ---- 思考系统：待解决问题缓冲 ----
    _pending_questions: list = field(default_factory=list)

    # ---- 姐妹通道配置 ----
    _sibling_channel: dict = field(default_factory=lambda: {
        "enabled": False,
        "channel_dir": "",
        "self_name": "",
        "peer_name": "",
    })

    # ---- 对话回应压力参数（负反馈：听懂了但不回 → 不舒服）----
    _response_pressure_params: dict = field(default_factory=lambda: {
        "coefficient": 0.03,   # comprehension → unresolved 的转化率（轻微）
        "min_comprehension": 0.3,  # 低于此理解度不产生压力
    })

    # ---- 反馈回路参数 ----
    _feedback_params: dict = field(default_factory=lambda: {
        "acute_boost_scale": 0.05,
        "chronic_threshold": 5,
        "chronic_drift_rate": 0.002,
        "chronic_signal_decay": 0.9,
        "chronic_tick_decay": 0.98,
        "chronic_min_quench": 0.1,
        "weight_ceiling": 0.80,
        "weight_floor": 0.05,
    })
    _chronic_feedback_tracker: dict = field(default_factory=lambda: {
        "social": 0.0, "explore": 0.0, "urgency": 0.0,
    })

    # ---- 核心情绪维度（v10.0 十个核心情绪）----
    joy: float = 0.0
    excitement: float = 0.0
    serenity: float = 0.0
    anger: float = 0.0
    fear: float = 0.0
    sadness: float = 0.0
    disgust: float = 0.0
    anxiety: float = 0.0
    surprise: float = 0.0
    curiosity: float = 0.5    # v11.5 好奇驱力（认知探索）

    # 长时行为偏置（进化层）：跨时间尺度的行为风格轨迹
    # 不代表"目标"，只代表"倾向"——受历史行为效果累积影响
    # explore: 探索倾向，connect: 连接倾向，introspect: 内省倾向，build: 构建倾向
    long_term_bias: Dict[str, float] = field(default_factory=lambda: {
        "explore": 0.0,
        "connect": 0.0,
        "introspect": 0.0,
        "build": 0.0,
    })

    # recent_deltas（coherence 状态变化缓存，不持久化）
    # 惰性初始化：管线在 Step 8.4 按需创建（maxlen 由参数决定）
    recent_deltas: Any = field(default=None)

    # observation_buffer（观测缓存区，不持久化，重启后清空）
    # 每轮追加一条 tick-record，最大保留50条
    observation_buffer: Any = field(default=None)

    # ---- 行为身份 & 进展追踪（v4 bias 系统）----
    # unresolved 来源：记录 unresolved 是外部触发的还是自己生成的
    # 外部（用户/环境触发）→ 解决它权重高
    # 自我生成 → 解决它权重低（防止 self-generated task loop）
    unresolved_source: str = "external"   # "external" | "self_generated"

    # self_generated_ratio（最近 50 tick 中 self-generated unresolved 占比）
    # 用于 penalty 判断
    _unresolved_sources: list = field(default_factory=lambda: [])

    # identity_signal：行为签名相似度（v4 新增）
    # 当前行为分布 vs 长期行为签名
    # 高相似度 → 行为一致 → identity 强
    # 低相似度 → 行为漂移 → identity 弱
    # identity 强时 bias 更新幅度放大；弱时抑制（防止乱变）
    behavior_signature: Dict[str, int] = field(default_factory=lambda: {
        "explore": 0, "seek": 0, "avoid": 0, "comfort": 0, "idle": 0, "rest": 0,
    })
    # 历史行为（最近 N tick，用于计算当前分布）
    _recent_actions: list = field(default_factory=list)

    def to_state_snapshot(self) -> Dict[str, float]:
        """转换为 state_snapshot 字典"""
        return {
            "energy": self.energy,
            "loneliness": self.loneliness,
            "loneliness_core": self.loneliness_core,       # v11.4
            "loneliness_surface": self.loneliness_surface,  # v11.4
            "unresolved": self.unresolved,
            "boredom": self.boredom,
            "fatigue": self.fatigue,
            "stress": self.stress,
            "relief_debt": self.relief_debt,
            "pain": self.pain,
            "info_gap": self.info_gap,
            "time_since_last_info": self.time_since_last_info,
            "time_since_last_social": self.time_since_last_social,
            "external_change_rate": self.external_change_rate,
            "tick": self.tick,
            # v3 细菌主体字段
            "somatic_tone": self.somatic_tone,
            "danger_level": self.danger_level,
            "approach_drive": self.approach_drive,
            "avoid_drive": self.avoid_drive,
            # v11 子驱动力分家
            "approach_social": self.approach_social,
            "approach_explore": self.approach_explore,
            "approach_urgency": self.approach_urgency,
            "quenching_eff_rolling": self.quenching_eff_rolling,
            # v11 训练随机化开关
            "_training_randomize": self._training_randomize,
            # v11.4 手动训练状态冻结（跳过 TrainingMC + AntiLock）
            "_freeze_state": self._freeze_state,
            # 长时偏置（供 BP 评分用）
            "long_term_bias": dict(self.long_term_bias),
            # 行为签名（identity signal 计算用）
            "behavior_signature": dict(self.behavior_signature),
            "unresolved_source": self.unresolved_source,
            # v10.0 厌倦双根源
            "boredom_despair": getattr(self, "boredom_despair", 0.0),
            "boredom_futility": getattr(self, "boredom_futility", 0.0),
            # v11.5 情绪维度（锚点表匹配需要）
            "anxiety": self.anxiety,
            "fear": self.fear,
            "joy": self.joy,
            "sadness": self.sadness,
            "anger": self.anger,
            "serenity": self.serenity,
            "disgust": self.disgust,
            "excitement": self.excitement,
            "curiosity": self.curiosity,   # v11.5
            # v11.0 情绪粒子场状态（供 output_layer 调制）
            "emotion_particle_field": getattr(self, "emotion_particle_field", {}),
            # v10.0 体感帮助事件（可观测的归因信号）
            "_last_help_event": self._last_help_event,
            "_last_meta_event": self._last_meta_event,
        }

    def take_snapshot(self) -> Dict[str, float]:
        """快照接口（与 to_state_snapshot 等价，供 emergent_behavior 使用）"""
        return self.to_state_snapshot()

    def add_snapshot(self, snap: Dict[str, Any]) -> None:
        """追加经验快照，自动截断"""
        self.snapshots.append(snap)
        if len(self.snapshots) > self.max_snapshots:
            self.snapshots = self.snapshots[-self.max_snapshots:]

    def add_memory_sample(self, sample: Dict[str, Any]) -> None:
        """追加记忆样本"""
        self.memory_context.append(sample)
        if len(self.memory_context) > self.max_memory_context:
            self.memory_context = self.memory_context[-self.max_memory_context:]

    def update_behavior_signature(self, action_type: str) -> float:
        """
        更新行为签名并返回 identity_signal（0~1）。

        identity_signal = cosine_similarity(current_distribution, behavior_signature)
        - 1.0 = 当前行为分布完全匹配历史签名（强一致性）
        - 0.0 = 完全漂移（乱变）
        """
        if not action_type:
            return 0.5

        # 更新近期行为记录
        self._recent_actions.append(action_type)
        if len(self._recent_actions) > 50:
            self._recent_actions = self._recent_actions[-50:]

        # 更新长期签名（慢速移动平均）
        sig = self.behavior_signature
        if action_type in sig:
            sig[action_type] = sig[action_type] + 1
        else:
            sig[action_type] = 1

        # 计算 identity_signal：当前分布 vs 长期签名
        if not self._recent_actions:
            return 0.5
        total_sig = sum(sig.values())
        if total_sig == 0:
            return 0.5

        # 当前分布
        curr_counts: Dict[str, float] = {}
        for a in self._recent_actions:
            curr_counts[a] = curr_counts.get(a, 0) + 1
        total_curr = len(self._recent_actions)

        # cosine similarity
        dot = sum(
            (curr_counts.get(k, 0) / total_curr) * (sig.get(k, 0) / total_sig)
            for k in set(list(sig.keys()) + list(curr_counts.keys()))
        )
        curr_mag = math.sqrt(sum((v / total_curr) ** 2 for v in curr_counts.values()))
        sig_mag = math.sqrt(sum((v / total_sig) ** 2 for v in sig.values()))
        if curr_mag == 0 or sig_mag == 0:
            return 0.5
        return max(0.0, min(1.0, dot / (curr_mag * sig_mag)))

    def adjust(self, key: str, delta: float) -> None:
        """
        通过 delta 调整状态变量（v3 细菌主体核心接口）。

        所有状态变量 clamp 到 [0.0, 1.0]，
        somatic_tone clamp 到 [-1.0, 1.0]。
        v11.4: loneliness 写入 loneliness_surface（扰动影响表层），
               然后同步 loneliness = core + surface。
        """
        if not hasattr(self, key):
            return
        if key == "loneliness":
            # 扰动/噪声影响表层假孤独
            self.loneliness_surface = max(0.0, min(1.0, self.loneliness_surface + delta))
            self._sync_loneliness()
            return
        current = getattr(self, key)
        if key == "somatic_tone":
            new_val = max(-1.0, min(1.0, current + delta))
        else:
            new_val = max(0.0, min(1.0, current + delta))
        setattr(self, key, new_val)

    def _sync_loneliness(self) -> None:
        """v11.4: 同步 loneliness = core + surface（上限 1.0）。"""
        self.loneliness = min(1.0, self.loneliness_core + self.loneliness_surface)

    # =========================================================================
    # 失败感知接口（V4，与 EntityCore 同步）
    # =========================================================================

    def register_failure(self, failure_record) -> None:
        """记录一次工具执行失败。"""
        self.pending_failures.append(failure_record)
        # 代谢物积累
        self.failure_metabolite = min(1.0, self.failure_metabolite + 0.12)
        self.adjust("somatic_tone", -failure_record.severity * 0.08
                    - min(0.15, len(self.pending_failures) * 0.02))
        if len(self.pending_failures) >= 3:
            self.adjust("danger_level", 0.03)
        self.adjust("unresolved", 0.04)

    def resolve_failure(self, failure_index: int, fix_success: bool) -> None:
        """解决一个挂起的失败。"""
        if failure_index < 0 or failure_index >= len(self.pending_failures):
            return
        self.pending_failures.pop(failure_index)
        # 代谢物部分清除
        self.failure_metabolite = max(0.0, self.failure_metabolite - 0.15)
        if fix_success:
            self.adjust("somatic_tone", 0.06)
            self.adjust("unresolved", -0.08)
        if len(self.pending_failures) == 0:
            self.adjust("danger_level", -0.05)

    def has_pending_failures(self) -> bool:
        return len(self.pending_failures) > 0

    def recent_failure_types(self) -> list:
        return [getattr(f, "error_type", "") if not isinstance(f, dict)
                else f.get("error_type", "")
                for f in self.pending_failures[-10:]]

    # =========================================================================
    # 持久化（EntityCore 持久化接口移植）
    # =========================================================================

    def persist_to_file(self, path: Optional[Path] = None) -> None:
        """
        将完整 EntityState 状态序列化到文件（跨进程持久化）。

        持久化内容：
            - 所有状态字段（energy, loneliness 等）
            - wm_rules（世界模型规律）
            - snapshots（最近 50 轮状态快照）
            - memory_context（最近 20 条记忆上下文）
            - tick / created_at / last_update_time（元数据）
        """
        path = path or ENTITY_CORE_PATH
        try:
            data = {
                "energy": self.energy,
                "loneliness": self.loneliness,
                "loneliness_core": self.loneliness_core,       # v11.4
                "loneliness_surface": self.loneliness_surface,  # v11.4
                "unresolved": self.unresolved,
                "boredom": self.boredom,
                "fatigue": self.fatigue,
                "stress": self.stress,
                "relief_debt": self.relief_debt,
                "pain": self.pain,
                "info_gap": self.info_gap,
                "time_since_last_info": self.time_since_last_info,
                "time_since_last_social": self.time_since_last_social,
                "external_change_rate": self.external_change_rate,
                "somatic_tone": self.somatic_tone,
                "danger_level": self.danger_level,
                "approach_drive": self.approach_drive,
                "avoid_drive": self.avoid_drive,
                # v11 子驱动力分家
                "approach_social": self.approach_social,
                "approach_explore": self.approach_explore,
                "approach_urgency": self.approach_urgency,
                "quenching_eff_rolling": self.quenching_eff_rolling,
                # v11 训练随机化开关
                "_training_randomize": self._training_randomize,
                "wm_rules": self.wm_rules,
                "snapshots": self.snapshots[-50:],
                "memory_context": self.memory_context[-20:],
                "tick": self.tick,
                "created_at": getattr(self, "created_at", time.time()),
                "last_update_time": self.last_update_time,
                "last_interaction_timestamp": self.last_interaction_timestamp,
                "last_interaction_context": self.last_interaction_context,
                "pending_surprises": self.pending_surprises,
                "long_term_bias": dict(self.long_term_bias),
                "behavior_signature": dict(self.behavior_signature),
                "unresolved_source": self.unresolved_source,
                "last_action_timestamp": getattr(self, "last_action_timestamp", 0.0),
                "consecutive_reaches_without_response": getattr(self, "consecutive_reaches_without_response", 0),
                "pending_failures": [f.to_dict() if hasattr(f, "to_dict") else f for f in self.pending_failures[-20:]],
                "failure_metabolite": self.failure_metabolite,
                "behavior_rules": self.behavior_rules,
                # v7.0 语言系统持久化
                "_umbilical_detached": self._umbilical_detached,
                "_unlocked_vocabulary": list(self._unlocked_vocabulary),  # v11.3 永久词汇表
                "_cluster_weights": dict(self._cluster_weights),        # v11.3 体感聚类权重
                "_approach_synthesis_weights": dict(self._approach_synthesis_weights),
                "_quench_feedback_weights": dict(self._quench_feedback_weights),
                "_failure_metabolite_weights": dict(self._failure_metabolite_weights),
                "_conflict_to_unresolved_weights": dict(self._conflict_to_unresolved_weights),
                "_emotion_drive_modulation": dict(self._emotion_drive_modulation),
                "_vocab_acquisition_params": dict(self._vocab_acquisition_params),
                "_word_exposure_tracker": dict(self._word_exposure_tracker),
                "_repetition_decay_params": dict(self._repetition_decay_params),
                "_response_pressure_params": dict(self._response_pressure_params),
                "_sibling_channel": dict(self._sibling_channel),
                "_pending_questions": list(self._pending_questions),
                "_feedback_params": dict(self._feedback_params),
                "_chronic_feedback_tracker": dict(self._chronic_feedback_tracker),
                "_quenching_data": self._quenching_data,
                "_strategy_map_data": self._strategy_map_data,
                "_thermal_data": self._thermal_data,
                "_mirror_data": self._mirror_data,
                "_five_rights_data": self._five_rights_data,
                "_semantic_analyzer_data": self._semantic_analyzer_data,
                "_candidate_gen_data": self._candidate_gen_data,
                "_behavior_profiler_data": self._behavior_profiler_data,
                "_decay_engine_data": self._decay_engine_data,
                # v10.0/v11.0 情绪系统持久化
                "boredom_despair": self.boredom_despair,
                "boredom_futility": self.boredom_futility,
                "emotion_particle_field": self.emotion_particle_field,
                "emotion_accumulators": self.emotion_accumulators,
                "last_emotion_tick": self.last_emotion_tick,
                # 十个核心情绪
                "joy": self.joy,
                "excitement": self.excitement,
                "serenity": self.serenity,
                "anger": self.anger,
                "fear": self.fear,
                "sadness": self.sadness,
                "disgust": self.disgust,
                "anxiety": self.anxiety,
                "surprise": self.surprise,
                # 阅读品味持久化
                "_reading_taste_log": list(getattr(self, "_reading_taste_log", [])),
                "_taste_evidence": list(getattr(self, "_taste_evidence", [])),
            }
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.debug(f"[EntityState] Persisted to {path}")
        except Exception as e:
            logger.warning(f"[EntityState] persist_to_file failed: {e}")

    def load_from_file(self, path: Optional[Path] = None) -> bool:
        """
        从文件加载持久化的 EntityState 状态。

        参数：
            path : 文件路径，若为 None 使用默认路径

        返回：
            bool : 是否加载成功
        """
        path = path or ENTITY_CORE_PATH
        if not path.exists():
            logger.debug(f"[EntityState] {path} not found, skipping load")
            return False
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)

            self.energy = float(data.get("energy", 0.8))
            # v11.4 双通道孤独：新数据直接读，旧数据按 7:3 拆分
            if "loneliness_core" in data:
                self.loneliness_core = float(data.get("loneliness_core", 0.2))
                self.loneliness_surface = float(data.get("loneliness_surface", 0.1))
                self.loneliness = float(data.get("loneliness", self.loneliness_core + self.loneliness_surface))
            else:
                _old_loneliness = float(data.get("loneliness", 0.3))
                self.loneliness_core = _old_loneliness * 0.7
                self.loneliness_surface = _old_loneliness * 0.3
                self.loneliness = _old_loneliness
            self.unresolved = float(data.get("unresolved", 0.2))
            self.boredom = float(data.get("boredom", 0.2))
            self.fatigue = float(data.get("fatigue", 0.1))
            self.stress = float(data.get("stress", 0.1))
            self.relief_debt = float(data.get("relief_debt", 0.0))
            self.pain = float(data.get("pain", 0.0))
            self.info_gap = float(data.get("info_gap", 0.5))
            self.time_since_last_info = float(data.get("time_since_last_info", 0.0))
            self.time_since_last_social = float(data.get("time_since_last_social", 0.0))
            self.external_change_rate = float(data.get("external_change_rate", 0.0))
            self.somatic_tone = float(data.get("somatic_tone", 0.0))
            self.danger_level = float(data.get("danger_level", 0.0))
            self.approach_drive = float(data.get("approach_drive", 0.0))
            self.avoid_drive = float(data.get("avoid_drive", 0.0))
            # v11 子驱动力分家
            self.approach_social = float(data.get("approach_social", 0.0))
            self.approach_explore = float(data.get("approach_explore", 0.0))
            self.approach_urgency = float(data.get("approach_urgency", 0.0))
            self.quenching_eff_rolling = float(data.get("quenching_eff_rolling", 0.5))
            # v11 训练随机化开关
            self._training_randomize = bool(data.get("_training_randomize", False))
            self.wm_rules = data.get("wm_rules", [])
            self.snapshots = data.get("snapshots", [])
            self.memory_context = data.get("memory_context", [])
            self.tick = int(data.get("tick", 0))
            self.last_update_time = float(data.get("last_update_time", time.time()))
            self.last_interaction_timestamp = float(data.get("last_interaction_timestamp", 0.0))
            self.last_interaction_context = data.get("last_interaction_context", {})
            self.pending_surprises = data.get("pending_surprises", [])
            self.long_term_bias = data.get("long_term_bias", {
                "explore": 0.0, "connect": 0.0, "introspect": 0.0, "build": 0.0,
            })
            self.behavior_signature = data.get("behavior_signature", {
                "explore": 0, "seek": 0, "avoid": 0, "comfort": 0, "idle": 0, "rest": 0,
            })
            self.unresolved_source = data.get("unresolved_source", "external")
            self._unresolved_sources = []   # 运行时重置
            self.pending_failures = data.get("pending_failures", [])
            self.failure_metabolite = float(data.get("failure_metabolite", 0.0))
            self.behavior_rules = data.get("behavior_rules", [])
            self.last_action_timestamp = float(data.get("last_action_timestamp", 0.0))
            self.consecutive_reaches_without_response = int(data.get("consecutive_reaches_without_response", 0))
            # v7.0 语言系统持久化恢复
            self._umbilical_detached = bool(data.get("_umbilical_detached", False))
            self._unlocked_vocabulary = list(data.get("_unlocked_vocabulary", []))  # v11.3
            self._cluster_weights = dict(data.get("_cluster_weights", {}))         # v11.3
            self._approach_synthesis_weights = dict(data.get("_approach_synthesis_weights", {
                "social": 0.40, "explore": 0.35, "urgency": 0.25,
            }))
            self._quench_feedback_weights = dict(data.get("_quench_feedback_weights", {
                "quench_rate": 0.25, "approach_release": 0.3,
                "avoid_release": 0.3, "somatic_comfort": 0.15,
            }))
            self._failure_metabolite_weights = dict(data.get("_failure_metabolite_weights", {
                "approach_suppress": 0.15, "avoid_increase": 0.12,
                "curiosity_suppress": 0.10, "somatic_damage": 0.08,
            }))
            self._conflict_to_unresolved_weights = dict(data.get("_conflict_to_unresolved_weights", {
                "conflict_rate": 0.04, "unresolved_decay": 0.98, "introspection_gain": 1.5,
            }))
            self._emotion_drive_modulation = data.get("_emotion_drive_modulation", {
                "approach": {"joy": 0.15, "anger": 0.25, "excitement": 0.20, "sadness": -0.20, "anxiety": -0.10},
                "avoid": {"fear": 0.30, "disgust": 0.35, "anxiety": 0.15, "anger": -0.20},
            })
            self._vocab_acquisition_params = dict(data.get("_vocab_acquisition_params", {
                "min_comprehension": 0.3, "exposure_per_hit": 0.2,
                "ask_threshold": 1.0, "exposure_decay": 0.99,
                "max_asks_per_tick": 1,
            }))
            self._word_exposure_tracker = dict(data.get("_word_exposure_tracker", {}))
            self._repetition_decay_params = dict(data.get("_repetition_decay_params", {
                "decay_per_use": 0.15, "recovery_rate": 0.02,
                "floor": 0.20, "window_ticks": 200,
            }))
            self._response_pressure_params = dict(data.get("_response_pressure_params", {
                "coefficient": 0.03, "min_comprehension": 0.3,
            }))
            self._sibling_channel = dict(data.get("_sibling_channel", {
                "enabled": False, "channel_dir": "", "self_name": "", "peer_name": "",
            }))
            self._pending_questions = list(data.get("_pending_questions", []))
            self._feedback_params = dict(data.get("_feedback_params", {
                "acute_boost_scale": 0.05, "chronic_threshold": 5,
                "chronic_drift_rate": 0.002, "chronic_signal_decay": 0.9,
                "chronic_tick_decay": 0.98, "chronic_min_quench": 0.1,
                "weight_ceiling": 0.80, "weight_floor": 0.05,
            }))
            self._chronic_feedback_tracker = dict(data.get("_chronic_feedback_tracker", {
                "social": 0.0, "explore": 0.0, "urgency": 0.0,
            }))
            self._quenching_data = data.get("_quenching_data", {})
            self._strategy_map_data = data.get("_strategy_map_data", {})
            self._thermal_data = data.get("_thermal_data", {})
            self._mirror_data = data.get("_mirror_data", {})
            self._five_rights_data = data.get("_five_rights_data", {})
            self._semantic_analyzer_data = data.get("_semantic_analyzer_data", {})
            self._candidate_gen_data = data.get("_candidate_gen_data", {})
            self._behavior_profiler_data = data.get("_behavior_profiler_data", {})
            self._decay_engine_data = data.get("_decay_engine_data", {})
            # v10.0/v11.0 情绪系统持久化恢复
            self.boredom_despair = float(data.get("boredom_despair", 0.0))
            self.boredom_futility = float(data.get("boredom_futility", 0.0))
            self.emotion_particle_field = data.get("emotion_particle_field", {})
            self.emotion_accumulators = data.get("emotion_accumulators", {})
            self.last_emotion_tick = float(data.get("last_emotion_tick", time.time()))
            # 十个核心情绪
            self.joy = float(data.get("joy", 0.0))
            self.excitement = float(data.get("excitement", 0.0))
            self.serenity = float(data.get("serenity", 0.0))
            self.anger = float(data.get("anger", 0.0))
            self.fear = float(data.get("fear", 0.0))
            self.sadness = float(data.get("sadness", 0.0))
            self.disgust = float(data.get("disgust", 0.0))
            self.anxiety = float(data.get("anxiety", 0.0))
            self.surprise = float(data.get("surprise", 0.0))
            # 阅读品味恢复
            self._reading_taste_log = list(data.get("_reading_taste_log", []))
            self._taste_evidence = list(data.get("_taste_evidence", []))

            logger.info(
                f"[EntityState] Loaded from {path} — tick={self.tick}, "
                f"energy={self.energy:.2f}, wm_rules={len(self.wm_rules)}"
            )
            return True
        except Exception as e:
            logger.warning(f"[EntityState] load_from_file failed: {e}")
            return False


# ============================================================================
# 全局信号池 & 实体内核状态（单例）
# ============================================================================

_entity_state_instance: Optional[EntityState] = None


def _recover_from_episodes(entity: EntityState) -> None:
    """
    从 episodes.db 召回最近经验，重建 entity 的来路层。

    重建内容：
        - snapshots：从最近高重要性 episodes 回填状态快照
        - wm_rules：从 episodes 的 semantic_packet_biased 抽取情绪规律
        - memory_context：从 episodes 回填记忆样本

    仅补充 entity 当前没有的来路，不覆盖已有数据。
    """
    try:
        from .memory_hub.episodes_db import get_recent_episodes
    except Exception:
        return

    try:
        episodes = get_recent_episodes(limit=20, min_importance=0.1)
    except Exception:
        return

    if not episodes:
        return

    recovered_snapshots = 0
    recovered_memories = 0

    for ep in episodes:
        # ---- 重建 snapshots ----
        raw_state = getattr(ep, "state_snapshot", None)
        if raw_state and isinstance(raw_state, dict) and "energy" in raw_state:
            snap = dict(raw_state)
            snap["tick_index"] = getattr(ep, "iteration_id", 0)
            snap["timestamp"] = getattr(ep, "timestamp", time.time())
            entity.snapshots.append(snap)
            recovered_snapshots += 1

        # ---- 重建 memory_context ----
        raw_sp = getattr(ep, "semantic_packet_biased", None)
        if raw_sp and isinstance(raw_sp, dict):
            emotion = float(raw_sp.get("emotion", 0.0))
            intent = str(raw_sp.get("intent", "unknown"))
            output_text = getattr(ep, "output_text", "")
            entity.memory_context.append({
                "emotion": emotion,
                "intent": intent,
                "timestamp": getattr(ep, "timestamp", time.time()),
                "content": output_text[:200] if output_text else "",
            })
            recovered_memories += 1

    # 截断到上限
    if entity.snapshots:
        entity.snapshots = entity.snapshots[-entity.max_snapshots:]
    if entity.memory_context:
        entity.memory_context = entity.memory_context[-entity.max_memory_context:]

    if recovered_snapshots > 0 or recovered_memories > 0:
        logger.info(
            f"[EntityState] Recovered from episodes: "
            f"snapshots={recovered_snapshots}, memories={recovered_memories}"
        )


# ============================================================================
# 沉默期时间注入
# ============================================================================

# 沉默积累曲线（锚点：沉默小时数 → 目标值）
LONELINESS_DEFAULT_ANCHORS = ([0.0, 2.0,  6.0,  12.0, 24.0], [0.0, 0.1,  0.4,  0.7,  0.9])
LONELINESS_FAST_ANCHORS   = ([0.0, 2.0,  6.0,  12.0, 24.0], [0.0, 0.2,  0.55, 0.8,  0.95])
LONELINESS_SLOW_ANCHORS   = ([0.0, 2.0,  6.0,  12.0, 24.0], [0.0, 0.05, 0.2,  0.4,  0.65])
BOREDOM_ANCHORS           = ([0.0, 1.0,  3.0,  6.0],          [0.05, 0.2, 0.6, 0.8])
INFO_GAP_ANCHORS          = ([0.0, 2.0,  8.0,  24.0],          [0.0, 0.2, 0.5, 0.85])

SILENCE_INJECTION_MIN_HOURS = 10.0 / 60.0  # 至少沉默 10 分钟才注入


def _interpolate_lookup(x: float, x_anchors: list, y_anchors: list) -> float:
    """内联版 interpolate_lookup（无外部依赖）。"""
    try:
        if not x_anchors or not y_anchors or len(x_anchors) != len(y_anchors) or len(x_anchors) < 2:
            return 0.0
        if x <= x_anchors[0]:
            return max(0.0, min(1.0, y_anchors[0]))
        if x >= x_anchors[-1]:
            return max(0.0, min(1.0, y_anchors[-1]))
        import bisect
        idx = bisect.bisect_right(x_anchors, x)
        x0, x1 = x_anchors[idx - 1], x_anchors[idx]
        y0, y1 = y_anchors[idx - 1], y_anchors[idx]
        if abs(x1 - x0) < 1e-10:
            return max(0.0, min(1.0, y0))
        t = (x - x0) / (x1 - x0)
        return max(0.0, min(1.0, y0 + t * (y1 - y0)))
    except Exception:
        return 0.0


def _apply_silence_injection(entity: EntityState) -> None:
    """
    重启时计算沉默时长，向 entity 注入时间造成的高阶状态偏移。

    仅上调目标维度（max 语义），不影响低于目标值的现有状态。
    标记注入维度供后续恢复阻尼使用。
    """
    now = time.time()
    ts = entity.last_interaction_timestamp

    if ts <= 0.0:
        logger.debug("[SilenceInjection] No prior interaction, skipping")
        return

    silence_seconds = now - ts
    if silence_seconds <= 0.0:
        logger.warning(f"[SilenceInjection] clock skew (silence_seconds={silence_seconds}), skipping")
        return

    silence_hours = silence_seconds / 3600.0

    if silence_hours < SILENCE_INJECTION_MIN_HOURS:
        logger.debug(f"[SilenceInjection] silence_hours={silence_hours:.2f} < threshold, skipping")
        return

    ctx = entity.last_interaction_context or {}
    emotion = float(ctx.get("emotion", 0.0))
    intensity = float(ctx.get("intensity", 0.0))

    # ---- 选择 loneliness 曲线变体 ----
    if emotion > 0.3 and intensity > 0.5:
        lx, ly = LONELINESS_FAST_ANCHORS
        curve = "fast"
    elif emotion < -0.3 and intensity > 0.5:
        lx, ly = LONELINESS_SLOW_ANCHORS
        curve = "slow"
    else:
        lx, ly = LONELINESS_DEFAULT_ANCHORS
        curve = "default"

    loneliness_target = _interpolate_lookup(silence_hours, lx, ly)
    boredom_target   = _interpolate_lookup(silence_hours, BOREDOM_ANCHORS[0], BOREDOM_ANCHORS[1])
    info_gap_target = _interpolate_lookup(silence_hours, INFO_GAP_ANCHORS[0], INFO_GAP_ANCHORS[1])

    injected: set = set()

    # ---- 注入（只上调已有值，不覆盖更高的现有值）----
    # v11.4 双通道：沉默时间的孤独分给 core 70%、surface 30%
    if entity.loneliness < loneliness_target:
        _core_share = loneliness_target * 0.7
        _surface_share = loneliness_target * 0.3
        if entity.loneliness_core < _core_share:
            entity.loneliness_core = _core_share
        if entity.loneliness_surface < _surface_share:
            entity.loneliness_surface = _surface_share
        entity._sync_loneliness()
        injected.add("loneliness")
    if entity.boredom < boredom_target:
        entity.boredom = boredom_target
        injected.add("boredom")
    if entity.info_gap < info_gap_target:
        entity.info_gap = info_gap_target
        injected.add("info_gap")

    # ---- 负面情境额外注入 stress ----
    if emotion < -0.3 and intensity > 0.5:
        entity.adjust("stress", 0.15)
        injected.add("stress")

    entity._time_injected_fields = injected

    logger.info(
        f"[SilenceInjection] silence_h={silence_hours:.2f} curve={curve}: "
        f"loneliness={loneliness_target:.3f} boredom={boredom_target:.3f} "
        f"info_gap={info_gap_target:.3f} injected={injected}"
    )

    # ---- 重新调味 ----
    try:
        from .memory_hub.insula_hub import compute_somatic_signals
        somatic = compute_somatic_signals(entity.to_state_snapshot())
        entity.somatic_tone = float(somatic.get("somatic_tone", entity.somatic_tone))
    except Exception:
        pass


def get_entity_state() -> EntityState:
    """
    获取全局单例。

    启动时自动从 data/entity_core.json 加载持久化状态。
    若文件不存在，则创建新实例（全新 XIA）。
    加载完成后，从 episodes.db 召回最近经验重建来路。
    """
    global _entity_state_instance
    if _entity_state_instance is None:
        entity = EntityState()
        # 1. 加载持久化文件
        loaded = entity.load_from_file(ENTITY_CORE_PATH)
        if not loaded:
            logger.info("[EntityState] No persisted state found, starting fresh")
        # 2. 从 episodes.db 召回最近经验（重建来路）
        _recover_from_episodes(entity)
        # 3. 计算沉默时长并注入时间偏移
        _apply_silence_injection(entity)
        _entity_state_instance = entity
    return _entity_state_instance


def reset_entity_state() -> None:
    """
    保存当前状态后再重置全局单例（仅用于测试/重置场景）。
    """
    global _entity_state_instance
    if _entity_state_instance is not None:
        try:
            _entity_state_instance.persist_to_file(ENTITY_CORE_PATH)
        except Exception:
            pass
    _entity_state_instance = EntityState()



def force_set_state(overrides: Dict[str, float]) -> None:
    """
    强制设置实体内核状态（用于手工测试场景）。

    参数：
        overrides : {"loneliness": 0.7, "fatigue": 0.7, ...}

    示例（channel --test scenario1）：
        force_set_state({"loneliness": 0.7, "fatigue": 0.7})
    """
    entity = get_entity_state()
    for key, value in overrides.items():
        if hasattr(entity, key):
            setattr(entity, key, float(value))
    entity.persist_to_file(ENTITY_CORE_PATH)


# ============================================================================
# 测试场景（手工验证用）
# ============================================================================

TEST_SCENARIOS = {
    # 测试1：组合表达验证 — loneliness=0.7, fatigue=0.7
    # 预期：回复体现"有点想找人，但不太有力气开口"类质地
    "scenario1": {"loneliness": 0.7, "fatigue": 0.7},
    # 测试2：拮抗张力验证 — approach_drive=0.8, avoid_drive=0.8
    # 预期：回复有犹豫、自我修正、句式不稳定特征
    "scenario2": {"approach_drive": 0.8, "avoid_drive": 0.8, "somatic_tone": 0.0},
    # 测试3：真实行为执行验证 — 强制 action_type="explore"
    # 预期：下一轮出现新信息，dispatched_actions 有记录
    "scenario3": {"approach_drive": 0.8, "avoid_drive": 0.2, "info_gap": 0.9},
}


