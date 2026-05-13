"""
Entity Zero Iteration — 实体内核迭代器（完整同步管线版）

主引擎：负责任务编排、异步经验处理、规则持久化调度。

设计原则（核心原则：状态驱动，禁止时钟驱动）：
    - 所有行为由状态变化触发，而非定时器或周期任务
    - 任一模块失败必须可跳过，不阻断主循环
    - 持久化由外层调度器负责，核心函数纯函数

同步管线（run_pipeline）：
    0.  freeze_state   — 冻结当前状态快照
    1.  semantic        — 感性认识
    2.  memory_bias     — 记忆偏置
    3.  concept_tags    — 概念标签映射
    4.  world_model_read— 世界模型查询（只读）
    5.  drive           — 驱动力计算
    6.  think           — 受限思考
    7.  decide          — 裁决
    8.  intent_encode   — 意图编码
    9.  output          — 输出层

异步管线（异步处理）：
    - process_async_updates      — 经验写入 + 拓扑信号
    - trigger_sleep_if_needed   — 睡眠周期
    - run_reflection_cycle_async — 世界模型反思
    - run_world_model_update_async — 世界模型更新

与 TetraMem 的集成：
    - 经验写入跟随"经验流"，由决策动作自然触发
    - 做梦触发由决策层决定（状态池，如 fatigue > 0.9）
    - 拓扑反馈降维为认知压力，汇入裁决信号池
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


# ============================================================================
# Pipeline Trace — 调试追踪
# ============================================================================

@dataclass
class PipelineTrace:
    """同步管线执行追踪"""
    step: str = ""
    elapsed_ms: float = 0.0
    ok: bool = True
    data: Dict[str, Any] = field(default_factory=dict)
    error: str = ""


# ============================================================================
# Entity State — 实体内核状态（跨轮次持久）
# ============================================================================

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
    loneliness_core: float = 0.2     # v11.4 真孤独：只有真人互动能消解
    loneliness_surface: float = 0.1  # v11.4 假孤独：探索/创造等向外行为可缓解
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


def run_test_scenario(name: str) -> None:
    """
    执行指定测试场景，强制设置状态后运行一轮管线。
    用于手工验证接线。
    """
    scenario = TEST_SCENARIOS.get(name)
    if scenario is None:
        print(f"[test] 未知场景: {name}，可用: {list(TEST_SCENARIOS.keys())}")
        return

    print(f"[test] 运行场景: {name}")
    print(f"[test] 强制状态: {scenario}")

    # 强制设置状态
    force_set_state(scenario)

    # 强制 emergent_action 为 explore（仅 scenario3）
    if name == "scenario3":
        # 临时覆盖 emerge_behavior 的返回 action
        import copy
        entity = get_entity_state()
        entity._forced_action = "explore"
    else:
        entity = get_entity_state()
        entity._forced_action = None

    # 运行一轮管线
    result = run_pipeline(raw_input="你好", debug=True)
    print(f"\n[test] 场景 {name} 完成")
    print(f"[test] 输出: {result.get('response', {}).get('text', '')}")
    print(f"[test] 决策: {result.get('decision', {}).get('action_type', '')}")
    print(f"[test] dispatched_actions: {result.get('dispatched_actions', [])}")



# ============================================================================
# 同步管线主函数
# ============================================================================

# ---------------------------------------------------------------------------
# 语言训练降级：启发式默认候选
# ---------------------------------------------------------------------------
def _make_fallback_candidates(state: Dict[str, float]) -> List[str]:
    """根据驱动力场从体感词典中抽取最相关候选词。

    v3.2: 替换硬编码 12 词 → 240+ 词的体感词典。
    用粗略方向匹配做第一轮粗筛，BGE 再做精确打分。
    v11.1: 不混入功能词——功能词走输出层辅线附赠，不参与 BGE 竞争。
    """
    candidates = []
    
    try:
        from .language_system.somatic_dictionary import get_words_matching_state
        matches = get_words_matching_state(state, top_k=8, min_similarity=0.15)
        if matches:
            candidates = [w for w, _, _ in matches]
        return candidates[:16]  # 上限 16 个候选
    except Exception:
        pass

    # 词典加载失败时的硬兜底
    avoid = float(state.get("avoid_drive", state.get("avoid", 0.3)))
    if avoid > 0.7:
        return ["嗯", "……", "不知道", "算了"]
    elif avoid > 0.5:
        return ["嗯", "哦", "不知道", "也许"]
    return ["嗯", "哦", "好"]


def run_pipeline(
    raw_input: Optional[str] = None,
    entity_state: Optional[EntityState] = None,
    params_override: Optional[Dict[str, Any]] = None,
    llm_callable: Optional[Any] = None,
    debug: bool = False,
    daemon_mode: bool = False,
) -> Dict[str, Any]:
    """
    同步管线主入口。

    将原始输入通过完整认知管线，输出响应和更新后的状态。

    参数：
        raw_input       : 用户输入文本（外部输入时）
                        若为 None，表示内部 tick（无外部输入）
        entity_state    : 实体内核状态（若为 None，使用全局单例）
        params_override : 参数覆盖（用于测试）
        llm_callable    : LLM 调用函数（若为 None，使用 output_layer 默认）
        debug           : 是否打印调试追踪
        daemon_mode     : 后台 tick 模式，跳过 LLM 输出步骤（daemon tick 使用）

    返回：
        {
            "response": {
                "text": str,           # 生成的回应
                "confidence": float,    # 置信度
                "generation_time_ms": int,
            },
            "decision": {
                "action_type": str,
                "target": str,
                "priority": float,
                "payload": dict,
            },
            "intent_repr": dict,
            "state_snapshot": dict,    # 更新后的状态快照
            "trace": List[PipelineTrace],  # 执行追踪（debug=True 时）
            "tick": int,
        }
    """
    t0 = time.time()
    entity = entity_state or get_entity_state()
    trace: List[PipelineTrace] = []

    # 清除上轮帮助事件和元认知事件（每 tick 只保留当轮产生的事件）
    if hasattr(entity, "_last_help_event"):
        entity._last_help_event = None
    if hasattr(entity, "_last_meta_event"):
        entity._last_meta_event = None

    def _trace(step: str, ok: bool, data: Dict[str, Any] = None, error: str = "") -> PipelineTrace:
        t = PipelineTrace(
            step=step,
            elapsed_ms=round((time.time() - t0) * 1000, 2),
            ok=ok,
            data=data or {},
            error=error,
        )
        if debug:
            print(f"  [{t.elapsed_ms:.1f}ms] {step}: {'OK' if ok else 'FAIL'} {error}")
        trace.append(t)
        return t

    # ---- Step 0: 创建参数快照（每个 Tick 一次）----
    snapshot = create_snapshot(overrides=params_override)
    _trace("create_snapshot", True)

    # ---- Step 0a: 转换为 dict（供语言/情绪系统模块使用）----
    # 语言系统和情绪系统模块期望 Dict[str, Any]，但管线传递的是 ParameterSnapshot。
    # 在此统一转换，避免每个调用点单独处理类型适配。
    def _snapshot_dict(key_path: str, default: Any = None) -> Any:
        return get_param(snapshot, key_path, default)

    _snapshot_as_dict: Dict[str, Any] = {}
    # 从 ParameterSnapshot 提取常用参数域的 dict 表示
    # 语言/情绪系统需要的 keys 会被 get_param 按需解析
    # 这里提供一个 dict-like 包装，让 language_system 的 .get() 调用不崩溃
    class _SnapshotDictWrapper(dict):
        """将 ParameterSnapshot 包装为 dict 接口，透明转发给 get_param。"""
        __slots__ = ("_snap",)
        def __init__(self, snap: Any):
            self._snap = snap
        def get(self, key: str, default: Any = None) -> Any:
            return get_param(self._snap, key, default)
        def __getitem__(self, key: str) -> Any:
            return get_param(self._snap, key, None)
        def __contains__(self, key: str) -> bool:
            return get_param(self._snap, key, _SENTINEL) is not _SENTINEL

    _SENTINEL = object()
    _snapshot_dict = _SnapshotDictWrapper(snapshot)
    # ---- Step 0b: 记录 somatic_tone_start（供 Step 8.4 somatic_tone_delta 计算）----
    somatic_tone_start = float(getattr(entity, "somatic_tone", 0.0))

    # ---- Step 1: 冻结状态快照（所有模块共享的只读视图）----
    state_snapshot = entity.to_state_snapshot()
    _trace("freeze_state", True, {"energy": state_snapshot.get("energy"), "fatigue": state_snapshot.get("fatigue")})

    # =========================================================================
    # [语言系统 L1] Step 1 后、Step 2（感性认识）前：初始化 + 顶撞权检查
    # =========================================================================
    # 初始化语言系统各模块（惰性注入 entity_state）
    _quenching: QuenchingTracker = getattr(entity, "_quenching", None)
    _strategy_map: StrategyMap = getattr(entity, "_strategy_map", None)
    _thermal: ThermalController = getattr(entity, "_thermal", None)
    _mirror: MirrorLearner = getattr(entity, "_mirror", None)
    _five_rights: FiveRightsController = getattr(entity, "_five_rights", None)
    _semantic_analyzer: SemanticAnalyzer = getattr(entity, "_semantic_analyzer", None)
    _candidate_gen: CandidateGenerator = getattr(entity, "_candidate_gen", None)
    _behavior_profiler: BehaviorProfiler = getattr(entity, "_behavior_profiler", None)
    _decay_engine: DecayEngine = getattr(entity, "_decay_engine", None)

    # 尝试从持久化 dict 恢复（优先级高于惰性创建）
    if _quenching is None and getattr(entity, "_quenching_data", None):
        _quenching = QuenchingTracker.from_dict(entity._quenching_data)
    if _strategy_map is None and getattr(entity, "_strategy_map_data", None):
        _strategy_map = StrategyMap.from_dict(entity._strategy_map_data)
    if _thermal is None and getattr(entity, "_thermal_data", None):
        _thermal = ThermalController.from_dict(entity._thermal_data)
    if _mirror is None and getattr(entity, "_mirror_data", None):
        _mirror = MirrorLearner.from_dict(entity._mirror_data)
    if _five_rights is None and getattr(entity, "_five_rights_data", None):
        _five_rights = FiveRightsController.from_dict(entity._five_rights_data)
    if _semantic_analyzer is None:
        # 优先尝试 BGE-small-zh-v1.5，不可用时降级到 LLM 启发式
        try:
            from .language_system.bge_analyzer import SemanticAnalyzerV2
            _semantic_analyzer = SemanticAnalyzerV2()
            logger.info("[run_pipeline] Using BGE SemanticAnalyzerV2")
        except Exception:
            _semantic_analyzer = SemanticAnalyzer()
            logger.info("[run_pipeline] BGE unavailable, using LLM SemanticAnalyzer")
    if _candidate_gen is None:
        _candidate_gen = CandidateGenerator()
    if _behavior_profiler is None:
        _behavior_profiler = BehaviorProfiler()
    if _decay_engine is None:
        _decay_engine = DecayEngine()

    # 惰性创建（如无持久化记录）
    if _quenching is None:
        _quenching = QuenchingTracker(history_maxlen=int(get_param(snapshot, "language.quenching.history_maxlen", 500)))
    if _strategy_map is None:
        _strategy_map = StrategyMap()

    # 播种：策略地图空时注入极端状态锚点词作为初始参照系
    if _strategy_map is not None and not _strategy_map._map:
        try:
            from .language_system.seed_map import seed_strategy_map
            seeded = seed_strategy_map(_strategy_map, _quenching)
            logger.info(f"[run_pipeline] 策略地图播种: {seeded} 条初始锚点")
            _trace("seed_map", True, {"entries": seeded})
        except Exception as e:
            _trace("seed_map", False, {}, str(e))

    if _thermal is None:
        _thermal = ThermalController()
    if _mirror is None:
        _mirror = MirrorLearner(bias_strength=float(get_param(snapshot, "language.mirror.bias_strength", 0.40)))
    if _five_rights is None:
        _five_rights = FiveRightsController()

    # 绑定各模块之间的依赖关系
    _five_rights.set_mirror(_mirror)
    _candidate_gen.bind_strategy_map(_strategy_map)
    _candidate_gen.bind_thermal(_thermal)
    _candidate_gen.bind_semantic_analyzer(_semantic_analyzer)
    _candidate_gen.bind_five_rights(_five_rights)

    # ---- Step 2: 感性认识 ----
    try:
        semantic_raw = analyze_semantic(raw_input) if raw_input else {
            "emotion": 0.0, "intent": "闲聊", "intensity": 0.3, "anchors": []
        }
        # intent_confidence 字段由感性认识层自行补充（concept_tags 依赖此字段）
        if "intent_confidence" not in semantic_raw:
            semantic_raw["intent_confidence"] = 0.8
        semantic_packet = semantic_raw
        _trace("semantic", True, semantic_packet)
    except Exception as e:
        semantic_raw = {"emotion": 0.0, "intent": "闲聊", "intensity": 0.3, "anchors": [], "intent_confidence": 0.8}
        semantic_packet = semantic_raw
        _trace("semantic", False, semantic_packet, str(e))

    # ---- 顶撞权检查（Step 2 后：semantic_packet 已定义）----
    user_intent_from_input: Dict[str, Any] = {}
    if raw_input and str(raw_input).strip():
        user_intent_from_input = {
            "content": str(raw_input),
            "intent": semantic_packet.get("intent", "") if semantic_packet else "",
            "emotion": float(semantic_packet.get("emotion", 0.0)) if semantic_packet else 0.0,
            "pressure": abs(float(semantic_packet.get("emotion", 0.0))) if semantic_packet else 0.0,
        }
    _defy_result: Dict[str, Any] = {"defy": False, "reason": "", "efficiency_boost": 1.0}
    if user_intent_from_input:
        _defy_result = _five_rights.check_defy(user_intent_from_input, state_snapshot, snapshot)
        _trace("language_defy", True, _defy_result)

    # ---- Step 3: 记忆偏置 ----
    try:
        semantic_packet_biased = apply_memory_bias(
            semantic_packet,
            entity.memory_context
        )
        # raw_input 注入（供 WebSearch 等子模块使用）
        semantic_packet_biased["raw_input"] = raw_input
        _trace("memory_bias", True, {"emotion": semantic_packet_biased.get("emotion")})
    except Exception as e:
        semantic_packet_biased = dict(semantic_packet)
        semantic_packet_biased["raw_input"] = raw_input
        _trace("memory_bias", False, semantic_packet_biased, str(e))
        semantic_packet_biased = dict(semantic_packet)
        _trace("memory_bias", False, semantic_packet_biased, str(e))

    # ---- Step 4: 概念标签映射 ----
    try:
        concept_tags = generate_concept_tags(semantic_packet_biased)
        _trace("concept_tags", True, {"count": len(concept_tags), "tags": [t.get("tag") for t in concept_tags]})
    except Exception as e:
        concept_tags = []
        _trace("concept_tags", False, {"count": 0}, str(e))

    # ---- Step 4.5: Insights 召回（显性知识注入）----
    tag_strings = [t.get("tag", "") for t in concept_tags if isinstance(t, dict)]
    _recalled_insights: List[Any] = []
    try:
        from .memory_hub.insights import recall_insights as _recall_insights
        _recalled_insights = _recall_insights(tag_strings)
        _trace("insights_recall", True, {
            "query_tags": tag_strings,
            "hit_count": len(_recalled_insights),
        })
    except Exception as e:
        _recalled_insights = []
        _trace("insights_recall", False, {}, str(e))

    # ---- Step 5: 世界模型查询（只读）----
    wm_snapshot = {"rules": entity.wm_rules}
    try:
        tag_strings = [t.get("tag", "") for t in concept_tags if isinstance(t, dict)]
        wm_context = query_world_model(tag_strings, copy.deepcopy(wm_snapshot))
        _trace("world_model_read", True, {
            "hit_rate": wm_context.get("coverage", {}).get("hit_rate", 0.0),
            "matched_count": len(wm_context.get("matched_rules", [])),
        })
    except Exception as e:
        wm_context = {"matched_rules": [], "key_signals": {}, "coverage": {"hit_rate": 0.0, "queried_tags": [], "missed_tags": []}}
        _trace("world_model_read", False, {}, str(e))

    # ---- Step 6: 驱动力计算 ----
    try:
        curiosity_baseline = get_param(snapshot, "drives.curiosity_baseline", 0.2)
        info_hunger_baseline = get_param(snapshot, "drives.info_hunger_baseline", 0.24)
        drive_params = {
            "curiosity_baseline": curiosity_baseline,
            "info_hunger_baseline": info_hunger_baseline,
            "curiosity_param": get_param(snapshot, "drives.curiosity_param", 1.0),
            "max_info_gap_hours": get_param(snapshot, "drives.max_info_gap_hours", 24.0),
            "max_social_gap_hours": get_param(snapshot, "drives.max_social_gap_hours", 24.0),
            **get_default_drive_params(),
        }
        # 将 baseline 叠加到状态上（让 info_gap 反映基础好奇心）
        drive_state = dict(state_snapshot)
        drive_state["info_gap"] = min(1.0, state_snapshot.get("info_gap", 0.0) + curiosity_baseline * 0.5)
        drive_vector = compute_drive_vector(drive_state, drive_params)
        # 最终结果叠加 baseline 底噪
        drive_vector["curiosity"] = min(1.0, drive_vector.get("curiosity", 0.0) + curiosity_baseline)
        drive_vector["info_hunger"] = min(1.0, drive_vector.get("info_hunger", 0.0) + info_hunger_baseline)
        _trace("drive", True, drive_vector)
    except Exception as e:
        drive_vector = {"curiosity": 0.2, "info_hunger": 0.24, "obsolescence_anxiety": 0.0, "loneliness_drive": 0.0, "fatigue_avoid": 0.0}
        _trace("drive", False, drive_vector, str(e))

    # ---- Step 6.5: 感质调味（v3 改造，同步新增）----
    # 驱动力计算后、思考之前，感受此刻就在场
    try:
        somatic_signals = _compute_somatic_signals(
            drive_vector=drive_vector,
            wm_context=wm_context,
            entity_core_state=state_snapshot,
            param_snapshot=_snapshot_dict,
        )
        # 立即写入 EntityCore.somatic_tone
        entity.somatic_tone = max(-1.0, min(1.0, somatic_signals.get("tone", 0.0)))
        # 同时更新 approach_drive 和 avoid_drive（由决策结果决定）
        _trace("insula_hub", True, {
            "tone": somatic_signals.get("tone"),
            "dominant_feeling": somatic_signals.get("dominant_feeling"),
            "channel_weights": somatic_signals.get("channel_weights"),
        })
    except Exception as e:
        somatic_signals = {"tone": 0.0, "intensity": 0.0, "dominant_feeling": "", "channel_weights": {}, "dos_suppressed": []}
        _trace("insula_hub", False, {}, str(e))

    # 更新 state_snapshot 供后续步骤使用（somatic_tone 此刻在场）
    state_snapshot["somatic_tone"] = entity.somatic_tone

    # =========================================================================
    # [接入点 1] Step 6.5 后：初始化情绪粒子场 & 主线→日常投影
    # =========================================================================
    # 从 entity 恢复（或创建）情绪粒子场和投影控制器
    try:
        if hasattr(entity, "emotion_particle_field") and entity.emotion_particle_field:
            _particle_field = ParticleField.from_dict(entity.emotion_particle_field)
        else:
            _particle_field = ParticleField(
                max_capacity=int(get_param(snapshot, "emotion_particle.max_capacity", 200)),
                half_life=float(get_param(snapshot, "emotion_particle.log_half_life_s", 1800.0)),
            )

        if hasattr(entity, "emotion_accumulators") and entity.emotion_accumulators:
            acc_data = entity.emotion_accumulators.get("_projection_controller")
            if acc_data:
                _projection_ctrl = ProjectionController.from_dict(acc_data)
            else:
                _projection_ctrl = ProjectionController()
        else:
            _projection_ctrl = ProjectionController()

        # 推进粒子场衰减（基于距上次情绪更新的时间）
        elapsed_since_last = max(0.0, time.time() - getattr(entity, "last_emotion_tick", time.time()))
        _particle_field.tick(elapsed_since_last)
        _projection_ctrl.tick(elapsed_since_last)

        # 主线情绪（somatic_signals 中的 dominant_feeling）注入日常层
        dominant_feeling = somatic_signals.get("dominant_feeling", "")
        if dominant_feeling:
            _projection_ctrl.apply_mainline_to_daily(
                {dominant_feeling: abs(somatic_signals.get("tone", 0.0))},
                _particle_field,
                snapshot,
            )
    except Exception as e:
        _particle_field = ParticleField()
        _projection_ctrl = ProjectionController()
        _trace("emotion_particle_init", False, {}, str(e))

    # ---- Step 7: 受限思考（v3 改造：接入 somatic_signals）----
    try:
        thinking_params = {
            "thinking_activation_threshold": get_param(snapshot, "thresholds.thinking_activation_threshold", 0.5),
            "max_thinking_steps": get_param(snapshot, "thresholds.thinking_max_steps", 2),
            "thinking_timeout_ms": get_param(snapshot, "thresholds.thinking_timeout_ms", 2000),
            "thinking_time_budget_ms": get_param(snapshot, "thresholds.thinking_time_budget_ms", 500),
            "max_suggestions": get_param(snapshot, "thresholds.thinking_max_suggestions", 2),
            "very_low_confidence_threshold": get_param(snapshot, "thresholds.very_low_confidence_threshold", 0.4),
        }
        # V3：感受影响思考方向和深度
        # V2.0：传入 entity_state 和 concept_tags 触发枝干联想检索
        thought_packet = thinking_think(
            wm_context, drive_vector, state_snapshot, thinking_params,
            somatic_signals, entity_state=entity, concept_tags=concept_tags
        )
        _trace("think", True, {"questions": len(thought_packet.get("questions", [])), "suggestions": len(thought_packet.get("suggestions", []))})
    except Exception as e:
        thought_packet = {"suggestions": [], "questions": []}
        _trace("think", False, thought_packet, str(e))

    # =========================================================================
    # [接入点 2] Step 7 后：情绪衰减（thinking_system 后）
    # =========================================================================
    # 厌倦双根源独立衰减 + 其他核心情绪衰减
    # 注意：直接使用 L1 初始化的 _decay_engine（已从 entity 惰性恢复）
    try:
        elapsed_since_last = max(0.0, time.time() - getattr(entity, "last_emotion_tick", time.time()))
        decay_result = _decay_engine.tick_all(entity, elapsed_since_last, _snapshot_dict)
        _trace("emotion_decay", True, decay_result)
    except Exception as e:
        _trace("emotion_decay", False, {}, str(e))

    # =========================================================================
    # [语言系统 L7] Step 7 后：社交疲劳 + 自闭权（六大主权）
    # =========================================================================
    # 厌烦权：每轮更新社交疲劳值
    # 自闭权：检查 avoid 是否触发防御性退行
    # 注意：直接使用 L1 中初始化的模块级变量 _five_rights, _thermal
    try:
        did_express_in_tick = bool(
            getattr(entity, "_last_action_result", {}).get("success") is not None
        )
        fatigue = _five_rights.tick_social_fatigue(did_express_in_tick, _snapshot_dict)
        is_self_close = _five_rights.activate_self_close(getattr(entity, "avoid_drive", 0.3), snapshot)

        # 社交疲劳反向推高 avoid
        adjusted_avoid = _five_rights.apply_fatigue_to_avoid(getattr(entity, "avoid_drive", 0.3))
        entity.avoid_drive = max(0.0, min(1.0, adjusted_avoid))

        _trace("language_social_init", True, {
            "social_fatigue": fatigue,
            "is_self_close": is_self_close,
            "avoid_adjusted": adjusted_avoid,
        })
    except Exception as e:
        _trace("language_social_init", False, {}, str(e))

    # ---- Step 7.5: 感知前衰减（v11: 子驱动力缓慢衰减）----
    entity.approach_social = max(0.0, entity.approach_social * 0.95)
    entity.approach_explore = max(0.0, entity.approach_explore * 0.95)
    entity.approach_urgency = max(0.0, entity.approach_urgency * 0.95)
    entity.avoid_drive = max(0.0, entity.avoid_drive * 0.88)

    # ---- Step 7.6: MetaCognitive 感知镇压（v11）----
    # 锁死越久，所有感知模块输出越低
    try:
        _lock_snaps = 0
        _snaps = entity.snapshots
        if _snaps and len(_snaps) >= 15:
            _recent = _snaps[-15:]
            LOCK_DIMS = ["approach_drive", "somatic_tone", "loneliness"]
            for dim in LOCK_DIMS:
                _vals = [s.get(dim, 0.5) for s in _recent]
                _mean = sum(_vals) / len(_vals)
                # 检查是否全部接近均值（方差很低 = 锁死）
                _variance = sum((v - _mean)**2 for v in _vals) / len(_vals)
                if _variance < 0.001 and abs(_mean - (0.5 if dim not in ("somatic_tone", "loneliness") else (0.0 if dim == "somatic_tone" else 0.3))) > 0.3:
                    _lock_snaps += 1
            _lock_snaps = min(_lock_snaps * 5, 50)  # 放大（每维度=5 snaps 级）

        _perception_dampen = 1.0 / (1.0 + _lock_snaps * 0.02)
        entity._perception_dampen = _perception_dampen
        entity._lock_snaps = _lock_snaps  # v11.1: 供 danger/fatigue 等下游步骤读取
        _lock_boredom = _lock_snaps * 0.005
        entity.adjust("boredom", _lock_boredom)
        if _lock_snaps > 10:
            _trace("meta_perception_dampen", True, {
                "lock_snaps": _lock_snaps,
                "dampen": round(_perception_dampen, 3),
                "lock_boredom": round(_lock_boredom, 4),
            })
    except Exception as e:
        entity._perception_dampen = 1.0
        _trace("meta_perception_dampen", False, {}, str(e))

    # ---- Step 7.7: Boredom 独立激活（v11）----
    # 消力效率 EMA → boredom 注入 → approach_explore + somatic_tone
    try:
        _eff_ema = entity.quenching_eff_rolling
        _boredom_delta = (1.0 - _eff_ema) * 0.05
        entity.adjust("boredom", _boredom_delta)
        # boredom → explore 推力（保守系数，避免饱和）
        entity.adjust("approach_explore", entity.boredom * 0.20)
        # boredom → 降低舒适感
        entity.adjust("somatic_tone", -entity.boredom * 0.15)
        # 缓慢自然衰减
        entity.boredom *= 0.99
        _trace("boredom_activation", True, {
            "eff_ema": round(_eff_ema, 3),
            "boredom_delta": round(_boredom_delta, 4),
            "boredom": round(entity.boredom, 3),
        })
    except Exception as e:
        _trace("boredom_activation", False, {}, str(e))

    # ---- Step 7.8: Loneliness → approach_social 直接推力（v11）----
    # context_awareness 在 daemon 模式下 emotion=0 不触发，直接在这里加
    try:
        _lon = entity.loneliness
        if _lon > 0.2:
            _social_push = (_lon - 0.2) * 0.08
            entity.adjust("approach_social", _social_push)
    except Exception:
        pass

    # ---- Step 7.9: 自适应蒙特卡洛训练随机化（v11.1）----
    # daemon 模式常驻：对核心状态维度施加自适应高斯游走，
    # 让状态遍历 BGE 空间的不同区域，避免锁死在少数情绪簇。
    # σ 自适应：锁死时放大、词汇丰富时缩小。
    # 手动训练时（_freeze_state=True）跳过——用户正在精确操控状态。
    try:
        import random as _random
        _frozen = getattr(entity, "_freeze_state", False)
        if daemon_mode and not _frozen:
            _lock_snaps = getattr(entity, "_lock_snaps", 0)
            # 自适应 σ: 锁死越久越敢跳，词汇越丰富越精细
            _sigma_base = 0.03
            _vocab_diversity = 1.0  # 默认
            try:
                from .language_system.meta_cognitive import MetaCognitive
                _mc = MetaCognitive()
                _diagnosis = _mc.diagnose(entity.to_state_snapshot())
                _vocab_diversity = _diagnosis.get("vocabulary_diversity", 1.0)
            except Exception:
                pass
            _sigma = _sigma_base * (1.0 + _lock_snaps * 0.10)   # lock↑ → noise↑
            _sigma = _sigma / (1.0 + _vocab_diversity * 0.5)      # diversity↑ → noise↓
            _sigma = min(_sigma, 0.12)  # 上限，防止失控

            _dims = ["somatic_tone", "loneliness", "energy", "boredom",
                     "unresolved", "stress", "danger_level", "fatigue"]
            # 稀疏扰动：每 tick 只随机挑 ~40% 维度施加噪声，
            # 打破力场耦合导致的统一下降走廊。
            _all_targets = _dims + ["approach_social", "approach_explore", "approach_urgency"]
            _n_perturb = max(3, len(_all_targets) // 3)  # ~4 个维度
            _perturb = set(_random.sample(_all_targets, _n_perturb))
            for _dim in _dims:
                if _dim not in _perturb:
                    continue
                _step = _random.gauss(0, _sigma)
                if _dim == "somatic_tone":
                    entity.somatic_tone = max(-1.0, min(1.0, entity.somatic_tone + _step * 2))
                else:
                    entity.adjust(_dim, _step)
            # 子驱动力稀疏扰动
            for _sub in ["approach_social", "approach_explore", "approach_urgency"]:
                if _sub not in _perturb:
                    continue
                _val = getattr(entity, _sub, 0.0)
                setattr(entity, _sub, max(0.0, min(1.0,
                    _val + _random.gauss(0, _sigma * 0.75))))
            # 每 10 tick 记录一次
            if entity.tick % 10 == 0:
                logger.info(
                    f"[TrainingMC] σ={_sigma:.3f} lock={_lock_snaps} "
                    f"somatic={entity.somatic_tone:.2f} "
                    f"loneliness={entity.loneliness:.2f}(c={entity.loneliness_core:.2f}/s={entity.loneliness_surface:.2f}) "
                    f"boredom={entity.boredom:.2f}"
                )
            _trace("training_mc", True, {
                "sigma": round(_sigma, 4),
                "lock_snaps": _lock_snaps,
                "somatic": round(entity.somatic_tone, 3),
                "loneliness": round(entity.loneliness, 3),
                "boredom": round(entity.boredom, 3),
            })
    except Exception:
        pass

    # ---- Step 7.9b: 反锁推力（v11.2）----
    # 当某维度在最近 snap 中长期卡在极端值，
    # 施加连续定向力推向中性区——"在同一个感受里待太久，身体产生离开它的冲动"。
    # 力 = (neutral - current) × stuck_ratio × 0.015 × lock_snaps_factor
    # 完全连续：stuck_ratio ∈ [0,1]，lock_snaps 在线性区。
    # 手动训练时（_freeze_state=True）跳过——用户正在精确操控状态。
    try:
        _frozen = getattr(entity, "_freeze_state", False)
        if not _frozen:
            _snaps = entity.snapshots
            if _snaps and len(_snaps) >= 8:
                _recent = _snaps[-15:] if len(_snaps) >= 15 else _snaps[-8:]
                _neutral_map = {
                    "somatic_tone": 0.0,
                    "loneliness": 0.3,
                    "energy": 0.5,
                    "boredom": 0.2,
                    "unresolved": 0.2,
                    "stress": 0.1,
                    "danger_level": 0.0,
                    "fatigue": 0.1,
                    "approach_drive": 0.5,
                    "avoid_drive": 0.5,
                    "approach_social": 0.5,
                    "approach_explore": 0.5,
                    "approach_urgency": 0.5,
                }
                _lock = getattr(entity, "_lock_snaps", 0)
                _lock_factor = min(_lock / 20.0, 1.0) if _lock > 0 else 0.0

                for _dim, _neutral in _neutral_map.items():
                    _vals = [s.get(_dim, _neutral) for s in _recent]
                    _mean = sum(_vals) / len(_vals)
                    _deviation = abs(_mean - _neutral)
                    # 只对明显偏离中性且卡住的维度施加推力
                    if _deviation < 0.25:
                        continue
                    _variance = sum((v - _mean) ** 2 for v in _vals) / len(_vals)
                    if _variance > 0.005:
                        continue  # 还在变，不算锁死

                    _current = getattr(entity, _dim, _mean)
                    _stuck_ratio = min(_deviation / 0.5, 1.0)  # 偏离越大推力越强
                    _force = (_neutral - _current) * _stuck_ratio * 0.10 * (1.0 + _lock_factor)
                    if _dim == "somatic_tone":
                        entity.somatic_tone = max(-1.0, min(1.0, entity.somatic_tone + _force))
                    elif _dim in ("approach_social", "approach_explore", "approach_urgency",
                                  "approach_drive", "avoid_drive"):
                        setattr(entity, _dim, max(0.0, min(1.0, _current + _force)))
                    else:
                        entity.adjust(_dim, _force)

                if entity.tick % 10 == 0 and _lock_factor > 0:
                    _stuck_dims = []
                    for _dim, _neutral in _neutral_map.items():
                        _vals = [s.get(_dim, _neutral) for s in _recent]
                        _mean = sum(_vals) / len(_vals)
                        _deviation = abs(_mean - _neutral)
                        if _deviation >= 0.25:
                            _variance = sum((v - _mean) ** 2 for v in _vals) / len(_vals)
                            if _variance <= 0.002:
                                _stuck_dims.append(f"{_dim}={getattr(entity, _dim, 0):.2f}")
                    if _stuck_dims:
                        logger.info(
                            f"[AntiLock] lock_factor={_lock_factor:.2f} "
                            f"pushing: {', '.join(_stuck_dims)}"
                        )
    except Exception:
        pass

    # ---- Step 7.9c (was 7.9a): 物理约束检查（v11.1）----
    # MC 稀疏扰动可能产生逻辑上不可能的维度组合。
    # 不硬拒绝，只软修正——把越界的维度对拉回可行域。
    try:
        _violations = 0

        # 1. energy + fatigue ≤ 1.3（不可能精神饱满又极度疲惫）
        _e, _f = entity.energy, entity.fatigue
        if _e + _f > 1.3:
            _excess = (_e + _f - 1.3) / 2
            entity.energy = max(0.0, _e - _excess)
            entity.fatigue = max(0.0, _f - _excess)
            _violations += 1

        # 2. somatic_tone > 0.3 → pain 不能太高
        if entity.somatic_tone > 0.3:
            _pain_limit = 0.4 + (entity.somatic_tone - 0.3) * 0.3
            if entity.pain > _pain_limit:
                entity.pain = _pain_limit
                _violations += 1

        # 3. danger × approach_social ≤ 0.5（恐惧压抑社交冲动）
        _dp = entity.danger_level * entity.approach_social
        if _dp > 0.5:
            # 各退一半
            _excess = (_dp - 0.5) / 2
            entity.danger_level = max(0.0, entity.danger_level - _excess)
            entity.approach_social = max(0.0, entity.approach_social - _excess)
            _violations += 1

        # 4. fatigue × approach_urgency ≤ 0.4（累瘫不可能急迫）
        _fu = entity.fatigue * entity.approach_urgency
        if _fu > 0.4:
            _excess = (_fu - 0.4) / 2
            entity.fatigue = max(0.0, entity.fatigue - _excess)
            entity.approach_urgency = max(0.0, entity.approach_urgency - _excess)
            _violations += 1

        # 5. approach_drive + avoid_drive 不能同时 > 0.6
        _a, _av = entity.approach_drive, entity.avoid_drive
        if _a > 0.6 and _av > 0.6:
            _avg = (_a + _av) / 2
            entity.approach_drive = max(0.0, _a - (_a - 0.6) * 0.5)
            entity.avoid_drive = max(0.0, _av - (_av - 0.6) * 0.5)
            _violations += 1

        if _violations > 0 and entity.tick % 20 == 0:
            _trace("mc_constraints", True, {"violations": _violations})
    except Exception:
        pass

    # ---- Step 7.10: danger → 独立 avoid 通路（杏仁核，v11.1）----
    # 绕过 somatic_tone，直接注入 avoid_drive。
    # 激活条件：锁死深度 × 淬灭失效 → 危险感累积
    try:
        _lock_snaps = getattr(entity, "_lock_snaps", 0)
        _lock_depth = max(0.0, (_lock_snaps - 10) / 10.0)
        _inefficiency = 1.0 - entity.quenching_eff_rolling
        _danger_delta = _lock_depth * _inefficiency * 0.03
        if _danger_delta > 0:
            entity.adjust("danger_level", _danger_delta)
        entity.danger_level = max(0.0, entity.danger_level * 0.95)  # 自然衰减
        # 杏仁核通路：直接推 avoid，不经过 Insula/somatic_tone
        _danger_avoid = entity.danger_level * 0.50
        if _danger_avoid > 0.001:
            entity.adjust("avoid_drive", _danger_avoid)
            entity.adjust("stress", entity.danger_level * 0.20)
            if entity.tick % 20 == 0:
                _trace("danger_amygdala", True, {
                    "danger": round(entity.danger_level, 4),
                    "avoid_push": round(_danger_avoid, 4),
                    "lock_depth": round(_lock_depth, 3),
                    "inefficiency": round(_inefficiency, 3),
                })
    except Exception:
        pass

    # ---- Step 7.11: fatigue → 全局感知阻尼（v11.1）----
    # stress 积分器 → 疲劳累积 → 所有感知模块输出衰减
    try:
        _fatigue_delta = entity.stress * 0.015
        entity.adjust("fatigue", _fatigue_delta)
        entity.fatigue = max(0.0, entity.fatigue * 0.998)  # 极慢衰减
        # 疲劳阻尼叠加到现有 MetaCognitive dampen 上
        _fatigue_gain = 1.0 / (1.0 + entity.fatigue * 2.0)
        _current_dampen = getattr(entity, "_perception_dampen", 1.0)
        entity._perception_dampen = _current_dampen * _fatigue_gain
        if entity.tick % 20 == 0 and entity.fatigue > 0.3:
            _trace("fatigue_damping", True, {
                "fatigue": round(entity.fatigue, 4),
                "stress": round(entity.stress, 4),
                "fatigue_gain": round(_fatigue_gain, 4),
                "combined_dampen": round(entity._perception_dampen, 4),
            })
    except Exception:
        pass

    # ---- Step 7.12: unresolved → 内省模式（v11.1）----
    # approach ∧ avoid 同时高 → 冲突 → 转向内部
    try:
        _conflict = min(entity.approach_drive, entity.avoid_drive)
        _unresolved_delta = _conflict * 0.04
        if _unresolved_delta > 0.001:
            entity.adjust("unresolved", _unresolved_delta)
        entity.unresolved = max(0.0, entity.unresolved * 0.98)  # 缓慢衰减
        # 内省：外部感知增益降低
        _external_gain = 1.0 / (1.0 + entity.unresolved * 1.5)
        _current_dampen = getattr(entity, "_perception_dampen", 1.0)
        entity._perception_dampen = _current_dampen * _external_gain
        if entity.tick % 20 == 0 and entity.unresolved > 0.4:
            _trace("introspection_mode", True, {
                "unresolved": round(entity.unresolved, 4),
                "conflict": round(_conflict, 4),
                "external_gain": round(_external_gain, 4),
                "combined_dampen": round(entity._perception_dampen, 4),
            })
    except Exception:
        pass

    # ---- Step 7.13: pain 激活（v11.1）----
    # 疼痛不来自外部打击——是持续负躯体基调 + 威胁的身体化表达。
    # somatic_tone 长期负 → 身体在疼；danger × stress → 威胁加剧疼痛。
    try:
        # 负躯体基调累积
        _somatic_pain = max(0.0, -entity.somatic_tone - 0.2) * 0.03
        # 威胁放大
        _threat_pain = entity.stress * entity.danger_level * 0.05
        _pain_delta = _somatic_pain + _threat_pain
        if _pain_delta > 0:
            entity.adjust("pain", _pain_delta)
        entity.pain = max(0.0, entity.pain * 0.98)  # 缓慢自然衰减
        if entity.tick % 20 == 0 and entity.pain > 0.2:
            _trace("pain_activation", True, {
                "pain": round(entity.pain, 4),
                "somatic_pain": round(_somatic_pain, 4),
                "threat_pain": round(_threat_pain, 4),
            })
    except Exception:
        pass

    # ---- Step 7.14: relief_debt 激活（v11.1）----
    # 亏欠感 = 想消解但消不掉的东西的累积。
    # 消力持续低 + 心里挂着事 → 亏欠感上升。
    try:
        _inefficiency = 1.0 - entity.quenching_eff_rolling
        _debt_delta = _inefficiency * entity.unresolved * 0.02
        if _debt_delta > 0:
            entity.adjust("relief_debt", _debt_delta)
        entity.relief_debt = max(0.0, entity.relief_debt * 0.99)  # 极慢衰减
        if entity.tick % 20 == 0 and entity.relief_debt > 0.3:
            _trace("relief_debt_activation", True, {
                "relief_debt": round(entity.relief_debt, 4),
                "inefficiency": round(_inefficiency, 3),
                "unresolved": round(entity.unresolved, 3),
            })
    except Exception:
        pass

    # ---- Step 8: 九模块并行感知（v3 改造）----
    # 各子模块直接修改 entity 的状态变量，完成后 entity.approach_drive / avoid_drive 自然更新
    # Insights 作为显性知识注入 wm_context，供感知层读取
    wm_context["insights"] = _recalled_insights
    try:
        decision_params = _build_decision_params(snapshot)
        _perceive_all(
            entity_core=entity,
            semantic_packet_biased=semantic_packet_biased,
            concept_tags=concept_tags,
            wm_context=wm_context,
            drive_vector=drive_vector,
            thought_packet=thought_packet,
            state_snapshot=state_snapshot,
            params=decision_params,
        )
        _trace("perceive_all", True, {
            "approach_drive": entity.approach_drive,
            "avoid_drive": entity.avoid_drive,
            "somatic_tone": entity.somatic_tone,
        })
    except Exception as e:
        _trace("perceive_all", False, {}, str(e))

    # ---- Step 8.0a: 子驱动力合成 approach_drive（v11）----
    try:
        entity.approach_drive = (
            0.40 * entity.approach_social +
            0.35 * entity.approach_explore +
            0.25 * entity.approach_urgency
        )
        entity.approach_drive = max(0.0, min(1.0, entity.approach_drive))
    except Exception as e:
        _trace("approach_synthesis", False, {}, str(e))

    # ---- Step 8.0: 感知后重算驱动力（方案一：九模块先读 wm/drive 再修改 entity，涌现前重算最新驱动）----
    # perceive_all 会修改 entity 状态，但 Step 6 的 drive_vector 基于感知前状态
    # 九模块对 entity 的修改（approach_drive / avoid_drive 等）会体现在重算结果里
    # emerge_behavior 读取 entity.approach_drive/avoid_drive 时即是最新的
    try:
        state_after_perceive = entity.to_state_snapshot()
        drive_state_fresh = dict(state_after_perceive)
        drive_state_fresh["info_gap"] = min(
            1.0,
            state_after_perceive.get("info_gap", 0.0) + curiosity_baseline * 0.5,
        )
        drive_vector_final = compute_drive_vector(drive_state_fresh, drive_params)
        drive_vector_final["curiosity"] = min(
            1.0, drive_vector_final.get("curiosity", 0.0) + curiosity_baseline
        )
        drive_vector_final["info_hunger"] = min(
            1.0, drive_vector_final.get("info_hunger", 0.0) + info_hunger_baseline
        )
        _trace("drive_recomputed", True, drive_vector_final)
    except Exception as e:
        drive_vector_final = drive_vector  # fallback 到感知前的结果
        _trace("drive_recomputed", False, {}, str(e))

    # ---- Step 8.05: Insula 二次调味（感知后重算驱动，基于"此刻的她"）----
    # Step 6.5 用感知前的状态 + drive_vector；Step 8.05 用感知后的状态 + drive_vector_final
    # 二次调味让 emerge_behavior 读取的 somatic_tone 更准确
    try:
        state_for_insula = entity.to_state_snapshot()
        somatic_signals_2 = _compute_somatic_signals(
            drive_vector=drive_vector_final,
            wm_context=wm_context,
            entity_core_state=state_for_insula,
            param_snapshot=_snapshot_dict,
        )
        refined_tone = max(-1.0, min(1.0, somatic_signals_2.get("tone", 0.0)))
        entity.somatic_tone = refined_tone
        # 合并两次调味的结果（第二次覆盖第一次，但记录两次调试信息）
        somatic_signals["refined_tone"] = refined_tone
        somatic_signals["channel_weights_2"] = somatic_signals_2.get("channel_weights", {})
        _trace("insula_re_seasoning", True, {
            "refined_tone": refined_tone,
            "dominant_feeling": somatic_signals_2.get("dominant_feeling"),
        })
    except Exception as e:
        _trace("insula_re_seasoning", False, {}, str(e))

    # ---- Step 8.05b: 情绪内生计算（v10.0/v11.0 十个核心情绪从驱动力场中生长）----
    # 在 Insula 二次调味后、行为涌现前，根据当前驱动力场计算情绪激活强度
    # 情绪是状态导出的只读层——不反写状态，但影响输出层和记忆层
    try:
        _pred_err = float(getattr(entity, "_last_prediction_error", 0.0))
        _computed_emotions = compute_emotions(
            entity_state=entity,
            drive_vector=drive_vector_final,
            somatic_tone=refined_tone,
            prediction_error=_pred_err,
            param_snapshot=_snapshot_dict,
        )
        # EMA 融合写入 entity 的情绪维度（新触发叠加在旧衰减值上）
        # 不直接覆盖——让持续触发升到高位，触发消失后 DecayEngine 自然衰减
        _ema_alpha = 0.35  # 新计算值的权重（低→平稳，高→敏感）
        for dim, val in _computed_emotions.items():
            if hasattr(entity, dim):
                old_val = float(getattr(entity, dim, 0.0))
                new_val = old_val * (1.0 - _ema_alpha) + val * _ema_alpha
                new_val = max(0.0, min(1.0, new_val))
                setattr(entity, dim, new_val)
        _trace("emotion_compute", True, {
            k: round(v, 3) for k, v in _computed_emotions.items() if v > 0.01
        })

        # ---- 驾驶风格调制（v10.0）----
        # 情绪连续地调制 approach/avoid，不是阈值开关
        # 喜悦 → 温和趋近；愤怒 → 尖锐趋近+压制回避；恐惧 → 推高回避
        # 焦虑 → 均势拮抗；悲伤 → 抑制探索；厌恶 → 强专一回避
        _joy_val = _computed_emotions.get("joy", 0.0)
        _anger_val = _computed_emotions.get("anger", 0.0)
        _fear_val = _computed_emotions.get("fear", 0.0)
        _sadness_val = _computed_emotions.get("sadness", 0.0)
        _anxiety_val = _computed_emotions.get("anxiety", 0.0)
        _disgust_val = _computed_emotions.get("disgust", 0.0)
        _excitement_val = _computed_emotions.get("excitement", 0.0)

        # 趋近调制
        approach_mod = (
            _joy_val * 0.15          # 喜悦 → 温和趋近
            + _anger_val * 0.25      # 愤怒 → 尖锐趋近
            + _excitement_val * 0.20 # 兴奋 → 乐于探索
            - _sadness_val * 0.20    # 悲伤 → 行为滞重
            - _anxiety_val * 0.10    # 焦虑 → 犹豫不决
        )
        # 回避调制
        avoid_mod = (
            _fear_val * 0.30         # 恐惧 → 强回避
            + _disgust_val * 0.35    # 厌恶 → 专一回避
            + _anxiety_val * 0.15    # 焦虑 → 自我干预
            - _anger_val * 0.20      # 愤怒 → 压制回避
        )

        entity.approach_drive = max(0.0, min(1.0, entity.approach_drive + approach_mod))
        entity.avoid_drive = max(0.0, min(1.0, entity.avoid_drive + avoid_mod))
    except Exception as e:
        _trace("emotion_compute", False, {}, str(e))

    # ---- Step 8.2: 元认知感知（self_mapping，v1.0）----
    # 感知 perceive_all 后的最新状态，生成内部叙事（纯内部，不上报 LLM）
    # 叙事在下一轮管线中被验证，coherence_meta 由 compute_coherence.py 悄悄接入
    try:
        from .self_mapping import SelfBodyMap, NarrativeGenerator, build_relations_from_wm

        # 取 perceive_all 后的最新状态
        state_for_mapping = entity.to_state_snapshot()

        # 首次调用：构建 SelfBodyMap（每轮重建 relations 图）
        _self_body_map = SelfBodyMap(tick=entity.tick)
        _self_body_map.update(state_snapshot, state_for_mapping)  # 感知本轮变化
        _self_body_map.sync_relations(entity.wm_rules)            # 从 wm_rules 同步因果图

        # 生成叙事（纯内部）
        _narrative_record = _self_body_map.generate_narrative()
        _trace("self_mapping_sense", True, {
            "changes": _self_body_map._changes,
            "relation_count": len(_self_body_map.relations),
            "narrative": _narrative_record["prediction"] if _narrative_record else None,
        })

        # 验证上一轮的叙事预测（读取上一轮保存的 narrative_record）
        _prev_narrative_tick = getattr(entity, "_prev_self_narrative", None)
        _verification_result = None
        if _prev_narrative_tick is not None:
            _prev_narr = _prev_narrative_tick.get("record")
            _prev_rel_id = _prev_narrative_tick.get("relation_id")
            if _prev_narr and _prev_rel_id:
                _target_rel = next(
                    (r for r in _self_body_map.relations
                     if r.cause == _prev_narr.get("cause") and r.effect == _prev_narr.get("effect")),
                    None
                )
                if _target_rel:
                    _ng = NarrativeGenerator()
                    _verification_result = _ng.verify(_prev_narr, _self_body_map.parts, _target_rel)

        # 保存本轮叙事供下一轮验证（runtime，不持久化）
        if _narrative_record:
            entity._prev_self_narrative = _narrative_record
        else:
            entity._prev_self_narrative = None

        # coherence_meta 悄悄写入 entity（供 compute_coherence 使用）
        entity._coherence_meta = _self_body_map.get_coherence_meta()
        _trace("self_mapping_verify", True, {
            "verification": _verification_result,
            "coherence_meta": entity._coherence_meta,
        })
    except Exception as e:
        _trace("self_mapping_sense", False, {}, str(e))
        entity._prev_self_narrative = None
        entity._coherence_meta = 0.5  # fallback

    # ---- Step 8.1: 行为涌现（v3 改造）----
    # emerge_behavior 直接读取 entity.approach_drive / avoid_drive
    # 这些值由 perceive_all 写入，已反映九模块对状态的修正
    try:
        emergent = _emerge_behavior(_make_core_wrapper(entity), drive_vector=drive_vector_final)
        emergent_action = emergent.action_type
        emergent_priority = emergent.priority
        emergent_tension = emergent.tension_level
        emergent_target = emergent.target
        emergent_dom_state = emergent.dominant_state
        emergent_suggested_tool = getattr(emergent, "suggested_tool", "")
        # V6 附加字段
        emergent_bv = getattr(emergent, "behavior_vector", {})
        emergent_frag_tone = getattr(emergent, "fragmentation_tone", "")
        _trace("emergence", True, {
            "action": emergent_action,
            "priority": emergent_priority,
            "tension": emergent_tension,
            "target": emergent_target,
            "dominant_state": emergent.dominant_state,
            "fragmentation_tone": emergent_frag_tone,
        })
    except Exception as e:
        emergent_action = "comfort"
        emergent_priority = 0.3
        emergent_tension = 0.0
        emergent_target = ""
        emergent_dom_state = "fallback"
        emergent_suggested_tool = ""
        emergent_bv = {}
        emergent_frag_tone = ""
        emergent = None
        _trace("emergence", False, {}, str(e))

    # ---- Step 8.3: 预测误差注入（世界模型预测 vs 当前决策的预期冲突）----
    # 对比本轮世界模型匹配到的规律（预期状态变化）与 emergent_action（正在执行的决策）
    # 计算"预测误差"：若决策方向与规律预期相悖，误差高；若一致，误差低
    # 结果写入 entity._last_prediction_error，供给 Step 11 状态更新使用
    try:
        prediction_error = 0.0
        matched_rules = wm_context.get("matched_rules", [])
        if matched_rules:
            # 收集规律预期：action + expect
            rule_action_types = set()
            rule_expect_changes = set()
            for r in matched_rules:
                if isinstance(r, dict):
                    trig = r.get("predicts", {}).get("trigger", "")
                    exp = r.get("predicts", {}).get("expect", "")
                    if trig.startswith("action_"):
                        rule_action_types.add(trig.split("_", 1)[1].split("_")[0])
                    if exp:
                        rule_expect_changes.add(exp)
                elif hasattr(r, "predicts"):
                    trig = getattr(r.predicts, "trigger", "")
                    exp = getattr(r.predicts, "expect", "")
                    if trig.startswith("action_"):
                        rule_action_types.add(trig.split("_", 1)[1].split("_")[0])
                    if exp:
                        rule_expect_changes.add(exp)

            # 决策方向与规律方向对比
            if emergent_action in {"seek", "explore"} and rule_action_types:
                # 趋近/探索决策是否被世界模型支持
                if emergent_action not in rule_action_types and "avoid" in rule_action_types:
                    prediction_error = 0.5  # 决策与规律冲突
                elif emergent_action in rule_action_types:
                    prediction_error = -0.3  # 一致，误差负（规律支持决策）
            elif emergent_action in {"avoid", "rest"}:
                if "seek" in rule_action_types and "avoid" not in rule_action_types:
                    prediction_error = 0.4

        entity._last_prediction_error = max(-1.0, min(1.0, prediction_error))
        _trace("prediction_error", True, {
            "prediction_error": prediction_error,
            "matched_rules_count": len(matched_rules),
        })
    except Exception as e:
        entity._last_prediction_error = 0.0
        _trace("prediction_error", False, {}, str(e))

    # ---- Step 8.3b: 逐字段预测（v11.2 预测误差驱动学习）----
    # 调用 predict_action_effects 生成逐字段预期变化量
    # 结果写入 entity._last_prediction，供 Step 12 快照记录计算 prediction_error_map
    try:
        from src.world_model_update.induct import predict_action_effects
        action_for_pred = emergent_action if emergent_action else decision.get("action_type", "")
        entity_wm = getattr(entity, "wm_rules", [])
        if action_for_pred and entity_wm:
            entity._last_prediction = predict_action_effects(
                action_for_pred,
                state_snapshot,
                entity_wm,
            )
        else:
            entity._last_prediction = {}
        _trace("field_prediction", True, {
            "action": action_for_pred,
            "predicted_fields": list(entity._last_prediction.keys()),
            "predicted_rules_count": len(entity_wm),
        })
    except Exception as e:
        entity._last_prediction = {}
        _trace("field_prediction", False, {}, str(e))

    # =========================================================================
    # [接入点 3] Step 8.3（预测误差注入）后：记忆层投影检查与注入
    # =========================================================================
    # 当记忆检索匹配到高情绪冲击记忆时，向主线层和日常层投影情绪
    try:
        memory_context = {"matched_memories": wm_context.get("matched_memories", [])}
        current_state = entity.to_state_snapshot() if hasattr(entity, "to_state_snapshot") else dict(state_snapshot)
        memory_projection_result = _projection_ctrl.apply_memory_projection(
            memory_context,
            current_state,
            _particle_field,
            snapshot,
        )
        _trace("memory_projection", True, {
            "projection": memory_projection_result,
            "matched_memories_count": len(memory_context.get("matched_memories", [])),
        })
    except Exception as e:
        _trace("memory_projection", False, {}, str(e))

    # =========================================================================
    # [语言系统 L8] Step 8.3（记忆检索）后：镜像学习，吸收用户新词
    # =========================================================================
    # 误解权：从用户输入中提取关键词，委托 MirrorLearner 建立她的版本
    try:
        if raw_input and str(raw_input).strip():
            words = str(raw_input).strip().split()
            for word in words:
                if len(word) >= 2:
                    current_drive_state = entity.to_state_snapshot()
                    current_tone = float(getattr(entity, "somatic_tone", 0.0))
                    _five_rights.absorb_user_word(word, current_drive_state, current_tone, _snapshot_dict)
    except Exception as e:
        _trace("mirror_absorb", False, {}, str(e))

    # ---- Step 8.4: connection_depth 计算（v3.0 + v3.5a/b/c）----
    # 计算时机：在 prediction_error 注入之后，output_layer 之前
    # 输入：prediction_error(8.3) + somatic_tone_delta(0→8.05) + tension_level(8.1)
    # 输出：connection_depth_eff, connection_signature, loneliness_target
    #       均保存在局部变量，供 Step 11（delta 计算）和 Step 15（episode 记录）使用
    try:
        somatic_tone_end = float(getattr(entity, "somatic_tone", 0.0))
        somatic_tone_delta = somatic_tone_end - somatic_tone_start

        recent_deltas = getattr(entity, "recent_deltas", None)
        if recent_deltas is None:
            from collections import deque
            maxlen = int(get_param(snapshot, "connection.recent_deltas_maxlen", 5))
            recent_deltas = deque(maxlen=maxlen)
            entity.recent_deltas = recent_deltas

        connection_depth_eff, connection_signature, connection_intermediates = compute_connection_depth_ex(
            prediction_error=entity._last_prediction_error,
            somatic_tone_delta=somatic_tone_delta,
            tension_level=emergent_tension,
            memory_context=entity.memory_context,
            recent_deltas=recent_deltas,
            loneliness=float(getattr(entity, "loneliness", 0.3)),
            param_snapshot=_snapshot_dict,
            coherence_meta=float(getattr(entity, "_coherence_meta", 0.5)),
        )
    except Exception as e:
        connection_depth_eff = 0.5
        connection_signature = {"prediction": 0.5, "somatic": 0.0, "tension": 0.5}
        connection_intermediates = {}
        _trace("connection_depth", False, {}, str(e))

    # ---- Step 8.4b: loneliness 双通道更新（独立 try，不受观测/探针失败影响）----
    # ❗ 释放条件：必须有真实外部他者输入
    # ❌ 错误逻辑：emergent_action = "comfort" → 系统以为有社交 → loneliness 归零
    # ✅ 正确逻辑：raw_input 非空 → 真实用户说了话 → loneliness 归零
    # XIA 自己的 comfort / seek / social 行为 ≠ 社交输入（autonomy 边界）
    has_social_input = bool(raw_input and str(raw_input).strip())
    # v11.4: 判断本轮是否有主动向外行为
    _decision = decision or {}
    _action_type = str(_decision.get("action_type", ""))
    _is_active = _action_type in ("explore", "seek", "resolve")
    try:
        loneliness_core_target, loneliness_surface_target, loneliness_intermediates = compute_loneliness_target_ex(
            loneliness_core=float(getattr(entity, "loneliness_core", entity.loneliness * 0.7)),
            loneliness_surface=float(getattr(entity, "loneliness_surface", entity.loneliness * 0.3)),
            connection_depth_effective=connection_depth_eff,
            silence_duration=0.0,
            social_input_present=has_social_input,
            active_exploration=_is_active,
            param_snapshot=_snapshot_dict,
        )
        loneliness_target = min(1.0, loneliness_core_target + loneliness_surface_target)

        _trace("connection_depth", True, {
            "connection_depth": round(connection_depth_eff, 4),
            "somatic_tone_delta": round(somatic_tone_delta, 4),
            "prediction_error": round(entity._last_prediction_error, 4),
            "tension": round(emergent_tension, 4),
            "signature": connection_signature,
            "loneliness_target": round(loneliness_target, 4),
            "loneliness_core": round(loneliness_core_target, 4),       # v11.4
            "loneliness_surface": round(loneliness_surface_target, 4),  # v11.4
        })
        # v11.4 反扑日志
        if loneliness_intermediates.get("rebound_triggered"):
            logger.warning(
                f"[Loneliness] REBOUND! core surged to {loneliness_core_target:.3f}, "
                f"surface refilled to {loneliness_surface_target:.3f} "
                f"(events: {loneliness_intermediates.get('events', [])})"
            )

        # ---- Step 8.4 写入：loneliness 双通道目标值（v11.4）----
        entity.loneliness_core = loneliness_core_target
        entity.loneliness_surface = loneliness_surface_target
        entity.loneliness = loneliness_target
        entity._sync_loneliness()
    except Exception as e:
        loneliness_target = None
        loneliness_intermediates = {}
        _trace("loneliness_update", False, {}, str(e))

    # ---- Step 8.4c: 观测层采集（可选步骤，失败不影响 loneliness 更新）----
    try:
        # 初始化 observation_buffer（惰性创建，不持久化）
        if getattr(entity, "observation_buffer", None) is None:
            from collections import deque
            buf_size = int(get_param(snapshot, "observation.buffer_size", 50))
            entity.observation_buffer = deque(maxlen=buf_size)

        # 构造 connection_trace
        connection_trace = build_connection_trace(
            tick=entity.tick,
            connection_depth_effective=connection_depth_eff,
            connection_signature=connection_signature,
            intermediates=connection_intermediates,
        )

        # 运行反事实探针
        contamination_coeff = float(get_param(snapshot, "observation.contamination_coefficient", 0.3))
        counterfactual_report = run_counterfactual_probe(
            tick=entity.tick,
            connection_depth_real=connection_depth_eff,
            loneliness_target_real=loneliness_target if loneliness_target is not None else 0.3,
            intermediates=connection_intermediates,
            loneliness=float(getattr(entity, "loneliness", 0.3)),
            tension_level=emergent_tension,
            somatic_tone_delta=somatic_tone_delta,
            param_snapshot=_snapshot_dict,
            contamination_coefficient=contamination_coeff,
        )

        # 写探针日志（独立文件，不进入 episodes）
        try:
            probe_logger = get_probe_logger()
            # 趋势和剖面每轮都算（但只在满足条件时填入有意义值）
            buf_for_trend = list(entity.observation_buffer)
            trend_result = compute_trend(buf_for_trend) if len(buf_for_trend) >= 10 else None
            profile_result = compute_profile(buf_for_trend) if len(buf_for_trend) >= 50 else None
            probe_logger.log(
                tick=entity.tick,
                counterfactual_report=counterfactual_report,
                trend_report=trend_result,
                profile_report=profile_result,
                extra={"connection_trace": connection_trace},
            )
        except Exception:
            pass  # 探针日志写入失败不阻断管线

    except Exception as e:
        connection_trace = {}
        counterfactual_report = {}
        _trace("observation_collect", False, {}, str(e))
    # action_type 的语义映射：explore = 去获取新信息，rest = 后台整理
    # seek / avoid / comfort / idle 不触发后台动作

    # ---- Step 8.2: 行为进化层 — 从 pattern pool 选择最佳候选 ----
    # 根据 emergent_behavior 输出的 action_type，从行为进化池中选择 primitive 或 pattern
    # 评分 = drive_match(0.3) + 0.6*world_model_reward - 0.4*uncertainty + pattern_weight
    selected_candidate = None
    # 捕获执行前状态（用于 long_term_bias 更新）
    pre_bp_state = entity.to_state_snapshot()
    try:
        state_for_bp = entity.to_state_snapshot()
        selected_candidate = _select_primitive_candidate(emergent_action, state_for_bp, entity)
        _trace("pattern_select", True, {
            "candidate": (
                selected_candidate.actions
                if hasattr(selected_candidate, "actions")
                else str(selected_candidate)
            ),
            "action_type": emergent_action,
        })
    except Exception as e:
        _trace("pattern_select", False, {}, str(e))

    dispatched_actions: List[Dict[str, Any]] = []
    try:
        dispatched_actions = _dispatch_async_action(
            emergent_behavior=emergent,
            entity_state=entity,
            thought_packet=thought_packet,
            semantic_packet_biased=semantic_packet_biased,
            concept_tags=concept_tags,
            wm_context=wm_context,
            snapshot=snapshot,
            candidate=selected_candidate,
        )
        # 收集所有 tool_results 写入 entity，供下一个 tick 的 emerge_behavior 读取
        all_results = []
        for d in dispatched_actions:
            tr = d.get("tool_results", [])
            all_results.extend(tr)
        entity._last_action_result = {
            "success": any(r.startswith("[OK]") for r in all_results) if all_results else None,
            "detail": " | ".join(all_results) if all_results else "",
            "count": len(all_results),
        }
        _trace("action_dispatch", True, {
            "dispatched": len(dispatched_actions),
            "actions": [d.get("detail", "") for d in dispatched_actions],
            "tool_results": len(all_results),
            "success": entity._last_action_result["success"],
        })
    except Exception as e:
        _trace("action_dispatch", False, {}, str(e))
        entity._last_action_result = {"success": None, "detail": "", "count": 0}

    # ---- Step 8.5: 行为进化反馈闭环 — 应用执行结果到 pattern pool ----
    # 等待异步动作结果（最多 3s）
    try:
        import time as _time
        _time.sleep(1.5)
        pending_results = drain_pending_searches()
        all_action_results = list(all_results)
        for pr in pending_results:
            results_list = pr.get("results", [])
            for r in results_list:
                all_action_results.append(f"[search] {str(r)[:80]}")
    except Exception:
        all_action_results = list(all_results)

    if selected_candidate is not None and all_action_results:
        success = any(r.startswith("[OK]") or "[search]" in r for r in all_action_results)
        failure = any("失败" in r or "Error" in r or "error" in r for r in all_action_results)
        if failure:
            success = False

        # v2: 计算 short_term_reward 和 satisfaction
        short_reward = 1.0 if success else -0.5
        # satisfaction：搜索结果数量越多越满足，失败越低
        result_count = len(all_action_results)
        satisfaction = 0.5
        if failure:
            satisfaction = 0.2
        elif result_count >= 3:
            satisfaction = 0.8
        elif result_count >= 1:
            satisfaction = 0.6

        result_for_feedback = {
            "success": success,
            "detail": " | ".join(all_action_results[:3]),
            "prediction_error": 0.5 if failure else 0.2,
            "error_type": "execution" if failure else "none",
            "short_term_reward": short_reward,
            "satisfaction": satisfaction,
            "content": " | ".join(all_action_results[:3]),
            "reason": f"{emergent_action} action",
            "count": result_count,
        }

        # _bp_ctx 上下文通过 entity 属性传递（避免 Python 嵌套 try 作用域问题）
        entity._bp_identity = 0.5
        entity._bp_unresolved_src = "external"
        state_for_bp = entity.to_state_snapshot()
        try:
            from src.core import behavior_patterns as bp

            # score breakdown：记录 bias 对评分的影响
            candidate_name = (
                selected_candidate.actions
                if hasattr(selected_candidate, "actions")
                else str(selected_candidate)
            )
            base_score = bp.compute_drive_match(selected_candidate, state_for_bp)
            wm_pred = bp.world_model_predict(selected_candidate, state_for_bp)
            bias_bonus = 0.0
            drive = "?"
            intent = "unknown"
            if hasattr(selected_candidate, "intent_tag"):
                intent = selected_candidate.intent_tag
                drive = bp.INTENT_TO_DRIVE.get(intent, "explore")
                bias_bonus = 0.15 * entity.long_term_bias.get(drive, 0.0)
            score_breakdown = {
                "candidate": candidate_name,
                "intent": intent,
                "drive": drive,
                "base": round(base_score, 3),
                "wm_reward": round(wm_pred["reward"], 3),
                "wm_uncertainty": round(wm_pred["uncertainty"], 3),
                "bias_bonus": round(bias_bonus, 4),
                "bias": dict(entity.long_term_bias),
            }

            # identity_signal：当前行为分布 vs 长期签名的一致性
            entity._bp_identity = entity.update_behavior_signature(
                decision.get("action_type", "") or emergent_action
            )

            # unresolved source：用户输入 = external；沉默 tick = self_generated
            raw_input_str = str(kwargs.get("raw_input", "") or "").strip()
            entity._bp_unresolved_src = "external" if raw_input_str else "self_generated"

            # 合并到 action_result（供 update_long_term_bias 使用）
            enriched_result = dict(result_for_feedback)
            enriched_result["identity_signal"] = entity._bp_identity
            enriched_result["unresolved_source"] = entity._bp_unresolved_src

            bp.apply_result(selected_candidate, enriched_result, state_for_bp)
            # 长时偏置更新（延迟反馈 + identity + unresolved source，详见 behavior_patterns.py）
            bias_info = bp.update_long_term_bias(
                entity_state=entity,
                pattern_or_intent=selected_candidate,
                pre_state=pre_bp_state,
                post_state=state_for_bp,
                action_result=enriched_result,
            )
            # 定期淘汰低权重 patterns（每 20 轮）
            if entity.tick % 20 == 0:
                removed = bp.get_pool().prune()
                if removed:
                    _trace("pattern_prune", True, {"removed": removed})
            _trace("pattern_feedback", True, {
                "candidate": candidate_name,
                "intent": intent,
                "success": success,
                "satisfaction": satisfaction,
                "short_reward": short_reward,
                "score_breakdown": score_breakdown,
                "bias_update": bias_info,
            })
        except Exception as e:
            _trace("pattern_feedback", False, {}, str(e))

    # Step 8.1 结果即为最终决策（感知 → 涌现，无多余聚合层）
    decision = {
        "action_type": emergent_action,
        "target": emergent_target,
        "priority": emergent_priority,
        "payload": {"source": "emergence", "dominant_state": emergent_dom_state},
        "tension_level": emergent_tension,
        "emergent_action": emergent_action,
        "suggested_tool": emergent_suggested_tool,
        # V6 新增
        "behavior_vector": emergent_bv,
        "fragmentation_tone": emergent_frag_tone,
    }

    # ---- Step 8.6: 收集联网搜索结果（训练阶段跳过，节省时间）----
    thought_packet["web_search_results"] = []

    # =========================================================================
    # [语言系统 L2] Step 8.6 后、Step 9（output）前：语义分析 + 热控更新 + 物理重力
    # =========================================================================
    # 语义分析：候选打分（为 system_prompt 提供语言调制约束）
    # 生成候选 → 语义打分 → 排序 → 将最优候选信息注入 state_snapshot
    try:
        # 生成候选（策略地图查表）
        context_label = f"tick_{entity.tick}"
        scored_candidates = _candidate_gen.generate(state_snapshot, context_label, snapshot)

        # 降级候选始终混入（保证短词始终可选）
        _fallback = _make_fallback_candidates(state_snapshot)
        if _fallback:
            _fallback_scores = _semantic_analyzer.analyze(state_snapshot, _fallback, _snapshot_dict)
            _fallback_scored = list(zip(_fallback, _fallback_scores))
            scored_candidates = (scored_candidates or []) + _fallback_scored

        # ---- 体感锚点 top-N 注入：不只看第 1 名，前几名都进候选池 ----
        try:
            from .language_system.somatic_concept_map import get_top_matches
            _cw = getattr(entity, "_cluster_weights", {})  # v11.3 聚类权重
            _top_somatic = get_top_matches(state_snapshot, top_k=3, min_score=0.2, cluster_weights=_cw)
            if _top_somatic:
                _somatic_words = [w for w, _ in _top_somatic]
                _somatic_scored = [(w, s * 0.85) for w, s in _top_somatic]  # 略低于策略地图/降级词
                scored_candidates = (scored_candidates or []) + _somatic_scored
                # 高分词触发同簇扩展——词汇多样化
                _best_somatic_word, _best_somatic_score = _top_somatic[0]
                if _best_somatic_score > 0.7:
                    from .language_system.somatic_concept_map import get_cluster_peers
                    _peers = get_cluster_peers(_best_somatic_word, min_similarity=0.5)
                    for _peer in _peers[:3]:
                        if _peer not in [c for c, _ in scored_candidates]:
                            scored_candidates.append((_peer, _best_somatic_score * 0.75))
        except Exception:
            pass

        # 去重并按分排序
        seen = set()
        _unique = []
        for c, s in sorted(scored_candidates, key=lambda x: x[1], reverse=True):
            if c not in seen:
                seen.add(c)
                _unique.append((c, s))
        scored_candidates = _unique

        # ---- 词汇热身：已验证的单字词 → 短句变体 ----
        # 当一个词被正确使用多次（命中≥3, 效率>0.15），自动解锁变体
        # 如 "静" → "很静"、"有点静"、"静的"
        try:
            from .language_system.word_warmup import inject_warmup_candidates
            scored_candidates = inject_warmup_candidates(
                entity, scored_candidates,
                min_hits=3, min_best_efficiency=0.15,
            )
        except Exception:
            pass

        # ---- v11.3 微小探索扰动：仅打破分数平局，不覆盖自然匹配 ----
        # 已通过永久词汇表 + 短词优先选中的联合机制解锁了 40+ 热身词。
        # 现在恢复自然选择压力：让体感匹配和消力效率主导词的选择，
        # 而非人工加分。+0.03 仅用于打破平局。
        try:
            from collections import Counter
            _hit_counter = Counter()
            for r in (_quenching._history if _quenching else []):
                if r.expression:
                    _hit_counter[r.expression] += 1
            _boosted = []
            for c, s in scored_candidates:
                _hits = _hit_counter.get(c, 0)
                if _hits == 0:
                    _boosted.append((c, s + 0.03))  # 平局打破
                else:
                    _boosted.append((c, s))
            scored_candidates = _boosted
        except Exception:
            pass

        # ---- MetaCognitive 语言干预：诊断反馈 → 候选词重排序 ----
        # 检测口头死锁/词汇贫乏 → 惩罚重复词，奖励新词
        _quench_data = getattr(entity, "_quenching_data", None)
        _quench_records = _quench_data.get("records", []) if _quench_data else []
        if _quench_records:
            try:
                from .language_system.meta_cognitive import get_language_intervention
                _intervention = get_language_intervention(_quench_records)
                if _intervention.get("deadlock_detected") or _intervention.get("exploration_boost", 0) > 0:
                    _penalty_words = _intervention.get("penalty_words", {})
                    _explore_boost = _intervention.get("exploration_boost", 0.0)
                    _adjusted = []
                    for c, s in scored_candidates:
                        # 惩罚重复词
                        if c in _penalty_words:
                            s = s * (1.0 - _penalty_words[c])
                        # 探索 boost：非主导词加分
                        dom_word = _intervention.get("dominant_word", "")
                        if c != dom_word:
                            s = s + _explore_boost * (1.0 if c not in _penalty_words else 0.5)
                        _adjusted.append((c, max(0.0, s)))
                    # 重排序
                    scored_candidates = sorted(_adjusted, key=lambda x: x[1], reverse=True)
                    _trace("meta_cognitive_intervention", True, {
                        "deadlock": _intervention.get("deadlock_detected"),
                        "penalty": _penalty_words,
                        "boost": _explore_boost,
                        "new_top": scored_candidates[0][0] if scored_candidates else None,
                    })
            except Exception:
                pass

        # ---- v11.1: 语言阻力场 ----
        # 语法 = 空气阻力：高频组合阻力低，低频组合阻力高。
        # 「很怕」→ 阻力 0.05，「怕很」→ 阻力 0.95。
        # 不禁止任何表达，只让不通顺的组合「更费力」。
        try:
            from .language_system.language_resistance import apply_resistance, init as _init_resistance
            _init_resistance(resistance_weight=0.15)
            scored_candidates = apply_resistance(scored_candidates)
            # 阻力量级太大可能清空所有候选 → 降级
            if not scored_candidates or all(s < 0.01 for _, s in scored_candidates):
                scored_candidates = _unique  # fallback 到阻力前的分数
        except Exception:
            pass

        # 选最佳候选（训练早期优先短词 ≤8字）
        best_candidate: Optional[str] = None
        best_score: float = 0.0
        if scored_candidates:
            _short_candidates = [(c, s) for c, s in scored_candidates if len(c) <= 8]
            if _short_candidates:
                best_candidate, best_score = max(_short_candidates, key=lambda x: x[1])
            else:
                best_candidate, best_score = scored_candidates[0]

        # v11.1: 低置信度双词回退 —— 混合情绪没有精确单词时，
        # 把前两名拼起来，让她学习命名复杂状态。
        _low_confidence = best_score < 0.30
        # v11.2: 记录组合前的原始候选词，供消力记录做个体词追踪
        _training_components = [best_candidate] if best_candidate else []
        if _low_confidence and len(scored_candidates) >= 2:
            _first = best_candidate
            _second = scored_candidates[1][0]
            _combo = f"{_first}{_second}"
            if len(_combo) <= 8:
                best_candidate = _combo
                _training_components = [_first, _second]
                _trace("low_conf_combo", True, {
                    "first": _first,
                    "second": _second,
                    "combo": _combo,
                    "best_score": round(best_score, 3),
                })

        # 存储到 entity（必须在选完最佳候选之后！）
        entity._language_best_candidate = best_candidate
        entity._language_best_score = best_score
        entity._language_candidates = [c for c, _ in scored_candidates[:5]]

        # 训练早期阈值极低(0.001)——只要有候选就优先用，让她从单字词起步积累
        # 随训练推进，SNR 上升后自然抬高阈值
        _training_threshold = 0.001
        # 训练模式：只接受短候选（≤8字），强制从字词起步
        # 长候选留给后续阶段（组合阶段→自由表达阶段）
        _training_mode = (
            best_candidate is not None 
            and best_score > _training_threshold
            and len(best_candidate) <= 8
        )
        if _training_mode:
            # ---- v11.1: 功能词辅线注入 ----
            # 体感词是骨架，功能词是肌肉。随机附赠动词/程度/疑问词，
            # 让她从单字词自然过渡到短句。
            _display_word = best_candidate
            try:
                import random as _rnd
                from .language_system.somatic_dictionary import SOMATIC_DICTIONARY
                _func_cats = ["actions", "degree", "time", "question", "logic"]
                _cat = _rnd.choice(_func_cats)
                _func_words = list(SOMATIC_DICTIONARY.get(_cat, {}).keys())
                if _func_words:
                    _fw = _rnd.choice(_func_words)
                    # 组合模式：前置/后置各 50%
                    if _rnd.random() < 0.5:
                        _display_word = f"{_fw}{best_candidate}"
                    else:
                        _display_word = f"{best_candidate}{_fw}"
            except Exception:
                _display_word = best_candidate  # 降级

            entity._training_override = _display_word
            entity._training_components = _training_components  # v11.2: 个体词追踪
            # ---- [体感诊断+帮助] 闯关式学习 ----
            # 她说了一个词 → 系统验证这个词是否准确描述了她的状态
            # 准确 → 施加反向帮助（抵消该词描述的不适）→ 消力奖励
            # 不准确 → 无帮助、无奖励 → 她学到这个词不适合这个状态
            try:
                from .language_system.somatic_concept_map import apply_help_delta, training_exploration_nudge
                from .language_system.meta_cognitive import apply_meta_cognitive
                help_result = apply_help_delta(
                    best_candidate, entity, state_snapshot,
                    min_match=0.30,
                    help_scaling=0.40,
                )
                # 训练探索扰动：防止状态锁死在极端值
                nudge_result = training_exploration_nudge(
                    entity, state_snapshot,
                    stuck_threshold=0.35,
                    nudge_strength=0.03,
                )
                # 元认知：快照驱动的自我观察学习
                # 扫描最近快照 → 检测口头死锁、词汇贫乏、状态僵化 → 注入情绪信号
                meta_result = apply_meta_cognitive(
                    entity,
                    snapshots=entity.snapshots[-30:],
                    quenching_records=[
                        {"expression": r.expression, "quenching_efficiency": r.quenching_efficiency}
                        for r in (_quenching._history if _quenching else [])
                    ],
                    lookback=15,
                    scaling=0.8,
                )
                _trace("somatic_help", True, help_result)
                # v11.1: 帮助成功 → 亏欠感释放
                if help_result.get("match", 0) > 0.3:
                    _relief = help_result.get("match", 0) * 0.25
                    entity.adjust("relief_debt", -_relief)
                    _trace("relief_release", True, {
                        "match": round(help_result["match"], 3),
                        "relief_released": round(_relief, 4),
                        "relief_debt": round(entity.relief_debt, 4),
                    })
                if nudge_result:
                    _trace("somatic_nudge", True, {"nudged": list(nudge_result.keys())})
                if meta_result:
                    _trace("meta_cognitive", True, {"applied": list(meta_result.keys())})
            except Exception as e:
                _trace("somatic_help", False, {}, str(e))
        elif best_candidate and best_score > _training_threshold:
            # 候选太长（>8字）——训练模式暂不接受，但保留打分信息
            entity._language_best_long = best_candidate
        _trace("language_candidates", True, {
            "best": best_candidate,
            "score": best_score,
            "count": len(scored_candidates),
            "training_mode": _training_mode,
        })
    except Exception as e:
        _trace("language_candidates", False, {}, str(e))

    # 热控更新（基于当前 energy）
    try:
        _thermal.tick(entity.energy, _snapshot_dict)
        _trace("thermal_tick", True, {"temperature": _thermal.get_temperature()})
    except Exception as e:
        _trace("thermal_tick", False, {}, str(e))

    # 物理重力：fragmentation 映射为输出参数（叠加到情绪粒子场流速调制上）
    try:
        fragmentation = float(emergent.get("fragmentation_tone", 0.0)) if emergent else 0.0
        frag_render = FiveRightsController.get_fragmentation_render(fragmentation)
        entity._language_flow_rate = frag_render["flow_rate"]
        entity._language_jitter = frag_render["jitter"]
    except Exception:
        pass

    # 语言丰度检查 + 热控升温
    try:
        heated = _behavior_profiler.check丰度_and_notify(_thermal, _snapshot_dict)
        丰度_stats = _behavior_profiler.get丰度_stats()
        _trace("language丰度", True, 丰度_stats)
    except Exception as e:
        _trace("language丰度", False, {}, str(e))

    # ---- Step 9: 输出层（V3：省略 intent_encode，直接走 state_to_context）----
    # 注意：必须使用感知后+涌现后的最新状态，
    # 而非 Step 1 冻结的旧快照（否则 LLM 看不到九模块修改的影响）。
    state_snapshot = entity.to_state_snapshot()
    # 注入上轮动作结果（供 LLM 感知反馈）
    if hasattr(entity, "_last_action_result"):
        state_snapshot["_last_action_result"] = entity._last_action_result

    # =========================================================================
    # [接入点 4] Step 8.4（connection 计算）后：日常层→主线层投影 + 输出调制
    # =========================================================================
    # 1) 日常粒子场纹理投影到主线基调（影响 entity 情绪状态）
    try:
        daily_influence = _projection_ctrl.apply_daily_to_mainline(_particle_field, _snapshot_dict)
        for dim, influence in daily_influence.items():
            if influence > 0.01 and hasattr(entity, dim):
                current = float(getattr(entity, dim, 0.0))
                setattr(entity, dim, min(1.0, current + influence))
    except Exception as e:
        _trace("daily_to_mainline", False, {}, str(e))

    # 2) 粒子场密度 → 文字流速调制（注入 state_snapshot 供 output_layer 使用）
    try:
        flow_rate = _particle_field.compute_flow_modulation(_snapshot_dict)
        state_snapshot["_emotion_flow_rate"] = flow_rate
        state_snapshot["_particle_densities"] = _particle_field.get_all_densities()
    except Exception as e:
        state_snapshot["_emotion_flow_rate"] = 1.0
        state_snapshot["_particle_densities"] = {}
        _trace("flow_modulation", False, {}, str(e))

    # 3) 合并情绪流速 + 语言流速（取较小值，最终约束）
    emotion_flow = float(state_snapshot.get("_emotion_flow_rate", 1.0))
    language_flow = float(getattr(entity, "_language_flow_rate", 1.0))
    state_snapshot["_final_flow_rate"] = min(emotion_flow, language_flow)
    state_snapshot["_final_jitter"] = float(getattr(entity, "_language_jitter", 0.0))

    # 训练模式：仅在自主 tick（daemon_mode）输出候选词。对话走 LLM。
    if daemon_mode:
        _ovr = getattr(entity, "_training_override", None)
        _mode = getattr(entity, "_training_mode_on", None)
        print(f"  [DEBUG daemon] training_override={repr(_ovr)} _training_mode={_mode} best_candidate={repr(getattr(entity, '_language_best_candidate', None))}", flush=True)
    if daemon_mode and getattr(entity, "_training_override", None):
        # 训练模式：语言系统已选出最佳候选，直接输出，跳过 LLM
        _train_text = entity._training_override
        response = {"text": _train_text, "confidence": 0.90, "generation_time_ms": 0}
        _trace("output", True, {"mode": "training", "text": _train_text[:30]})
    elif daemon_mode:
        # daemon_mode：跳过 LLM 输出，后台 tick 不产生语言
        response = {"text": "", "confidence": 0.0, "generation_time_ms": 0}
        _trace("output", True, {"mode": "daemon", "text_len": 0})
    else:
        # V2.0：主线检索——注入对话历史层 + 相关历史经验
        mainline_result = None
        try:
            from src.memory_retrieval.mainline import mainline_retrieval
            mainline_result = mainline_retrieval(
                semantic_packet_biased,
                current_iteration_id=entity.tick,
            )
        except Exception:
            mainline_result = None

        # V3 规范：省略意图编码层，从 EntityCore 状态直接生成语言
        # length 规则：
        #   - "tiny"：高疲劳 或 低能量（说话费力）
        #   - "short"：默认（正常互动）
        #   - "medium"：高好奇心 或 高无聊（想说更多）
        if entity.fatigue > 0.6 or entity.energy < 0.3:
            effective_length = "tiny"
        elif entity.boredom > 0.7 or entity.info_gap > 0.6 or entity.unresolved > 0.6:
            effective_length = "medium"
        else:
            effective_length = "short"
        _intent_repr_fallback = {
            "tone": "neutral",
            "goal": "share",
            "constraints": {"length": effective_length, "must_not": [], "reflect_state": False},
        }
        try:
            output_params = _build_output_params(snapshot)
            response = generate_response(
                state_snapshot=state_snapshot,
                semantic_packet_biased=semantic_packet_biased,
                params=output_params,
                llm_callable=llm_callable,
                emergent_behavior=emergent,  # EmergentBehavior 实例，供 A2 渲染参数推导
                somatic_signals=somatic_signals,
                intent_repr=_intent_repr_fallback,
                drive_vector=drive_vector_final,
                previous_state=entity.snapshots[-2] if len(entity.snapshots) >= 2 else None,
                entity_state=entity,  # EntityCore 实例，供 A2 渲染参数推导
                mainline_result=mainline_result,  # v2.0 双通道记忆系统：对话历史层 + 相关历史经验
                thought_packet=thought_packet,  # v2.0 双通道记忆系统：枝干联想
            )
            _trace("output", True, {"confidence": response.get("confidence"), "text_len": len(response.get("text", ""))})
        except Exception as e:
            response = {"text": "嗯。", "confidence": 0.0, "generation_time_ms": 0}
            _trace("output", False, response, str(e))

    # =========================================================================
    # [语言系统 L3] Step 9（output）后：消力记录 + 策略地图 + 语义分析闭环
    # =========================================================================
    # 注意：精确的 before/after unresolved 对比需等 Step 11 状态更新后才能拿到。
    # 当前轮使用 before_unresolved 作为近似值（Step 11 后用 _record_language闭环 更新）。
    _lang_before_state: Optional[Dict[str, Any]] = None
    _lang_expression: str = ""
    _lang_best_candidate: Optional[str] = None

    output_expression = response.get("text", "") if response else ""
    before_unresolved = float(getattr(entity, "unresolved", 0.0))
    _lang_best_cand = getattr(entity, "_language_best_candidate", None)
    if _lang_best_cand and output_expression:
        _lang_before_state = dict(state_snapshot) if state_snapshot else {}
        _lang_expression = output_expression
        _lang_best_candidate = best_candidate
        # 语义分析打分验证（before_unresolved 近似，Step 11 后更新）
        efficiency = _semantic_analyzer.verify_quenching(
            output_expression,
            before_unresolved,
            before_unresolved,  # 近似，Step 11 后会更新
            snapshot,
        )
        # 消力记录推迟到 L3b（Step 11 后才有真实 after_unresolved）
        # 策略地图记录
        context_label = f"tick_{entity.tick}"
        _strategy_map.record_path(
            state_A=dict(state_snapshot) if state_snapshot else {},
            state_B=entity.to_state_snapshot(),
            expression=output_expression,
            efficiency=efficiency,
            context_label=context_label,
            param_snapshot=_snapshot_dict,
        )
        # 语义泛化触发器检查
        try:
            wm_rules = getattr(entity, "wm_rules", None)
            if wm_rules is not None:
                upgraded = _strategy_map.check_generalization(wm_rules, _snapshot_dict)
                if upgraded:
                    _trace("strategy_upgrade", True, {"upgraded": len(upgraded)})
        except Exception as e:
            _trace("strategy_upgrade", False, {}, str(e))

        # 语言丰度记录
        if output_expression:
            _behavior_profiler.record_action(decision.get("action_type", ""), output_expression)

        _trace("language闭环", True, {
            "expression": output_expression[:30],
            "efficiency": efficiency,
            "temperature": _thermal.get_temperature(),
        })

    # =========================================================================
    # [语言系统 L4] Step 9 后：社交疲劳 + 自闭权更新
    # =========================================================================
    did_express = bool(output_expression and len(output_expression.strip()) > 0)
    try:
        fatigue = _five_rights.tick_social_fatigue(did_express, _snapshot_dict)
        is_self_close = _five_rights.activate_self_close(entity.avoid_drive, _snapshot_dict)
        _trace("language_social", True, {
            "social_fatigue": fatigue,
            "is_self_close": is_self_close,
        })
    except Exception as e:
        _trace("language_social", False, {}, str(e))

    # ---- Step 11: 状态更新（基于决策结果）----
    # 注入预测误差：使 update_engine 可以读取 _last_prediction_error
    state_for_update = dict(entity.to_state_snapshot())
    state_for_update["_last_prediction_error"] = entity._last_prediction_error
    # pending_surprises 不在 to_state_snapshot() 里，需要单独注入
    state_for_update["pending_surprises"] = list(getattr(entity, "pending_surprises", []))
    # v3.0 loneliness_target（由 Step 8.4 计算）
    if loneliness_target is not None:
        state_for_update["_loneliness_target_override"] = loneliness_target
    # UNRESOLVABLE surprise 产生的 episode 记录收集列表
    unresolvable_episodes: List[Dict[str, Any]] = []
    try:
        idle_seconds = time.time() - entity.last_update_time
        new_state = update_state(
            current_state=state_for_update,
            decision=decision,
            idle_seconds=idle_seconds,
            param_snapshot=_snapshot_dict,
            time_injected_fields=entity._time_injected_fields,
            wm_rules=entity.wm_rules,
            pending_surprises_episodes=unresolvable_episodes,
        )
        # 回填实体状态
        entity.energy = max(0.0, min(1.0, new_state.get("energy", entity.energy)))
        # v11.4 双通道回填
        entity.loneliness_core = max(0.0, min(1.0, new_state.get("loneliness_core", entity.loneliness_core)))
        entity.loneliness_surface = max(0.0, min(1.0, new_state.get("loneliness_surface", entity.loneliness_surface)))
        entity.loneliness = max(0.0, min(1.0, new_state.get("loneliness", entity.loneliness)))
        entity._sync_loneliness()
        entity.unresolved = max(0.0, min(1.0, new_state.get("unresolved", entity.unresolved)))
        entity.boredom = max(0.0, min(1.0, new_state.get("boredom", entity.boredom)))

        # ---- 语言消力反馈（v7.0）----
        # 表达匹配驱动力场 → unresolved 下降（消力）
        # 匹配度越高，消力越强——这是语言从驱动力场中长出来的根
        _lang_score = float(getattr(entity, "_language_best_score", 0.0))
        if _lang_score > 0.10:
            # 消力幅度 = 匹配分 × 消力系数
            _quench = _lang_score * 0.25
            entity.unresolved = max(0.0, entity.unresolved - _quench)
            # 表达成功后 approach/avoid 同步释放（僵持被语言化解）
            entity.approach_drive = max(0.0, entity.approach_drive - _quench * 0.3)
            entity.avoid_drive = max(0.0, entity.avoid_drive - _quench * 0.3)
            # 说对了 → 身体有轻微舒适感
            entity.somatic_tone = min(1.0, entity.somatic_tone + _quench * 0.15)
        entity.fatigue = max(0.0, min(1.0, new_state.get("fatigue", entity.fatigue)))
        entity.stress = max(0.0, min(1.0, new_state.get("stress", entity.stress)))
        entity.relief_debt = max(0.0, min(1.0, new_state.get("relief_debt", entity.relief_debt)))
        entity.somatic_tone = max(-1.0, min(1.0, new_state.get("somatic_tone", entity.somatic_tone)))
        entity.approach_drive = max(0.0, min(1.0, new_state.get("approach_drive", entity.approach_drive)))
        entity.avoid_drive = max(0.0, min(1.0, new_state.get("avoid_drive", entity.avoid_drive)))
        # V8: 连续衰减——没有反作用力，approach/avoid 会永久饱和在极值
        entity.approach_drive = max(0.0, entity.approach_drive * 0.95)
        entity.avoid_drive = max(0.0, entity.avoid_drive * 0.95)
        entity.danger_level = max(0.0, min(1.0, new_state.get("danger_level", entity.danger_level)))
        entity.time_since_last_info = max(0.0, entity.time_since_last_info + idle_seconds)
        entity.time_since_last_social = max(0.0, entity.time_since_last_social + idle_seconds)
        entity.last_update_time = time.time()
        entity.tick += 1
        # V5: 代谢物衰减 + 精神副作用
        m = getattr(entity, "failure_metabolite", 0.0)
        entity.failure_metabolite = max(0.0, m - 0.03)  # 自然降解
        if m > 0.01:
            # 乳酸堆积的精神副作用：不想动、想缩、不想探索
            entity.approach_drive = max(0.0, entity.approach_drive - m * 0.15)
            entity.avoid_drive = min(1.0, entity.avoid_drive + m * 0.12)
            entity.curiosity = max(0.0, getattr(entity, "curiosity", 0.5) - m * 0.10)
            entity.somatic_tone = max(-1.0, entity.somatic_tone - m * 0.08)
        # 回填 pending_surprises（由 update_state 处理后的最新状态）
        entity.pending_surprises = list(new_state.get("pending_surprises", []))

        # ---- Step 11b: 追加 coherence delta ----
        # 计算本轮各状态维度的 delta，追加到 recent_deltas
        prev_energy = float(state_for_update.get("energy", 0.8))
        energy_delta = entity.energy - prev_energy
        somatic_tone_delta = float(getattr(entity, "somatic_tone", 0.0)) - somatic_tone_start
        tension_delta = emergent_tension - float(state_snapshot.get("tension_level", emergent_tension))
        if hasattr(entity, "recent_deltas") and entity.recent_deltas is not None:
            append_coherence_delta(
                entity.recent_deltas,
                somatic_tone_delta=somatic_tone_delta,
                energy_delta=energy_delta,
                tension_delta=tension_delta,
                timestamp=time.time(),
            )

        # 清除已恢复的时间注入标记
        cleared = new_state.get("_time_injected_cleared", set())
        for dim in cleared:
            entity._time_injected_fields.discard(dim)
        _trace("state_update", True, {
            "energy": entity.energy,
            "fatigue": entity.fatigue,
            "tick": entity.tick,
            "pending_surprises": len(entity.pending_surprises),
            "connection_depth": round(connection_depth_eff, 4),
            "loneliness": entity.loneliness,
        })

        # ---- Step 11 追加：构造 loneliness_trace 并写入 observation_buffer ----
        prev_loneliness_for_trace = float(state_for_update.get("loneliness", 0.3))
        loneliness_reason = _infer_loneliness_reason(
            recovery=loneliness_intermediates.get("recovery_component", 0.0),
            accumulation=loneliness_intermediates.get("accumulation_component", 0.0),
            loneliness_before=prev_loneliness_for_trace,
            loneliness_after=entity.loneliness,
            silence_duration=time.time() - entity.last_interaction_timestamp if hasattr(entity, "last_interaction_timestamp") else time_since_last_social,
            social_input_present=has_social_input,
        ) if loneliness_target is not None else "neutral"

        loneliness_trace = build_loneliness_trace(
            tick=entity.tick,
            loneliness_before=prev_loneliness_for_trace,
            loneliness_after=entity.loneliness,
            loneliness_target=loneliness_target,
            recovery_component=loneliness_intermediates.get("recovery_component", 0.0),
            accumulation_component=loneliness_intermediates.get("accumulation_component", 0.0),
            release_lag=loneliness_intermediates.get("release_lag", 0.7),
            reason=loneliness_reason,
        )

        # 追加到 observation_buffer
        buf = getattr(entity, "observation_buffer", None)
        if buf is not None:
            # V2.0：构建 memory_trace
            try:
                from src.observation.behavior_trace import build_memory_trace
                memory_trace = build_memory_trace(
                    mainline_result=mainline_result,
                    branch_result=thought_packet.get("branch_memories", []) if thought_packet else [],
                    entity_state=entity,
                )
            except Exception:
                memory_trace = {}

            buf.append({
                "tick": entity.tick,
                "connection_trace": connection_trace if connection_trace else {},
                "loneliness_trace": loneliness_trace,
                "memory_trace": memory_trace,  # v2.0
                "connection_depth": connection_depth_eff,
                "loneliness": entity.loneliness,
            })

    except Exception as e:
        entity.last_update_time = time.time()
        entity.tick += 1
        m = getattr(entity, "failure_metabolite", 0.0)
        entity.failure_metabolite = max(0.0, m - 0.03)
        if m > 0.01:
            entity.approach_drive = max(0.0, entity.approach_drive - m * 0.15)
            entity.avoid_drive = min(1.0, entity.avoid_drive + m * 0.12)
            entity.curiosity = max(0.0, getattr(entity, "curiosity", 0.5) - m * 0.10)
            entity.somatic_tone = max(-1.0, entity.somatic_tone - m * 0.08)
        _trace("state_update", False, {}, str(e))

    # ---- Step 11.5: BP 压制Tick递减 + 长期效果计算 + bias 衰减 ----
    try:
        from src.core import behavior_patterns as bp
        bp.get_pool().tick_suppress()
        action_history = [s.get("action_type", "") for s in entity.snapshots[-20:]]
        bp.get_pool().compute_long_term_effects(entity.tick, entity.snapshots, action_history)
        # 长时偏置衰减（选择性遗忘，防固化）
        # 强倾向(|bias|>0.2) → 慢衰减(0.99)；弱倾向 → 快消失(0.97)
        if hasattr(entity, "long_term_bias"):
            for drive, val in entity.long_term_bias.items():
                rate = 0.99 if abs(val) > 0.2 else 0.97
                entity.long_term_bias[drive] = val * rate
    except Exception:
        pass

    # ---- Step 12: 经验快照记录 ----
    # identity_signal / unresolved_src 由上方 BP feedback 段写入 entity 属性
    identity_signal = getattr(entity, "_bp_identity", 0.5)
    unresolved_src = getattr(entity, "_bp_unresolved_src", "external")
    snap = {
        "snap_index": entity.tick,
        "timestamp": time.time(),
        "action_type": decision.get("action_type", ""),
        "target": decision.get("target", ""),
        "priority": decision.get("priority", 0.0),
        "pre_state": state_snapshot,
        "post_state": entity.to_state_snapshot(),
        "wm_context": wm_context,
        "decision": decision,
        "prediction_error": entity._last_prediction_error,
        "prediction_error_map": _compute_prediction_error_map(
            entity, state_snapshot
        ),
        "identity_signal": identity_signal,
        "unresolved_source": unresolved_src,
    }
    entity.add_snapshot(snap)

    # ---- Step 13: 记忆样本记录 ----
    memory_sample = {
        "emotion": semantic_packet_biased.get("emotion", 0.0),
        "intent": semantic_packet_biased.get("intent", ""),
        "timestamp": time.time(),
        "metadata": {"action": decision.get("action_type", ""), "outcome": "neutral"},
    }
    entity.add_memory_sample(memory_sample)

    # ---- Step 14: 清空联网搜索池 ----
    clear_pending_searches()

    # ---- Step 15: 写入原始事件日志（异步，不阻塞）----
    idle_seconds = time.time() - entity.last_update_time

    # V2.0：生成对话摘要（供后续管线的主线检索对话历史层使用）
    try:
        from src.memory_retrieval.summary import generate_turn_summary
        turn_summary = generate_turn_summary(
            raw_input=raw_input,
            output_text=response.get("text", ""),
            intent=semantic_packet_biased.get("intent", ""),
        )
    except Exception:
        turn_summary = ""

    # V3：intent_repr 仅作向后兼容保留（主流程已省略意图编码）
    intent_repr = {
        "tone": "neutral",
        "goal": "share",
        "constraints": {"length": "tiny", "must_not": [], "reflect_state": False},
    }

    episode = build_episode(
        iteration_id=entity.tick,
        raw_input=raw_input,
        semantic_packet_biased=semantic_packet_biased,
        decision=decision,
        intent_repr=intent_repr,
        state_snapshot=entity.to_state_snapshot(),
        drive_vector=drive_vector_final,
        output_text=response.get("text"),
        idle_seconds=idle_seconds,
        was_override=decision.get("was_override", False),
        tags=[t.get("tag", "") for t in concept_tags if isinstance(t, dict)],
        dispatched_actions=dispatched_actions,
        summary=turn_summary,  # v2.0：对话摘要
    )

    # =========================================================================
    # [接入点 5] Step 11 后（记忆固化前）：高冲击惊讶写入 Insights
    # =========================================================================
    # 当 prediction_error 波动幅度超过高冲击阈值时，触发认知重组
    try:
        _insight_writer = InsightWriter()
        # 计算驱动力场变化幅度（近似：somatic_tone_delta 的绝对值）
        somatic_tone_end = float(getattr(entity, "somatic_tone", 0.0))
        drive_change_magnitude = abs(somatic_tone_end - somatic_tone_start)
        insight_id = _insight_writer.check_and_write(
            entity_state=entity,
            episode=episode,
            prediction_error=float(getattr(entity, "_last_prediction_error", 0.0)),
            drive_change_magnitude=drive_change_magnitude,
            param_snapshot=_snapshot_dict,
            semantic_packet=semantic_packet_biased,
        )
        _trace("insight_write", True, {"insight_id": insight_id})
    except Exception as e:
        _trace("insight_write", False, {}, str(e))

    write_episode_async(episode)
    _trace("episodes_write", True, {"iteration_id": entity.tick, "importance": episode.importance})

    # =========================================================================
    # [接入点 6] Step 15 后：情绪粒子场 & 投影累计器持久化
    # =========================================================================
    try:
        # 更新时间戳
        entity.last_emotion_tick = time.time()
        # 粒子场序列化
        entity.emotion_particle_field = _particle_field.to_dict()
        # 投影控制器序列化（含运行时累计器状态）
        entity.emotion_accumulators = {
            "_projection_controller": _projection_ctrl.to_dict(),
        }
    except Exception as e:
        _trace("emotion_persist", False, {}, str(e))

    # ---- Step 15: 记录 connection_episode（v3.0 + v3.5b）----
    # 写入 memory_context，供未来的经验偏移检索使用
    try:
        if loneliness_target is not None and connection_signature:
            prev_loneliness = float(state_for_update.get("loneliness", 0.3))
            curr_loneliness = float(getattr(entity, "loneliness", 0.3))
            loneliness_change = curr_loneliness - prev_loneliness
            connection_episode = {
                "prediction_error": float(entity._last_prediction_error),
                "somatic_delta": float(getattr(entity, "somatic_tone", 0.0)) - somatic_tone_start,
                "tension": float(emergent_tension),
                "loneliness_change": loneliness_change,
                "connection_depth": float(connection_depth_eff),
                "signature": connection_signature,
                "timestamp": time.time(),
            }
            entity.add_memory_sample(connection_episode)
    except Exception:
        pass

    # ---- Step 15b: 写入超限 UNRESOLVABLE surprise 产生的 episode ----
    for unres_ep in unresolvable_episodes:
        try:
            unres_episode = build_episode(
                iteration_id=entity.tick,
                raw_input=None,
                semantic_packet_biased={
                    "emotion": 0.0,
                    "intent": "unresolvable_surprise",
                    "intensity": 0.0,
                    "anchors": [],
                    "intent_confidence": 0.0,
                },
                decision={"action_type": "rest", "target": "self"},
                intent_repr={"tone": "neutral", "goal": "reflect", "constraints": {}},
                state_snapshot=entity.to_state_snapshot(),
                drive_vector=drive_vector_final,
                output_text=unres_ep.get("reflection", ""),
                idle_seconds=idle_seconds,
                was_override=False,
                tags=["unresolvable_surprise", "from_stress_lifecycle"],
                dispatched_actions=[],
                summary="",  # 内部 tick，无用户交互，摘要留空
            )
            write_episode_async(unres_episode)
        except Exception:
            pass

    # ---- 更新最后交互时间戳（仅当有真实用户输入时）----
    # ❗ 原则：只有"外部真实他者"才能重置沉默计时器
    # - XIA 自己的 voice / reach / thinking / search → 不重置
    # - 后台 daemon tick → 不重置
    # - 真实用户输入 → 重置（唯一合法重置条件）
    if raw_input and str(raw_input).strip():
        entity.last_interaction_timestamp = time.time()
        entity.last_interaction_context = {
            "emotion": float(semantic_packet_biased.get("emotion", 0.0)),
            "intensity": float(semantic_packet_biased.get("intensity", 0.0)),
            "action_type": str(decision.get("action_type", "comfort")),
        }

    # =========================================================================
    # [语言系统 L5] Step 11 后：遗忘权标记
    # =========================================================================
    try:
        forgotten = _five_rights.process_forget_queue()
        if forgotten:
            _trace("forget_queue", True, {"forgotten_count": len(forgotten)})
    except Exception as e:
        _trace("forget_queue", False, {}, str(e))

    # =========================================================================
    # [语言系统 L3b] Step 11 后：消力闭环重录（精确 after_unresolved）
    # =========================================================================
    try:
        if _lang_before_state is not None and _lang_expression:
            after_unresolved = float(getattr(entity, "unresolved", 0.0))
            # DEBUG: 确认消力闭环拿到了正确的 after 值
            if debug:
                print(f"  [L3b DEBUG] before={before_unresolved:.3f} after={after_unresolved:.3f} delta={before_unresolved-after_unresolved:.3f}")
                print(f"  [L3b DEBUG] _quenching id={id(_quenching)} history={len(_quenching._history)} type={type(_quenching).__name__}")
            real_efficiency = _semantic_analyzer.verify_quenching(
                _lang_expression,
                before_unresolved,
                after_unresolved,
                snapshot,
            )
            if debug:
                print(f"  [L3b pre-record] hist={len(_quenching._history)}")
            _quenching.record(
                drive_state=dict(_lang_before_state),
                expression=_lang_expression,
                delta_unresolved_before=before_unresolved,
                delta_unresolved_after=after_unresolved,
                tick=entity.tick,
            )
            # v11.2: 同时记录个体词（拆分组合词），供词热身系统追踪
            # 每个组成词单独记一条，效率 ≈ 组合效率 × 0.8（保守归因）
            _comps = getattr(entity, "_training_components", [])
            for _comp in _comps:
                if _comp and _comp != _lang_expression and len(_comp) <= 8:
                    _comp_after = before_unresolved - (before_unresolved - after_unresolved) * 0.8
                    _quenching.record(
                        drive_state=dict(_lang_before_state),
                        expression=_comp,
                        delta_unresolved_before=before_unresolved,
                        delta_unresolved_after=_comp_after,
                        tick=entity.tick,
                    )
            if debug:
                print(f"  [L3b post-record] hist={len(_quenching._history)}")
            context_label = f"tick_{entity.tick}"
            _strategy_map.record_path(
                state_A=dict(_lang_before_state),
                state_B=entity.to_state_snapshot(),
                expression=_lang_expression,
                efficiency=real_efficiency,
                context_label=context_label,
                param_snapshot=_snapshot_dict,
            )
            try:
                wm_rules = getattr(entity, "wm_rules", None)
                if wm_rules is not None:
                    upgraded = _strategy_map.check_generalization(wm_rules, _snapshot_dict)
                    if upgraded:
                        _trace("strategy_upgrade_post", True, {"upgraded": len(upgraded)})
            except Exception:
                pass

            # ---- v11.3 长词->聚类权重：3+字词修正体感概念地图锚点影响力 ----
            # 长词不产生热身变体，但用于调秤：效率高的长词所属的聚类获得权重，
            # 后续体感匹配时该聚类更受重视。短词造砖，长词调秤。
            if len(_lang_expression) > 2 and real_efficiency > 0.10:
                try:
                    from .language_system.somatic_concept_map import find_closest_anchor
                    _anchor_result = find_closest_anchor(_lang_expression, min_score=0.25)
                    if _anchor_result:
                        _anchor_name, _anchor_sim = _anchor_result
                        _cw = getattr(entity, "_cluster_weights", {})
                        _old_w = _cw.get(_anchor_name, 0.0)
                        _cw[_anchor_name] = _old_w + real_efficiency * 0.05
                        _trace("cluster_weight_update", True, {
                            "word": _lang_expression[:20],
                            "anchor": _anchor_name,
                            "sim": round(_anchor_sim, 3),
                            "efficiency": round(real_efficiency, 3),
                            "weight": round(_cw[_anchor_name], 4),
                        })
                        print(f"  [ClusterWeight] '{_lang_expression[:15]}' -> {_anchor_name} +{real_efficiency*0.05:.3f} (w={_cw[_anchor_name]:.3f})", flush=True)
                except Exception:
                    pass

            _trace("language闭环_post", True, {
                "expression": _lang_expression[:30],
                "before_unresolved": round(before_unresolved, 4),
                "after_unresolved": round(after_unresolved, 4),
                "real_efficiency": round(real_efficiency, 4),
                "snr": round(_quenching.get_snr(), 4),
            })

            # v11: 消力效率滚动 EMA（boredom 激活源，α=0.05 缓慢跟随）
            try:
                entity.quenching_eff_rolling = (
                    0.95 * entity.quenching_eff_rolling + 0.05 * real_efficiency
                )
            except Exception:
                pass

            # 脐带脱落检测
            if not getattr(entity, "_umbilical_detached", False) and _quenching.is_stable(_snapshot_dict):
                entity._umbilical_detached = True
                logger.info(
                    "[run_pipeline] 脐带脱落！SNR=%.3f" % _quenching.get_snr()
                )
                _trace("umbilical_detach", True, {
                    "snr": round(_quenching.get_snr(), 4),
                    "history_count": len(_quenching._history),
                })
    except Exception as e:
        _trace("language闭环_post", False, {}, str(e))

    # =========================================================================
    # [语言系统 L6] L3b 后：语言系统状态持久化
    # =========================================================================
    try:
        entity._quenching = _quenching
        entity._quenching_data = _quenching.to_dict()
        entity._strategy_map = _strategy_map
        entity._strategy_map_data = _strategy_map.to_dict()
        entity._thermal = _thermal
        entity._thermal_data = _thermal.to_dict()
        entity._mirror = _mirror
        entity._mirror_data = _mirror.to_dict()
        entity._five_rights = _five_rights
        entity._five_rights_data = _five_rights.to_dict()
        entity._semantic_analyzer = _semantic_analyzer
        entity._candidate_gen = _candidate_gen
        entity._behavior_profiler = _behavior_profiler
        entity._decay_engine = _decay_engine
    except Exception as e:
        _trace("language_persist", False, {}, str(e))

    # ---- 持久化实体内核 ----
    # 管线结束时保存状态，下次启动时能恢复同一个 XIA
    try:
        # V6: 行动后更新行为规则（从 snapshot 归纳 effect）
        _update_behavior_rules(entity, decision)
        entity.persist_to_file(ENTITY_CORE_PATH)
    except Exception as e:
        logger.warning(f"[run_pipeline] persist_to_file failed: {e}")

    total_ms = round((time.time() - t0) * 1000, 2)

    return {
        "response": response,
        "decision": decision,
        "intent_repr": intent_repr,
        "semantic": semantic_packet_biased,
        "concept_tags": concept_tags,
        "wm_context": wm_context,
        "drive_vector": drive_vector_final,
        "thought_packet": thought_packet,
        "state_snapshot": entity.to_state_snapshot(),
        "trace": trace if debug else [],
        "total_ms": total_ms,
        "tick": entity.tick,
        "iteration_id": entity.tick,
        "dispatched_actions": dispatched_actions,
    }


# ============================================================================
# 异步管线
# ============================================================================

async def process_async_updates(
    experience_log: ExperienceLog,
    state_snapshot: StateSnapshot,
    entity_id: str = "default",
    entity=None,
    param_snapshot=None,
) -> Optional[Dict[str, Any]]:
    """
    异步经验处理入口。

    在决策管线完成后调用（在决策结果写入快照之后）。
    将经验+状态自然写入 TetraMem，可选读取拓扑并降维为信号。
    状态驱动触发世界模型归纳周期。

    参数：
        entity_id       : 实体唯一标识
        experience_log  : 本轮经验日志
        state_snapshot  : 本轮状态快照
        entity         : EntityState 实例（可选，用于预加载外部记忆到 memory_context）
        param_snapshot  : ParameterSnapshot 实例（可选，用于读取 world_model 触发阈值）
    """
    try:
        # ---- 预加载外部记忆（不阻塞，异步进行）----
        if entity is not None:
            try:
                from .memory_bias.memory_bias import load_memories_to_entity
                intent = "seek"  # 默认意图，预留
                emotion = 0.0
                if experience_log and hasattr(experience_log, "tags"):
                    tags = getattr(experience_log, "tags", [])
                    for tag in tags:
                        if tag.startswith("intent:"):
                            intent = tag[len("intent:"):]
                            break
                await load_memories_to_entity(
                    entity=entity,
                    intent=intent,
                    emotion=emotion,
                    limit=3,
                )
            except Exception as e:
                logger.debug(f"[EntityZero] Preload memories skipped: {e}")

        await log_experience_with_context(
            entity_id=entity_id,
            experience_log=experience_log,
            state_snapshot=state_snapshot,
        )

        topo = await get_topology_metrics()
        pressure_signal = calculate_memory_pressure_from_topology(topo)
        if pressure_signal is not None:
            return pressure_signal.to_dict()

        # ---- 状态驱动：检查快照累积量，触发世界模型更新 ----
        if entity is not None and param_snapshot is not None:
            try:
                from .world_model_update.defaults import get_raw_value
                snapshot_count = len(entity.snapshots)
                induction_threshold = int(get_raw_value(
                    param_snapshot,
                    "world_model.induction_min_rounds",
                    5.0,
                ))
                if snapshot_count >= induction_threshold:
                    # 经验质量检查：快照间多样性 CV 低于阈值时强制跳过
                    diversity_ok = True
                    try:
                        cv_thresh = get_raw_value(
                            param_snapshot,
                            "world_model.diversity_cv_threshold",
                            0.08,
                        )
                        diversity_ok = _compute_snapshot_diversity(getattr(entity, "snapshots", [])) >= cv_thresh
                    except Exception:
                        pass  # 检查失败时放行，宁可多学也不漏学
                    if not diversity_ok:
                        logger.debug(
                            f"[EntityZero] WM update skipped: low snapshot diversity "
                            f"(CV < {cv_thresh:.3f})"
                        )
                    else:
                        retention = int(get_raw_value(
                            param_snapshot,
                            "world_model.retention_after_update",
                            5.0,
                        ))
                        _wmu_cycle = await run_world_model_update_cycle_async(
                            old_rules=entity.wm_rules,
                            snaps=entity.snapshots,
                            dialogue_log=[],
                            state_snapshot=state_snapshot,
                            param_snapshot=param_snapshot,
                            embedding_provider=None,
                        )
                        _trace("wmu_update", True, {
                            "snapshots_processed": snapshot_count,
                            "new_rules": len(_wmu_cycle[0]) if _wmu_cycle else 0,
                        })
                        # 更新完成后清空已处理的快照，保留最近 N 轮作为上下文
                        old_rule_ids = {r.get("id") if isinstance(r, dict) else getattr(r, "id", None)
                                        for r in entity.wm_rules}
                        entity.wm_rules = _wmu_cycle[0] if _wmu_cycle else entity.wm_rules
                        entity.snapshots = entity.snapshots[-retention:] if entity.snapshots else []

                        # Insights 衰减同步：新规则替换旧列表后同步一次
                        try:
                            from .memory_hub.insights import sync_decay as _sync_decay
                            _sync_decay(entity.wm_rules)
                        except Exception:
                            pass

                        # Insights 升级：找出本轮新升 active 的规则，触发写入
                        if _wmu_cycle:
                            new_rules = _wmu_cycle[0]
                            upgrade_threshold = get_raw_value(
                                param_snapshot,
                                "world_model.upgrade_to_insight_threshold",
                                0.7,
                            )
                            newly_active = [
                                r for r in new_rules
                                if (r.get("status") if isinstance(r, dict) else getattr(r, "status", ""))
                                   == "active"
                                and (r.get("id") if isinstance(r, dict) else getattr(r, "id", None))
                                   not in old_rule_ids
                                and (r.get("confidence", 0.0) if isinstance(r, dict)
                                     else getattr(r, "confidence", 0.0)) >= upgrade_threshold
                            ]
                            if newly_active:
                                try:
                                    from .memory_hub.insights import write_insight_batch as _write_insight_batch
                                    upgraded = _write_insight_batch(newly_active)
                                    if upgraded > 0:
                                        logger.info(f"[EntityZero] Insights upgraded: {upgraded} rules")
                                except Exception:
                                    pass

                        logger.info(
                            f"[EntityZero] WM update done: {snapshot_count} snaps → "
                            f"{len(entity.wm_rules)} rules, kept {retention} as context"
                        )
            except Exception as e:
                logger.debug(f"[EntityZero] WM update skipped: {e}")

        return None

    except Exception as e:
        logger.error(f"[EntityZero] TetraMem async failed, skipped: {e}")
        return None


async def trigger_sleep_if_needed(
    entity_id: str,
    fatigue: float,
    current_residue: float,
) -> float:
    """
    状态驱动的睡眠触发器。

    此函数本身不决定是否睡眠——决策由 V4 裁决层做出。
    此函数仅执行"睡眠"动作的物理后果（做梦、残留层衰减）。
    """
    try:
        return await execute_sleep_cycle(
            entity_id=entity_id,
            current_residue=current_residue,
        )
    except Exception as e:
        logger.error(f"[EntityZero] Sleep cycle failed, residue unchanged: {e}")
        return current_residue


async def run_world_model_update_cycle_async(
    old_rules: List[Any],
    snaps: List[Any],
    dialogue_log: Any,
    state_snapshot: Any,
    param_snapshot: ParameterSnapshot,
    embedding_provider: Optional[Any] = None,
) -> tuple[List[Any], _WMUCycleStats]:
    """
    世界模型更新异步反思周期主入口（world_model_update 管线）。
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        _wmu_run_update_cycle,
        old_rules,
        snaps,
        dialogue_log,
        state_snapshot,
        param_snapshot,
        embedding_provider,
    )


# ============================================================================
# 状态驱动触发检查（供裁决层调用）
# ============================================================================

def should_trigger_sleep(fatigue: float, stress: float) -> bool:
    """
    睡眠触发条件检查。

    状态驱动：fatigue 或 stress 超过阈值时，触发睡眠信号。
    此函数本身不触发睡眠，仅返回布尔值供裁决层参考。
    """
    return fatigue > 0.9 or stress > 0.85


# ============================================================================
# V6: 行为规则学习
# ============================================================================

def _update_behavior_rules(entity, decision: dict) -> None:
    """
    管线结束时，从本轮 snapshot 更新行为规则。

    只记录有实际效果的动作（至少一个维度变化 > 0.01）。
    失败静默跳过。
    """
    try:
        from src.core.behavior_vector import update_rules_from_snapshot
        snaps = getattr(entity, "snapshots", [])
        if len(snaps) < 2:
            return
        action_type = decision.get("action_type", "")
        if not action_type:
            return
        pre = snaps[-2]
        post = snaps[-1]

        # 内生筛选：只记她当前在乎的变化
        # relevance = Σ |delta[dim]| × drive_pressure[dim]
        # loneliness 高时 loneliness 的小变化也值得记
        # loneliness 低时再大的变化也是噪音
        drive_weights = {
            "energy":       max(0.0, 1.0 - entity.energy),
            "loneliness":   entity.loneliness,
            "fatigue":      entity.fatigue,
            "info_gap":     entity.info_gap,
            "unresolved":   entity.unresolved,
            "somatic_tone": abs(entity.somatic_tone),
            "danger_level": getattr(entity, "danger_level", 0.0),
            "approach_drive": getattr(entity, "approach_drive", 0.0),
            "avoid_drive":  getattr(entity, "avoid_drive", 0.0),
        }
        relevance = 0.0
        for k in pre:
            if k in post and k in drive_weights:
                delta = abs(float(post.get(k, 0)) - float(pre.get(k, 0)))
                relevance += delta * drive_weights[k]
        if relevance < 0.005:  # 加权总变化太小 → 不值得记
            return

        snap = {
            "action_type": action_type,
            "pre_state": dict(pre),
            "post_state": dict(post),
        }
        update_rules_from_snapshot(entity, snap, entity.tick)
    except Exception:
        pass


# ============================================================================
# 经验质量：快照多样性计算
# ============================================================================

def _compute_snapshot_diversity(snaps: list) -> float:
    """
    计算快照集合的多样性（状态变化向量夹角余弦）。

    快照多样性低（CV 低）→ 各轮状态变化模式相似 → 学习价值低 → 跳过归纳。
    多样性高 → 状态变化模式丰富 → 学习价值高 → 执行归纳。

    返回：
        float — 快照间平均余弦距离（0=完全相同, 1=完全不相关）。
        snapshots 不足 2 个时返回 1.0（允许学习）。
    """
    if not snaps or len(snaps) < 2:
        return 1.0

    def _to_vec(snap) -> dict:
        if hasattr(snap, "pre_state") and hasattr(snap, "post_state"):
            pre = getattr(snap, "pre_state", {})
            post = getattr(snap, "post_state", {})
        elif isinstance(snap, dict):
            pre = snap.get("pre_state", {})
            post = snap.get("post_state", {})
        else:
            return {}
        all_keys = set(pre.keys()) | set(post.keys())
        return {k: post.get(k, 0.0) - pre.get(k, 0.0) for k in all_keys}

    vecs = [_to_vec(s) for s in snaps]
    valid = [v for v in vecs if v]
    if len(valid) < 2:
        return 1.0

    total_dist = 0.0
    count = 0
    for i in range(len(valid)):
        for j in range(i + 1, len(valid)):
            v1, v2 = valid[i], valid[j]
            all_keys = set(v1.keys()) | set(v2.keys())
            if not all_keys:
                continue
            dot = sum(v1.get(k, 0.0) * v2.get(k, 0.0) for k in all_keys)
            mag1 = math.sqrt(sum(v1.get(k, 0.0) ** 2 for k in all_keys))
            mag2 = math.sqrt(sum(v2.get(k, 0.0) ** 2 for k in all_keys))
            if mag1 > 1e-9 and mag2 > 1e-9:
                cos = dot / (mag1 * mag2)
                # 余弦距离 = 1 - cos，余弦越接近1（相似）距离越小
                total_dist += (1.0 - cos)
                count += 1

    if count == 0:
        return 1.0
    return total_dist / count


# 辅助函数
# ============================================================================

def get_default_drive_params() -> Dict[str, Any]:
    """返回驱动力系统的默认形态表参数"""
    return {
        "info_hunger_time_shape": {
            "x_anchors": [0.0, 0.3, 0.8, 1.0, 2.0, 5.0],
            "y_anchors": [0.0, 0.02, 0.15, 0.60, 0.85, 0.99]
        },
        "social_time_shape": {
            "x_anchors": [0.0, 0.5, 1.0, 2.0, 4.0],
            "y_anchors": [0.0, 0.05, 0.30, 0.70, 0.98]
        },
        "loneliness_shape": {
            "x_anchors": [0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
            "y_anchors": [0.0, 0.01, 0.05, 0.15, 0.45, 1.0]
        },
        "fatigue_shape": {
            "x_anchors": [0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
            "y_anchors": [0.0, 0.02, 0.08, 0.20, 0.50, 1.0]
        },
        "change_shape": {
            "x_anchors": [0.0, 0.25, 0.5, 0.75, 1.0],
            "y_anchors": [0.0, 0.05, 0.20, 0.55, 1.0]
        },
        "debt_shape": {
            "x_anchors": [0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
            "y_anchors": [0.0, 0.01, 0.05, 0.15, 0.40, 1.0]
        },
    }


def _build_decision_params(snapshot: ParameterSnapshot) -> Dict[str, Any]:
    """从参数快照构建裁决系统参数"""
    return {
        "module_weights": {
            "SituationAssessment": get_param(snapshot, "decision.module_weights.SituationAssessment", 1.0),
            "ContextAwareness": get_param(snapshot, "decision.module_weights.ContextAwareness", 1.0),
            "ThoughtIntegration": get_param(snapshot, "decision.module_weights.ThoughtIntegration", 1.0),
            "SignalActivation": get_param(snapshot, "decision.module_weights.SignalActivation", 1.0),
            "MainlineConstraint": get_param(snapshot, "decision.module_weights.MainlineConstraint", 1.0),
            "TemporalPressure": get_param(snapshot, "decision.module_weights.TemporalPressure", 1.0),
            "SelfState": get_param(snapshot, "decision.module_weights.SelfState", 1.0),
            "Preference": get_param(snapshot, "decision.module_weights.Preference", 1.0),
            "WorldModel": get_param(snapshot, "decision.module_weights.WorldModel", 1.0),
        },
        "survival_override_threshold": get_param(snapshot, "decision.survival_override_threshold", 0.85),
        "max_suggestions": get_param(snapshot, "decision.max_suggestions", 2),
        "fallback_priority": get_param(snapshot, "decision.fallback_priority", 0.0),
        "personality": get_param(snapshot, "personality", {
            "introverted_bias": 0.2,
            "extroverted_bias": 0.1,
        }),
        "web_search": {
            "enabled": get_param(snapshot, "web_search.enabled", True),
            "info_hunger_threshold": get_param(snapshot, "web_search.info_hunger_threshold", 0.6),
            "wm_hit_threshold": get_param(snapshot, "web_search.wm_hit_threshold", 0.3),
            "intent_intensity_threshold": get_param(snapshot, "web_search.intent_intensity_threshold", 0.6),
            "max_results": get_param(snapshot, "web_search.max_results", 5),
            "timeout_seconds": get_param(snapshot, "web_search.timeout_seconds", 8.0),
            "backend": get_param(snapshot, "web_search.backend", None),
        },
    }


def _build_output_params(snapshot: ParameterSnapshot) -> Dict[str, Any]:
    """从参数快照构建输出层参数"""
    return {
        "model_name": get_param(snapshot, "llm.model_name", "qwen2.5:3b"),
        "temperature": get_param(snapshot, "llm.temperature", 0.7),
        "max_tokens": int(get_param(snapshot, "llm.max_tokens", 300)),
        "output_llm_timeout_ms": get_param(snapshot, "llm.output_llm_timeout_ms", 90000),
    }


# ============================================================================
# Mock LLM（用于测试，无外部依赖）
# ============================================================================

def mock_llm_callable(
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    max_tokens: int,
    timeout_ms: float,
) -> tuple[Optional[str], Optional[str]]:
    """Mock LLM 调用，用于测试"""
    return "嗯，我听到了。", None


# ============================================================================
# 测试入口
# ============================================================================

if __name__ == "__main__":
    import time as _time

    print("=" * 64)
    print("Entity Zero Iteration — 同步管线集成测试")
    print("=" * 64)

    # 重置状态
    reset_entity_state()
    entity = get_entity_state()

    # Mock LLM callable（用于测试，不依赖真实 LLM）
    def test_llm(
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
        timeout_ms: float,
    ) -> tuple[Optional[str], Optional[str]]:
        # 根据 intent_repr 的 goal 和 state_snapshot 动态生成回复
        return "嗯，我听到了。", None

    test_inputs = [
        ("你好呀！", "正常外部输入-打招呼"),
        ("我今天很开心！", "分享正面情绪"),
        ("怎么解决这个问题？", "求助意图"),
        ("我好烦啊，什么破事", "抱怨负面情绪"),
        ("凭什么要听你的！", "挑战对抗"),
        (None, "内部 tick（无外部输入）"),
    ]

    for raw_input, name in test_inputs:
        print(f"\n{'─'*64}")
        print(f"【{name}】")
        if raw_input:
            print(f"  输入: {raw_input}")
        else:
            print(f"  输入: <内部 tick>")

        result = run_pipeline(
            raw_input=raw_input,
            entity_state=entity,
            debug=True,
            llm_callable=test_llm,
        )

        print(f"\n  决策: {result['decision']['action_type']} | target={result['decision']['target']} | priority={result['decision']['priority']:.3f}")
        print(f"  回应: {result['response']['text']}")
        print(f"  状态: energy={result['state_snapshot']['energy']:.3f} fatigue={result['state_snapshot']['fatigue']:.3f} loneliness={result['state_snapshot']['loneliness']:.3f}")
        print(f"  驱动力: curiosity={result['drive_vector']['curiosity']:.3f} info_hunger={result['drive_vector']['info_hunger']:.3f}")
        print(f"  世界模型命中: {len(result['wm_context']['matched_rules'])} 条, hit_rate={result['wm_context']['coverage']['hit_rate']:.2f}")
        print(f"  总耗时: {result['total_ms']:.1f}ms")
        print(f"  Tick: {result['tick']}")

    print(f"\n{'='*64}")
    print(f"全部测试完成。最终 Tick: {entity.tick}")
    print(f"经验快照数: {len(entity.snapshots)}")
    print(f"记忆上下文数: {len(entity.memory_context)}")
    print(f"世界模型规律数: {len(entity.wm_rules)}")
    print("=" * 64)


# ============================================================================
# v11.4 纯语言训练模式（关管线，只跑语言学习）
# ============================================================================

def run_language_training_tick(entity: EntityState, snapshot: dict, override_state: dict = None) -> dict:
    """
    纯语言训练 tick。

    如果 override_state 不为 None，直接使用该状态（不随机游走）；
    否则从真实状态初始化虚拟状态并做高斯游走。
    """
    import random as _rnd
    t0 = time.time()

    # ---- 虚拟状态：override 优先，否则随机游走 ----
    _vr = getattr(entity, "_vr_state", None)
    if override_state is not None:
        _vr = dict(override_state)
        entity._vr_state = _vr
    elif _vr is None:
        _vr = dict(snapshot)
        entity._vr_state = _vr
    else:
        _sigma = 0.15
        _vr_dims = {
            "somatic_tone": (-1.0, 1.0),
            "loneliness": (0.0, 1.0),
            "energy": (0.0, 1.0),
            "boredom": (0.0, 1.0),
            "unresolved": (0.0, 1.0),
            "stress": (0.0, 1.0),
            "fatigue": (0.0, 1.0),
            "danger_level": (0.0, 1.0),
            "info_gap": (0.0, 1.0),
            "approach_drive": (0.0, 1.0),
            "avoid_drive": (0.0, 1.0),
        }
        # 每 10 tick 随机跳跃到全新位置
        _jump = (entity.tick % 10 == 0)
        for dim, (lo, hi) in _vr_dims.items():
            if _jump:
                _vr[dim] = lo + _rnd.random() * (hi - lo)
            else:
                _vr[dim] = max(lo, min(hi, _vr.get(dim, 0.5) + _rnd.gauss(0, _sigma)))

    # ---- 物理约束：虚拟状态也必须合理 ----
    # 能量 + 疲劳 ≤ 1.3
    if _vr.get("energy", 0) + _vr.get("fatigue", 0) > 1.3:
        _excess = (_vr["energy"] + _vr["fatigue"] - 1.3) / 2
        _vr["energy"] = max(0.0, _vr["energy"] - _excess)
        _vr["fatigue"] = max(0.0, _vr["fatigue"] - _excess)
    # 躯体基调 > 0.3 时，疼痛不能太高
    if _vr.get("somatic_tone", 0) > 0.3:
        _vr["pain"] = min(_vr.get("pain", 0), 0.4)
    # 恐惧 × 社交趋近 ≤ 0.5
    if _vr.get("danger_level", 0) * _vr.get("approach_drive", 0) > 0.5:
        _vr["approach_drive"] = 0.5 / max(0.01, _vr["danger_level"])

    # ---- 锚点直接匹配：BGE 下线，教科书做主 ----
    scored_candidates = []
    try:
        from .language_system.somatic_concept_map import SOMATIC_ANCHORS
        for _word, _anchor in SOMATIC_ANCHORS.items():
            _ok = _total = 0
            for _dim, _delta in _anchor.items():
                if _dim not in _vr:
                    continue
                _total += 1
                _cur = _vr[_dim]
                if (_delta > 0.03 and _cur > 0.4) or (_delta < -0.03 and _cur < 0.4):
                    _ok += 1
            if _total >= 2:
                _match = _ok / _total
                _coverage = _total / len(_anchor)
                _score = _match * 0.5 + _coverage * 0.5
            elif _total == 1:
                _score = 0.3
            else:
                _score = 0.0
            if _score > 0.1:
                scored_candidates.append((_word, _score))
        scored_candidates.sort(key=lambda x: x[1], reverse=True)
    except Exception as e:
        logger.warning(f"[TrainOnly] Anchor match failed: {e}")

    # ---- 热身注入 ----
    try:
        from .language_system.word_warmup import inject_warmup_candidates
        scored_candidates = inject_warmup_candidates(
            entity, scored_candidates, min_hits=3, min_best_efficiency=0.15)
    except Exception:
        pass

    # ---- 去重排序 ----
    seen = set()
    _unique = []
    for c, s in sorted(scored_candidates, key=lambda x: x[1], reverse=True):
        if c not in seen:
            seen.add(c)
            _unique.append((c, s))
    scored_candidates = _unique

    # ---- 训练模式探索：1-2 命中词优先冲 3，0 命中只打破平局 ----
    try:
        from collections import Counter
        _quenching = getattr(entity, "_quenching", None)
        _hits = Counter()
        for r in (_quenching._history if _quenching else []):
            if hasattr(r, "expression"):
                _hits[r.expression] += 1
        _boosted = []
        for c, s in scored_candidates:
            _h = _hits.get(c, 0)
            if _h == 0:
                _boosted.append((c, s + 0.03))   # 平局打破
            elif _h < 3:
                _boosted.append((c, s + 0.08))   # 优先冲到 3 命中 → 解锁热身
            else:
                _boosted.append((c, s))           # 已解锁，不加分
        scored_candidates = _boosted
    except Exception:
        pass

    # ---- 阻力场 ----
    try:
        from .language_system.language_resistance import apply_resistance, init as _init_r
        _init_r(resistance_weight=0.10)
        _res = apply_resistance(scored_candidates)
        if _res and not all(s < 0.01 for _, s in _res):
            scored_candidates = _res
    except Exception:
        pass

    # ---- 选最佳 ----
    best_candidate = None
    best_score = 0.0
    if scored_candidates:
        _short = [(c, s) for c, s in scored_candidates if len(c) <= 8]
        if _short:
            best_candidate, best_score = max(_short, key=lambda x: x[1])
        else:
            best_candidate, best_score = scored_candidates[0]

    # ---- 功能词注入 + 消力 ----
    _display = best_candidate
    if best_candidate and best_score > 0.001:
        try:
            from .language_system.somatic_dictionary import SOMATIC_DICTIONARY
            _cats = ["actions", "degree", "time", "question", "logic"]
            _pool = list(SOMATIC_DICTIONARY.get(_rnd.choice(_cats), {}).keys())
            _fw = _rnd.choice(_pool) if _pool else ""
            if _fw:
                _display = f"{_fw}{best_candidate}" if _rnd.random() < 0.5 else f"{best_candidate}{_fw}"
        except Exception:
            pass

        try:
            from .language_system.quenching import QuenchingTracker
            _q = getattr(entity, "_quenching", None)
            if _q is None:
                # 从已有 _quenching_data 恢复，避免覆盖管线积累的记录
                _qd = getattr(entity, "_quenching_data", None)
                if _qd and _qd.get("records"):
                    _q = QuenchingTracker.from_dict(_qd)
                else:
                    _q = QuenchingTracker()
                entity._quenching = _q
            _q.record(
                drive_state=_vr,
                expression=best_candidate,
                delta_unresolved_before=0.0,
                delta_unresolved_after=0.0,
                tick=entity.tick,
            )
            entity._quenching_data = _q.to_dict()
        except Exception:
            pass

    # ---- 日志 ----
    _warm = []
    try:
        from .language_system.word_warmup import get_warm_words
        _warm = get_warm_words(entity)
    except Exception:
        pass

    elapsed = (time.time() - t0) * 1000
    logger.info(
        f"[TrainOnly] t={entity.tick} vr(s={_vr.get('somatic_tone',0):.2f} "
        f"l={_vr.get('loneliness',0):.2f}) "
        f"cand={len(scored_candidates)} best='{best_candidate}' "
        f"warm={len(_warm)} {elapsed:.0f}ms"
    )

    entity.tick += 1
    return {
        "vr_state": _vr,
        "best": best_candidate,
        "best_score": best_score,
        "cand_count": len(scored_candidates),
        "warm_count": len(_warm),
        "ms": elapsed,
    }
