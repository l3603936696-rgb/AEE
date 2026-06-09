"""实体状态模块 — EntityState、持久化、全局单例

从 entity_zero_iteration.py 拆分。所有相对导入保持不变。
"""

import logging
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

# ============================================================================
# 持久化路径
from .entity_io import (
    DATA_DIR,
    ENTITY_CORE_PATH,
)
from .entity_lifecycle import (
    _apply_offline_drift,
    _apply_silence_injection,
    _init_stereotype_trees,
    _interpolate_lookup,
    _recover_from_episodes,
)

from .entity_experience import _build_experience_log, _compute_prediction_error_map
from .entity_core_wrapper import _CoreWrapper, _make_core_wrapper
from .entity_persistence import load_entity_from_file, persist_entity_to_file


logger = logging.getLogger(__name__)


# ============================================================================
# 行为涌现适配器（兼容层）
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

    # ---- 时间连续机制断档字段（v11.x）----
    # 关机时写入，开机时读取并计算离线漂移
    last_shutdown_time: float = 0.0  # epoch 秒，0 = 无断档记录
    last_shutdown_tick: int = 0      # 关机时的 tick 数

    # ---- 醒来感知（v11.x）----
    # 开机时注入一条内部感知消息，由管线在首个心跳输出
    _pending_wakeup_message: Optional[str] = None

    # 运行时标记：哪些维度主要由沉默时间注入（不持久化，每轮重算）
    _time_injected_fields: set = field(default_factory=set)

    # 行为冷却追踪（持久化）
    last_action_timestamp: float = 0.0       # epoch 秒，最近一次主动行动时间
    consecutive_reaches_without_response: int = 0  # 连续敲门未得到回应的次数

    # pending_surprises（未处理的意外信号队列，stress 生命周期）
    pending_surprises: list = field(default_factory=list)

    # pending_failures（工具执行失败队列，V4 新增）
    pending_failures: list = field(default_factory=list)

    # _pending_tool_gaps（待处理的能力缺口队列，v11.6 新增）
    # 每次工具执行失败后由 executor 写入，供 pipeline 后续步骤使用
    _pending_tool_gaps: list = field(default_factory=list)

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
    # 生成层持久化：构式库 / 递归生成器 / 模板学习。三者每 tick 已写回同名属性
    # （s06c_anchor_core），但此前未进落盘白名单 → 重启即丢，组合能力攒不起来。
    _cxg_data: dict = field(default_factory=dict)                # ConstructionLearner.to_dict()
    _rcxg_data: dict = field(default_factory=dict)               # RecursiveGenerator.to_dict()
    _template_learner_data: dict = field(default_factory=dict)   # template_learner.to_dict()
    # 澄清记忆账本 JSON 镜像（record-only v1）：
    # 运行时对象 entity._clarification_memory 是 ClarificationMemory 实例（瞬态），
    # 由 clarification_memory._get_memory() 懒恢复；镜像随 entity_state 落盘。
    _clarification_memory_data: dict = field(default_factory=dict)
    # 澄清归属证据账本 JSON 镜像（observe-reply v2）：
    # 运行时对象 entity._clarification_evidence_store 是 SlotEvidenceStore 实例（瞬态），
    # 由 clarification_learning._get_evidence_store() 懒恢复；镜像随 entity_state 落盘。
    _clarification_hints_data: dict = field(default_factory=dict)

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
    dopamine_tone: float = 0.5     # 多巴胺基调（v11.x）
    oxytocin_tone: float = 0.5     # 催产素基调（v11.x）
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

    # ---- v11.5 内部符号涌现（StatePatternMemory）----
    _state_pattern_data: dict = field(default_factory=dict)  # StatePatternMemory.to_dict()

    # ================================================================
    # 转换系数（参数）：决定"外部输入如何转为内部变化"
    # 初始值从 param_store.json 同步，可被风化系统长期漂移
    # 对应 param_store.json 的 "conversion" 段
    # ================================================================

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
        "loneliness_surface_release": 0.15,  # 表达缓解急性孤独感
        "boredom_release": 0.10,             # 自我表达本身是一种刺激
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
    # ================================================================
    # 运行时追踪器（状态）：随 tick 实时变化的累积器
    # 不进入 param_store，不可漂移
    # ================================================================

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
        "enabled": True,
        "channel_dir": "E:/sibling_channel",
        "self_name": "xia",
        "peer_name": "knuonuo",
    })

    # ---- 他者建模：来源 profile 记录（v2.0）----
    _source_profiles: dict = field(default_factory=dict)

    # ---- 刻板印象树：分层级说话者认知结构（v1.0）----
    # {tree_name: StereotypeTree}，default="default"（XIA 自己的树）
    _stereotype_trees: dict = field(default_factory=dict)
    # 刻板印象树对话历史（{speaker_id: [samples]})
    _stereotype_conversation_history: dict = field(default_factory=dict)
    # 每个说话者最近学习的特征（{speaker_id: features}），用于 fork 比较
    _recent_speaker_features: dict = field(default_factory=dict)

    # ---- 回复动机：输出因果追踪临时字段（重启清零，不 persist）----
    _pending_output_causal: dict = field(default_factory=dict)

    # ---- 环境状态向量（patch-02-二）----
    # semantic_residue: {source_id: float}，按 tick 指数衰减（0.8/tick）
    # social_prediction_tension: float，沉默累积，对数饱和
    # physical: dict，物理状态（暂为空，供后续扩展）
    _environment_vector: dict = field(default_factory=lambda: {
        "semantic_residue": {},
        "social_prediction_tension": 0.0,
        "physical": {},
    })

    # ---- 概念图经验学习（重启清零，不 persist）----
    # _concept_exposure_log: {word: [{tick, state}]}
    # _concept_learned_bias: {word: {dim: delta}} 经验积累后补充的偏置
    _concept_exposure_log: dict = field(default_factory=dict)
    _concept_learned_bias: dict = field(default_factory=dict)

    # ---- 心事系统（preoccupations）：带对象、带时间跨度的具体念头 ----
    # 每条心事: {
    #   "id": str,                  唯一 id
    #   "about": str,               心事的对象（你、妹妹、那件事…）
    #   "type": str,                担心 / 想念 / 期待 / 不安 / 怀念 / 好奇
    #   "intensity": float,         强度 0-1
    #   "created_tick": int,        创建时的 tick
    #   "last_refresh_tick": int,   最近一次被刷新的 tick
    # }
    # 每 tick 自然衰减 + 投射到标量状态；持久化随实体保存。
    _preoccupations: list = field(default_factory=list)

    # ---- 反刍层（reflection）：用 LLM 当镜子做深度复盘 ----
    # _last_reflection_tick: 上次反刍的 tick；初始 -10 让首次启动后 N tick 即可触发
    # _self_narrative: 她对自己当前的一句话叙事，由反刍更新
    # _reflection_log: 反刍历史 [{tick, insights, narrative_update}]，FIFO 上限 20
    # _narrative_bias: 当前自我叙事对应的状态色调，每 tick 加到 _real_state，直到下次反刍刷新
    _last_reflection_tick: int = -10
    _self_narrative: str = ""
    _reflection_log: list = field(default_factory=list)
    _narrative_bias: dict = field(default_factory=dict)

    # ---- JEPA 世界模型（I-JEPA + V-JEPA）运行时字段 ----
    # _last_vjepa_tick: 上次 V-JEPA 短时总结的 tick
    # _jepa_surprise_density: 近期平均意外程度 [0, 1]，由 V-JEPA 写入
    # _jepa_transition_indices: 近期高意外时刻下标列表（由 V-JEPA 写入，I-JEPA 可读）
    _last_vjepa_tick: int = -(200 + 1)   # 初始为负，保证首次 200 tick 后即触发
    _jepa_surprise_density: float = 0.0
    _jepa_transition_indices: list = field(default_factory=list)

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

    # ---- 因果观测缓冲：(输入来源, 状态delta) 配对 ----
    # 每 tick 记录一条，用于学习"什么输入导致什么状态变化"
    _causal_observations: list = field(default_factory=list)  # max 200 entries
    _causal_associations: dict = field(default_factory=dict)  # 学到的因果关联
    # ②a：输入主题在线聚类存储 {centroids, ids, counts}（input_theme.py 维护）
    _input_theme_data: dict = field(default_factory=dict)

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
            # 注意：tick 是元数据不是状态，不放进 snapshot——
            # 否则会被 CxG learner 学进 drive_profile，再通过 cx_delta 的
            # setattr 循环污染 entity.tick（曾导致 tick 卡在 2.0 永不递增）。
            # 需要 tick 的消费方请直接读 entity.tick。
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
            # v11.x 多巴胺基调
            "dopamine_tone": getattr(self, "dopamine_tone", 0.5),
            "oxytocin_tone": getattr(self, "oxytocin_tone", 0.5),
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
        persist_entity_to_file(self, path)

    def load_from_file(self, path: Optional[Path] = None) -> bool:
        return load_entity_from_file(self, path)


# ============================================================================
# 全局信号池 & 实体内核状态（单例）
_entity_state_instance: Optional[EntityState] = None


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
        # 3. 计算离线漂移（时间连续机制：关机后重启的状态双向漂移）
        _apply_offline_drift(entity)
        # 4. 计算沉默时长并注入时间偏移
        _apply_silence_injection(entity)
        # 5. 初始化刻板印象树（v1.0）
        _init_stereotype_trees(entity)
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
