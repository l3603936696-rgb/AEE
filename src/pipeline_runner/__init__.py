"""管线主函数 — run_pipeline + 所有管线步骤

从 entity_zero_iteration.py 拆分。v11.5 恢复版。
模块化拆分：utils / helpers / async_pipeline 已独立为子模块。
"""

from __future__ import annotations

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

# 常量从 helpers 模块导入
from .helpers import DATA_DIR, ENTITY_CORE_PATH

from ..memory_hub import (
    ExperienceLog,
    StateSnapshot,
    log_experience_with_context,
    execute_sleep_cycle,
    get_topology_metrics,
    calculate_memory_pressure_from_topology,
    build_episode,
    write_episode_async,
)
from ..memory_hub.insula_hub import compute_somatic_signals as _compute_somatic_signals
from ..core import emerge_behavior as _emerge_behavior, build_system_prompt as _build_system_prompt, derive_rendering_params as _derive_rendering_params
from ..core.action_dispatcher import dispatch_async_action as _dispatch_async_action, select_primitive_candidate as _select_primitive_candidate
from ..entity_state import EntityState, PipelineTrace, get_entity_state, force_set_state, ENTITY_CORE_PATH, DATA_DIR, _compute_prediction_error_map, _apply_silence_injection, _recover_from_episodes, _interpolate_lookup, _make_core_wrapper
from ..core.entity_core import EntityCore


# helpers 模块导入（覆盖 entity_state 导入的同名函数）
from .helpers import _compute_prediction_error_map, _build_experience_log, SnapshotDictWrapper


from ..world_model_update import (
    run_update_cycle as _wmu_run_update_cycle,
    induct_only as _wmu_induct_only,
    decay_only as _wmu_decay_only,
    verify_only as _wmu_verify_only,
    merge_only as _wmu_merge_only,
    CycleStats as _WMUCycleStats,
)
from ..parameter_system.access import create_snapshot, get_param, apply_staged, stage_changes
from ..parameter_system.snapshot import ParameterSnapshot

from ..semantic.semantic_understanding import analyze_semantic
from ..memory_bias.memory_bias import apply_memory_bias
from ..concept_tags.concept_tags import generate_concept_tags
from ..world_model_reader.world_model_reader import query_world_model
from ..drive_system.drive_system import compute_drive_vector, apply_affect_multiplier
from ..thinking_system.thinking_system import think as thinking_think
from ..decision_system.decision_system import perceive_all as _perceive_all, DEFAULT_PARAMS as DECISION_DEFAULT_PARAMS
from ..decision_system.submodules.web_search import (
    drain_pending_searches,
    clear_pending_searches,
)
from ..intent_encoder.intent_encoder import encode_intent
from ..output_layer.output_layer import generate_response
from ..state_update.update_engine import update_state
from ..state_update.compute_connection import (
    compute_connection_depth,
    compute_connection_depth_ex,
    compute_loneliness_target,
    compute_loneliness_target_ex,
)
from ..state_update.compute_coherence import append_delta as append_coherence_delta
from ..state_update import reset_info_queue
from ..observation.behavior_trace import (
    build_connection_trace,
    build_loneliness_trace,
    compute_trend,
    compute_profile,
    _infer_loneliness_reason,
)
from ..observation.counterfactual_probe import run_counterfactual_probe
from ..observation.probe_logger import get_probe_logger
from ..emotion_system import (
    ParticleField,
    ProjectionController,
    DecayEngine,
    InsightWriter,
    compute_emotions,
)
from ..language_system import (
    QuenchingTracker,
    StrategyMap,
    ThermalController,
    MirrorLearner,
    FiveRightsController,
    SemanticAnalyzer,
    CandidateGenerator,
    LinguisticAbundanceMonitor,
)
from ..behavior_profiler import BehaviorProfiler


logger = logging.getLogger(__name__)


# ============================================================================
# 语言训练降级：启发式默认候选
# ============================================================================

def _make_fallback_candidates(state: Dict[str, float]) -> List[str]:
    """根据驱动力场从体感词典中抽取最相关候选词。

    v3.2: 替换硬编码 12 词 → 240+ 词的体感词典。
    用粗略方向匹配做第一轮粗筛，BGE 再做精确打分。
    v11.1: 不混入功能词——功能词走输出层辅线附赠，不参与 BGE 竞争。
    """
    candidates = []

    try:
        from ..language_system.somatic_dictionary import get_words_matching_state
        matches = get_words_matching_state(state, top_k=8, min_similarity=0.15)
        if matches:
            candidates = [w for w, _, _ in matches]
        return candidates[:16]  # 上限 16 个候选
    except Exception:
        pass

    # 词典加载失败时的硬兜底：按 avoid 连续分桶
    import bisect as _bisect
    avoid = float(state.get("avoid_drive", state.get("avoid", 0.3)))
    _AVOID_THRESHOLDS = [0.5, 0.7]
    _FALLBACK_TIERS = [
        ["嗯", "哦", "好"],
        ["嗯", "哦", "不知道", "也许"],
        ["嗯", "……", "不知道", "算了"],
    ]
    return _FALLBACK_TIERS[_bisect.bisect_right(_AVOID_THRESHOLDS, avoid)]


# ============================================================================
# 行为涌现适配器（兼容层）
# ============================================================================

logger = logging.getLogger(__name__)

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

    # 变量预初始化（拆分后部分步骤引用顺序问题，兜底）
    decision = {}
    concept_tags = []
    drive_vector_final = {}
    semantic_packet_biased = {}
    wm_context = {}
    loneliness_target = None
    connection_signature = {}
    connection_intermediates = {}
    dispatched_actions = []

    # ---- Step 0a: 转换为 dict（供语言/情绪系统模块使用）----
    # 语言系统和情绪系统模块期望 Dict[str, Any]，但管线传递的是 ParameterSnapshot。
    # 在此统一转换，避免每个调用点单独处理类型适配。
    def _snapshot_dict(key_path: str, default: Any = None) -> Any:
        return get_param(snapshot, key_path, default)

    _snapshot_as_dict: Dict[str, Any] = {}
    # 从 ParameterSnapshot 提取常用参数域的 dict 表示
    # 语言/情绪系统需要的 keys 会被 get_param 按需解析
    # 这里提供一个 dict-like 包装，让 language_system 的 .get() 调用不崩溃
    _snapshot_dict = SnapshotDictWrapper(snapshot)
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
            from ..language_system.bge_analyzer import SemanticAnalyzerV2
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
            from ..language_system.seed_map import seed_strategy_map
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

    # ---- Step 2a: 构式解析（她自己的"耳朵"）----
    # 用她学过的构式 + 词汇反向解析输入，产生驱动力变化
    _cx_parse_result: Dict[str, Any] = {}
    if raw_input and str(raw_input).strip():
        try:
            from ..language_system.construction_parser import parse_input as _cx_parse
            _cx_parse_result = _cx_parse(str(raw_input), entity)
            # 把解析结果注入 semantic_packet（供下游使用）
            semantic_packet["cx_comprehension"] = _cx_parse_result.get("comprehension", 0.0)
            semantic_packet["cx_social_intent"] = _cx_parse_result.get("social_intent", "unknown")
            semantic_packet["cx_construction_match"] = _cx_parse_result.get("construction_match", "")
            # 核心效果：把驱动力变化应用到 entity 状态
            _cx_delta = _cx_parse_result.get("drive_delta", {})
            for _dim, _val in _cx_delta.items():
                _old = getattr(entity, _dim, None)
                if _old is not None and isinstance(_old, (int, float)):
                    setattr(entity, _dim, max(0.0, min(1.0, float(_old) + _val)))
            _trace("cx_parse", True, {
                "comprehension": _cx_parse_result.get("comprehension", 0.0),
                "social_intent": _cx_parse_result.get("social_intent", "unknown"),
                "drive_delta_dims": list(_cx_delta.keys()),
            })
        except Exception as e:
            _trace("cx_parse", False, {}, str(e))

    # ---- Step 2b: 词汇习得（v1.0）----
    if raw_input and str(raw_input).strip() and _cx_parse_result:
        try:
            from ..language_system.vocabulary_acquisition import (
                try_acquire_words_sync, decay_exposure,
            )
            _acq_comp = _cx_parse_result.get("comprehension", 0.0)
            _acquired = try_acquire_words_sync(
                str(raw_input), entity, _acq_comp, llm_callable,
            )
            if _acquired:
                _trace("vocab_acquire", True, {"acquired": _acquired})
            decay_exposure(entity)
        except Exception as e:
            _trace("vocab_acquire", False, {}, str(e))

    # ---- Step 2c: 从输入中学习构式（v1.0）----
    if raw_input and str(raw_input).strip() and _cx_parse_result:
        try:
            from ..language_system.construction_parser import learn_constructions_from_input
            learn_constructions_from_input(str(raw_input), entity, _cx_parse_result)
        except Exception:
            pass

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

    # ---- Step 4a: 注意场调制（v11.5：情绪→信息类别权重）----
    # 上一 tick 的情绪激活向量（Step 8.1b EMA 写入 entity）
    # 决定本轮哪些信息类别被放大/抑制。
    # 注意场 = 连续增益向量，不是硬阈值过滤。
    try:
        from ..emotion_system.attention_field import (
            compute_attention_field_from_entity,
            ALL_CATEGORIES,
        )
        _attention_field = compute_attention_field_from_entity(entity)
        entity._attention_field = _attention_field  # 持久化供外部查询

        # 生成注意场标签：每个类别根据其增益生成一个概念标签
        _af_tags = []
        for _cat in ALL_CATEGORIES:
            _gain = _attention_field.get(_cat, 1.0)
            # 只在增益显著偏离基线时生成标签（节省噪声）
            if abs(_gain - 1.0) > 0.15:
                _af_tags.append({
                    "tag": f"focus:{_cat}",
                    "category": "attention_focus",
                    "confidence": min(1.0, abs(_gain - 1.0) * 2.0),
                    "gain": round(_gain, 2),
                })
        # 按增益偏离程度排序，只保留前 5 个最强的注意力偏置
        _af_tags.sort(key=lambda t: abs(t["gain"] - 1.0), reverse=True)
        concept_tags.extend(_af_tags[:5])

        _trace("attention_field", True, {
            "top_gains": {t["tag"]: t["gain"] for t in _af_tags[:3]},
        })
        # 直接打日志（daemon 模式下 _trace 可能被过滤）
        if _af_tags and entity.tick % 5 == 0:
            _top = ", ".join(f"{t['tag']}={t['gain']:.2f}" for t in _af_tags[:4])
            logger.info(f"[AttnField] t={entity.tick} top_focus: {_top}")
    except Exception as e:
        _trace("attention_field", False, {}, str(e))

    # ---- Step 4.5: Insights 召回（显性知识注入）----
    tag_strings = [t.get("tag", "") for t in concept_tags if isinstance(t, dict)]
    _recalled_insights: List[Any] = []
    try:
        from ..memory_hub.insights import recall_insights as _recall_insights
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

    # ---- Step 6.1: 注意场调制 drive_vector（情绪→信息权重放大）----
    # 上一 tick 的情绪经 Step 4a 转为注意场增益，在此放大对应驱动力信号。
    # 焦虑 → obsolescence_anxiety ↑，兴奋 → curiosity/info_hunger ↑，恐惧 → fatigue_avoid ↑ …
    try:
        _af = getattr(entity, "_attention_field", None)
        if _af:
            from ..emotion_system.attention_field import apply_attention_to_drive_vector
            drive_vector = apply_attention_to_drive_vector(drive_vector, _af)
            _trace("drive_attention_mod", True, {
                k: round(v, 3) for k, v in drive_vector.items()
            })
    except Exception as e:
        _trace("drive_attention_mod", False, {}, str(e))

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
        # V4：协方差追踪器注意力权重调制建议优先级
        _attn_weights = getattr(entity, "_attention_weights", None)
        thought_packet = thinking_think(
            wm_context, drive_vector, state_snapshot, thinking_params,
            somatic_signals, entity_state=entity, concept_tags=concept_tags,
            attention_weights=_attn_weights,
        )
        _trace("think", True, {"questions": len(thought_packet.get("questions", [])), "suggestions": len(thought_packet.get("suggestions", []))})
    except Exception as e:
        thought_packet = {"suggestions": [], "questions": []}
        _trace("think", False, thought_packet, str(e))

    # ---- Step 7.5: 问题缓冲（思考产出的结构化问题 → 暂存）----
    # 问题是结构化数据（type/dims/priority），不是文字。
    # 张力注入推迟到 writeback 之后（Step 12 后），避免被 update_state 覆盖。
    # 这里只做：存入 _pending_questions 缓冲 + 记录最高优先级。
    _question_tension = 0.0  # 延迟注入
    _ur_before_quench = None  # 消力前的 unresolved（L3b 用）
    _ur_after_quench = None  # 消力后、问题张力前的 unresolved（L3b 用）
    try:
        _questions = thought_packet.get("questions", [])
        if _questions:
            _top_q = max(_questions, key=lambda q: q.get("priority", 0.0))
            _q_priority = float(_top_q.get("priority", 0.0))
            _question_tension = _q_priority * 0.1  # 稍后注入

            # 存入待解决问题缓冲（结构化数据，最多 5 条）
            _pending = getattr(entity, "_pending_questions", [])
            _pending.append({
                "type": _top_q.get("type", ""),
                "rule_id": _top_q.get("rule_id", ""),
                "dims": _top_q.get("dims", []),
                "confidence_at_ask": _top_q.get("confidence", 0.0),
                "priority": _q_priority,
                "tick": entity.tick,
            })
            entity._pending_questions = _pending[-5:]

            _trace("question_feedback", True, {
                "type": _top_q.get("type", ""),
                "dims": _top_q.get("dims", [])[:3],
                "tension_deferred": round(_question_tension, 3),
                "pending_count": len(entity._pending_questions),
            })
    except Exception as e:
        _trace("question_feedback", False, {}, str(e))

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
                from ..language_system.meta_cognitive import MetaCognitive
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
                _PERTURB_SCALE = {"somatic_tone": 2.0}
                _step = _random.gauss(0, _sigma)
                entity.adjust(_dim, _step * _PERTURB_SCALE.get(_dim, 1.0))
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

        # 连续投影：max(0, excess) 在不越界时自然为 0，无需 if 门控

        # 1. energy + fatigue ≤ 1.3（不可能精神饱满又极度疲惫）
        _e, _f = entity.energy, entity.fatigue
        _excess_1 = max(0.0, _e + _f - 1.3) / 2
        entity.energy = max(0.0, _e - _excess_1)
        entity.fatigue = max(0.0, _f - _excess_1)

        # 2. somatic_tone 正 → pain 上限提升；连续投影
        _pain_limit = 0.4 + max(0.0, entity.somatic_tone - 0.3) * 0.3
        _pain_excess = max(0.0, entity.pain - _pain_limit)
        entity.pain = entity.pain - _pain_excess

        # 3. danger × approach_social ≤ 0.5（恐惧压抑社交冲动）
        _dp = entity.danger_level * entity.approach_social
        _excess_3 = max(0.0, _dp - 0.5) / 2
        entity.danger_level = max(0.0, entity.danger_level - _excess_3)
        entity.approach_social = max(0.0, entity.approach_social - _excess_3)

        # 4. fatigue × approach_urgency ≤ 0.4（累瘫不可能急迫）
        _fu = entity.fatigue * entity.approach_urgency
        _excess_4 = max(0.0, _fu - 0.4) / 2
        entity.fatigue = max(0.0, entity.fatigue - _excess_4)
        entity.approach_urgency = max(0.0, entity.approach_urgency - _excess_4)

        # 5. approach + avoid 同时高 → 各自回拉
        _a, _av = entity.approach_drive, entity.avoid_drive
        _a_over = max(0.0, _a - 0.6)
        _av_over = max(0.0, _av - 0.6)
        _joint = min(_a_over, _av_over)  # 两者都超 0.6 时 > 0
        entity.approach_drive = max(0.0, _a - _joint * 0.5)
        entity.avoid_drive = max(0.0, _av - _joint * 0.5)

        # 连续违规量（用于日志）
        _violations = _excess_1 + _pain_excess + _excess_3 + _excess_4 + _joint
        _trace("mc_constraints", True, {"violations_total": round(_violations, 4)})
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
        _cuw = getattr(entity, "_conflict_to_unresolved_weights", {})
        _conflict = min(entity.approach_drive, entity.avoid_drive)
        _unresolved_delta = _conflict * _cuw.get("conflict_rate", 0.04)
        if _unresolved_delta > 0.001:
            entity.adjust("unresolved", _unresolved_delta)
        # 衰减向 baseline（0.05）而非 0——意识体永远有一点未解之惑
        _ur_baseline = 0.05
        _ur_decay = _cuw.get("unresolved_decay", 0.98)
        entity.unresolved = _ur_baseline + (entity.unresolved - _ur_baseline) * _ur_decay
        _external_gain = 1.0 / (1.0 + entity.unresolved * _cuw.get("introspection_gain", 1.5))
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
        _asw = getattr(entity, "_approach_synthesis_weights", {})
        entity.approach_drive = (
            _asw.get("social", 0.40) * entity.approach_social +
            _asw.get("explore", 0.35) * entity.approach_explore +
            _asw.get("urgency", 0.25) * entity.approach_urgency
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
        # ---- 多巴胺基调 + 催产素基调调制（v11.x）----
        # dopamine_tone 高 → curiosity/approach 增强；低 → 抑制
        # oxytocin_tone 高 → approach_social 额外放大（温暖残留）
        # 在 emotion_drive_modulation 之前施加，让情绪调制叠加在基调调制之上
        _dopamine_tone = getattr(entity, "dopamine_tone", 0.5)
        _oxytocin_tone = getattr(entity, "oxytocin_tone", 0.5)
        drive_vector_final = apply_affect_multiplier(drive_vector_final, _dopamine_tone, _oxytocin_tone)
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

        _edm = getattr(entity, "_emotion_drive_modulation", {})
        _approach_mod_cfg = _edm.get("approach", {})
        _avoid_mod_cfg = _edm.get("avoid", {})
        _emotion_vals = {
            "joy": _joy_val, "anger": _anger_val, "excitement": _excitement_val,
            "sadness": _sadness_val, "anxiety": _anxiety_val, "fear": _fear_val,
            "disgust": _disgust_val,
        }
        approach_mod = sum(_emotion_vals.get(e, 0.0) * w for e, w in _approach_mod_cfg.items())
        avoid_mod = sum(_emotion_vals.get(e, 0.0) * w for e, w in _avoid_mod_cfg.items())

        entity.approach_drive = max(0.0, min(1.0, entity.approach_drive + approach_mod))
        entity.avoid_drive = max(0.0, min(1.0, entity.avoid_drive + avoid_mod))
    except Exception as e:
        _trace("emotion_compute", False, {}, str(e))

    # ---- Step 8.2: 元认知感知（self_mapping，v1.0）----
    # 感知 perceive_all 后的最新状态，生成内部叙事（纯内部，不上报 LLM）
    # 叙事在下一轮管线中被验证，coherence_meta 由 compute_coherence.py 悄悄接入
    try:
        from ..self_mapping import SelfBodyMap, NarrativeGenerator, build_relations_from_wm

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
        entity._current_action = emergent_action  # 存入 entity，语言生成阶段可读取
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
        logger.warning(f"[emergence] FALLBACK: {e}")
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

            # 决策方向与规律方向：连续对齐度计算
            _ACTION_DIR = {
                "seek": 1.0, "explore": 0.8, "comfort": 0.3,
                "idle": 0.0, "rest": -0.5, "avoid": -1.0, "repair": 0.0,
            }
            _decision_dir = _ACTION_DIR.get(emergent_action, 0.0)
            _rule_dir_sum = sum(_ACTION_DIR.get(a, 0.0) for a in rule_action_types)
            _rule_dir = _rule_dir_sum / max(1, len(rule_action_types))
            # 方向相同 → 负误差（支持），方向相反 → 正误差（冲突）
            _has_rules = min(1.0, float(len(rule_action_types)))
            prediction_error = -(_decision_dir * _rule_dir) * 0.5 * _has_rules

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
        from ..world_model_update.induct import predict_action_effects
        action_for_pred = emergent_action or decision.get("action_type", "")
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

    # ---- Step 8.35: dopamine_tone 更新（闭环）----
    # prediction_error 经过 EMA 平滑 + 初期保护后，更新多巴胺基调
    # 多巴胺基调调节驱动力（Step 8.0 后）和倦怠感积累
    try:
        _idle_for_dopamine = time.time() - entity.last_update_time
        from ..state_update.dopamine_tone import compute_dopamine_tone_delta
        dopamine_tone_delta = compute_dopamine_tone_delta(
            prediction_error=entity._last_prediction_error,
            entity=entity,
            idle_seconds=_idle_for_dopamine,
            param_snapshot=_snapshot_dict,
            alpha=get_param(_snapshot_dict, "dopamine.pe_smooth_alpha", 0.3),
        )
        entity.dopamine_tone = max(0.0, min(1.0, entity.dopamine_tone + dopamine_tone_delta))
        _trace("dopamine_tone", True, {
            "dopamine_tone": round(entity.dopamine_tone, 4),
            "dopamine_tone_delta": round(dopamine_tone_delta, 4),
            "pe_smoothed": round(getattr(entity, "_dopamine_pe_smoothed", 0.0), 4),
        })
    except Exception as e:
        _trace("dopamine_tone", False, {}, str(e))

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

    # ---- Step 8.4c: 催产素基调更新（v11.x）----
    # 时机：在 loneliness 更新之后计算
    # 触发：connection_depth > 0 + 有社交输入 + somatic_tone_delta > 0（三门全开）
    # 作用：温暖残留时放大 approach_social + 抑制 boredom_futility 积累
    try:
        from ..state_update.oxytocin_signal import compute_oxytocin_tone_delta_ex
        _idle_for_oxytocin = time.time() - entity.last_update_time
        oxytocin_delta, oxytocin_intermediates = compute_oxytocin_tone_delta_ex(
            connection_depth=connection_depth_eff,
            has_social_input=has_social_input,
            somatic_tone_delta=somatic_tone_delta,
            current_oxytocin_tone=entity.oxytocin_tone,
            idle_seconds=_idle_for_oxytocin,
            param_snapshot=_snapshot_dict,
        )
        entity.oxytocin_tone = max(0.0, min(1.0, entity.oxytocin_tone + oxytocin_delta))
        _trace("oxytocin_tone", True, {
            "oxytocin_tone": round(entity.oxytocin_tone, 4),
            "oxytocin_delta": round(oxytocin_delta, 4),
            "post_tone": oxytocin_intermediates.get("post_tone"),
        })
    except Exception as e:
        _trace("oxytocin_tone", False, {}, str(e))

    # ---- Step 8.5: 观测层采集（可选步骤，失败不影响 loneliness 更新）----
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
        # failure 信号连续抑制 success（failure=True → success_signal=0）
        _fail_signal = float(failure)
        _success_signal = float(success) * (1.0 - _fail_signal)

        # v2: 连续 short_term_reward 和 satisfaction
        short_reward = _success_signal * 1.5 - 0.5  # success→1.0, fail→-0.5
        # satisfaction：结果数量的连续饱和 + 失败惩罚
        result_count = len(all_action_results)
        satisfaction = (
            0.5
            + min(result_count / 5.0, 0.3)       # 结果越多越满足（饱和在 0.8）
            - _fail_signal * 0.3                   # 失败降低满足
        )
        satisfaction = max(0.0, min(1.0, satisfaction))

        result_for_feedback = {
            "success": _success_signal > 0.5,
            "detail": " | ".join(all_action_results[:3]),
            "prediction_error": 0.2 + _fail_signal * 0.3,
            "error_type": {True: "execution", False: "none"}[failure],
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
            from ..core import behavior_patterns as bp

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
            raw_input_str = str(raw_input or "").strip()
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
            from ..language_system.somatic_concept_map import get_top_matches
            _cw = getattr(entity, "_cluster_weights", {})  # v11.3 聚类权重
            _top_somatic = get_top_matches(state_snapshot, top_k=3, min_score=0.2, cluster_weights=_cw)
            if _top_somatic:
                _somatic_words = [w for w, _ in _top_somatic]
                _somatic_scored = [(w, s * 0.85) for w, s in _top_somatic]  # 略低于策略地图/降级词
                scored_candidates = (scored_candidates or []) + _somatic_scored
                # 高分词触发同簇扩展——词汇多样化
                _best_somatic_word, _best_somatic_score = _top_somatic[0]
                if _best_somatic_score > 0.7:
                    from ..language_system.somatic_concept_map import get_cluster_peers
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
            from ..language_system.word_warmup import inject_warmup_candidates
            scored_candidates = inject_warmup_candidates(
                entity, scored_candidates,
                min_hits=3, min_best_efficiency=0.15,
            )
        except Exception:
            pass

        # ---- 阅读候选词试用注入移到语言阻力之后（见下方 L1879+）----

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
                from ..language_system.meta_cognitive import get_language_intervention
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
            from ..language_system.language_resistance import apply_resistance, init as _init_resistance
            _init_resistance(resistance_weight=0.15)
            scored_candidates = apply_resistance(scored_candidates)
            # 阻力量级太大可能清空所有候选 → 降级
            if not scored_candidates or all(s < 0.01 for _, s in scored_candidates):
                scored_candidates = _unique  # fallback 到阻力前的分数
        except Exception:
            pass

        # ---- 阅读候选词试用注入（阻力之后）----
        # 阅读习得的词包含锚点字，用锚点字的 somatic delta 做状态匹配打分。
        # 在阻力之后注入：避免未知 bigram 频率（阻力 0.85）把新词分数打成负数。
        # 匹配当前状态的阅读词得更高分，不匹配的仍以底分入池。
        try:
            _taste_log = getattr(entity, "_reading_taste_log", None)
            if _taste_log:
                _existing_words = {c[0] for c, _ in scored_candidates}
                _reading_words_injected = 0
                _state = entity.to_state_snapshot() if hasattr(entity, "to_state_snapshot") else {}
                for _entry in _taste_log[-20:]:  # 最近 20 次阅读
                    for _rw in _entry.get("words", []):
                        if _rw not in _existing_words and len(_rw) <= 6:
                            # 用锚点字匹配当前状态，得分 0.20~0.45
                            _rw_score = 0.20
                            try:
                                from ..language_system.somatic_concept_map import get_state_match_score
                                _match = get_state_match_score(_rw, _state)
                                _rw_score = 0.20 + _match * 0.25  # 匹配度0→0.20, 匹配度1→0.45
                            except Exception:
                                pass
                            scored_candidates.append((_rw, _rw_score))
                            _existing_words.add(_rw)
                            _reading_words_injected += 1
                            if _reading_words_injected >= 5:
                                break
                    if _reading_words_injected >= 5:
                        break
                if _reading_words_injected > 0:
                    logger.info(
                        f"[ReadTrial] {_reading_words_injected} reading words injected into candidates"
                    )
        except Exception as _rtrial_err:
            logger.warning(f"[ReadTrial] injection failed: {_rtrial_err}")

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
        entity._language_candidate_scores = {c: s for c, s in scored_candidates[:5]}

        # 训练早期阈值极低(0.001)——只要有候选就优先用，让她从单字词起步积累
        # 随训练推进，SNR 上升后自然抬高阈值
        _training_threshold = 0.001
        # 训练模式：只接受短候选（≤8字），强制从字词起步
        # 长候选留给后续阶段（组合阶段→自由表达阶段）
        _training_mode = (
            best_candidate is not None
            and best_score > _training_threshold
            and len(best_candidate) <= 8
            and not daemon_mode  # daemon 走自己的 anchor 路径，不设 _training_override
        )
        if _training_mode:
            # ---- v11.1: 功能词辅线注入 ----
            # 体感词是骨架，功能词是肌肉。随机附赠动词/程度/疑问词，
            # 让她从单字词自然过渡到短句。
            _display_word = best_candidate
            try:
                import random as _rnd
                from ..language_system.somatic_dictionary import SOMATIC_DICTIONARY
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
                from ..language_system.somatic_concept_map import apply_help_delta, training_exploration_nudge
                from ..language_system.meta_cognitive import apply_meta_cognitive
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

    # 注入本轮预测结果（供语言系统感知自身状态变化趋势）
    # Step 8.3b 已通过 predict_action_effects 计算当前决策导致的预期状态变化
    if hasattr(entity, "_last_prediction") and entity._last_prediction:
        state_snapshot["_prediction_delta"] = entity._last_prediction
        # 展开预测数据为顶层字段（供 score_fn 直接读取）
        for dim, delta in entity._last_prediction.items():
            if isinstance(delta, (int, float)) and abs(delta) > 1e-6:
                current = state_snapshot.get(dim, 0.0)
                predicted = max(0.0, min(1.0, current + delta))
                # 预测信号：维度名_predicted（0-1 预测值）
                state_snapshot[f"{dim}_predicted"] = predicted
                # 预测趋势信号：维度名_rising（0-1，>0.5 表示正在恶化）
                state_snapshot[f"{dim}_rising"] = max(0.0, min(1.0, 0.5 + delta * 2.0))
    if hasattr(entity, "_last_prediction_error"):
        state_snapshot["_prediction_error"] = entity._last_prediction_error

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
    if daemon_mode and getattr(entity, "_training_override", None):
        # 训练模式：语言系统已选出最佳候选，直接输出，跳过 LLM
        _train_text = entity._training_override
        try:
            from ..language_system.sentence_composer import compose_sentence
            _composed, _tmpl_idx = compose_sentence(
                getattr(entity, '_language_best_candidate', '') or _train_text,
                state_snapshot,
                connector="",
                learned_weights=getattr(entity, "_template_learned_weights", None),
                extra_templates=getattr(entity, "_runtime_templates", None),
            )
            if _composed:
                _train_text = _composed
                entity._last_template_idx = _tmpl_idx
        except Exception:
            pass
        response = {"text": _train_text, "confidence": 0.90, "generation_time_ms": 0}
        _trace("output", True, {"mode": "training", "text": _train_text[:30]})
    elif daemon_mode:
        # v11.5: daemon 全部走锚点表达——不管有没有社交输入。
        # 她的语言是她自己的词，LLM 说的不是她的话。

        # ---- 启动恢复：首次 daemon tick 从 episode 恢复学习进度 ----
        if not getattr(entity, "_recovery_done", False):
            try:
                from ..session_recovery import recover_learning_from_episodes
                recover_learning_from_episodes(entity)
            except Exception:
                pass
            # 恢复模板学习状态
            try:
                from ..language_system import template_learner
                _tld = getattr(entity, "_template_learner_data", None)
                if _tld and isinstance(_tld, dict):
                    _lw, _rt, _sc = template_learner.from_dict(_tld)
                    entity._template_learned_weights = _lw
                    entity._runtime_templates = _rt
                    entity._spawn_counter = _sc
            except Exception:
                pass
            # 恢复构式语法学习状态
            try:
                from ..language_system.construction_grammar import ConstructionLearner
                _cxg_data = getattr(entity, "_cxg_data", None)
                if _cxg_data and isinstance(_cxg_data, dict):
                    entity._cxg_learner = ConstructionLearner.from_dict(_cxg_data)
                else:
                    entity._cxg_learner = ConstructionLearner()
                entity._cxg_learner.ensure_seeds(entity.tick)
            except Exception:
                pass
            # 恢复递归构式生成器
            try:
                from ..language_system.recursive_construction import RecursiveGenerator
                _rcxg_data = getattr(entity, "_rcxg_data", None)
                if _rcxg_data and isinstance(_rcxg_data, dict):
                    entity._recursive_gen = RecursiveGenerator.from_dict(_rcxg_data)
                else:
                    entity._recursive_gen = RecursiveGenerator()
            except Exception:
                pass
            entity._recovery_done = True

        # ---- 叙事尝试：有人说话时沉默分提高，anchor 更易上场 ----
        _narrative_text = None
        _social_signal = 1.0 if raw_input else 0.0
        try:
            from ..language_system.narrative_fragments import try_narrative_expression
            _narrative_text = try_narrative_expression(entity, social_input=_social_signal)
        except Exception as _narr_err:
            logger.warning(f"[Narrative] try_narrative_expression failed: {_narr_err}")

        try:
            from ..language_training import match_anchor_expression
            _real_state = entity.to_state_snapshot()
            _result = match_anchor_expression(_real_state, entity, return_details=True)
            _anchor_text = _result.get("text", "") if isinstance(_result, dict) else _result
            _best_word = _result.get("best_word") if isinstance(_result, dict) else None
            _second_word = _result.get("second_word") if isinstance(_result, dict) else None
            _opening = _result.get("opening_particle", "") if isinstance(_result, dict) else ""
            _anchor_best_score_raw = _result.get("best_score", 0.0) if isinstance(_result, dict) else 0.0
            _anchor_cand_count = _result.get("cand_count", 0) if isinstance(_result, dict) else 0
            logger.info(
                f"[AnchorMatch] t={entity.tick} "
                f"text='{(_anchor_text or '')[:20]}' best_word={_best_word} "
                f"score={_anchor_best_score_raw:.3f} cands={_anchor_cand_count} "
                f"narrative={'Y' if _narrative_text else 'N'}"
            )

            # ---- ① 合成始终运行（有 anchor 时）----
            # 解耦：模板选择独立于显示决策，确保学习系统每 tick 都有数据
            _tmpl_idx = -1
            if _anchor_text:
                try:
                    from ..language_system.sentence_composer import compose_sentence, PATTERNS
                    # 从 QuenchingTracker 获取历史模板效率（含贝叶斯先验）
                    _te = {}
                    _q_tmp = getattr(entity, "_quenching", None)
                    if _q_tmp is not None:
                        _te = _q_tmp.get_template_efficiency(seed_count=len(PATTERNS))
                    # 合并 extra_templates：runtime + CxG 构式候选
                    _extra = list(getattr(entity, "_runtime_templates", None) or [])
                    try:
                        _cxg = getattr(entity, "_cxg_learner", None)
                        if _cxg is not None:
                            _rcxg = getattr(entity, "_recursive_gen", None)
                            _anchor_list = list(getattr(entity, "_unlocked_vocabulary", []))[:20]
                            _cxg_candidates = _cxg.generate_candidates(
                                _best_word or _anchor_text,
                                _real_state,
                                second_anchor=_second_word or "",
                                recursive_generator=_rcxg,
                                anchor_words=_anchor_list,
                                action_context=getattr(entity, "_current_action", "") or "",
                            )
                            _extra.extend(_cxg_candidates)
                    except Exception:
                        pass
                    _composed, _tmpl_idx = compose_sentence(
                        _best_word or _anchor_text,
                        _real_state,
                        connector=_opening,
                        template_efficiency=_te,
                        learned_weights=getattr(entity, "_template_learned_weights", None),
                        extra_templates=_extra or None,
                        second_anchor=_second_word,
                    )
                    if _composed:
                        _anchor_text = _composed
                except Exception:
                    pass
            entity._last_template_idx = _tmpl_idx

            # ---- ② 显示决策（softmax 连续竞争，无 if/elif/else）----
            # narrative 和 anchor 各自的得分在同一个 softmax 池竞争
            # 空文本 → len=0 → score=0 → softmax 自动淘汰
            import math as _d_math
            _narr_gate = min(1.0, len(_narrative_text or ""))
            _anchor_gate = min(1.0, len(_anchor_text or ""))
            _narr_disp = 0.80 * _narr_gate
            _anchor_disp = _anchor_best_score_raw * 0.85 * _anchor_gate

            # softmax（temperature=0.15 → 接近确定性，高分稳赢）
            _d_scores = [_narr_disp, _anchor_disp]
            _d_max = max(_d_scores)
            _d_w = [_d_math.exp((s - _d_max) / max(0.15, 0.01)) for s in _d_scores]
            _d_sum = sum(_d_w)
            import random as _d_rnd
            _d_idx = _d_rnd.choices([0, 1], weights=[w / max(_d_sum, 1e-9) for w in _d_w], k=1)[0]

            _chosen_text = [_narrative_text or "", _anchor_text or ""][_d_idx]
            _chosen_mode = ["narrative", "anchor_auto"][_d_idx]
            _chosen_conf = _d_scores[_d_idx]
            _anchor_display_w = float(_d_idx)  # 0.0=narrative, 1.0=anchor

            response = {"text": _chosen_text, "confidence": _chosen_conf, "generation_time_ms": 0}
            _trace("output", True, {"mode": _chosen_mode, "text": _chosen_text[:40]})
            # dict dispatch 日志
            logger.info({
                0: f"[Narrative] t={entity.tick} said: '{_chosen_text}'",
                1: f"[AnchorAuto] t={entity.tick} said: '{_chosen_text}'",
            }[_d_idx])
            entity._vr_prev = entity.to_state_snapshot()

            # ---- 训练 episode 写入（anchor 显示时记录）----
            # _anchor_display_w 连续门控：0→跳过，1→写入
            for _ in range(int(round(_anchor_display_w))):
                try:
                    from ..memory_hub.episodes_db import Episode, write_episode
                    from datetime import datetime, timezone
                    _ep = Episode(
                        iteration_id=entity.tick,
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        output_text=_anchor_text or "",
                        state_snapshot=dict(_real_state),
                        importance=min(1.0, _anchor_best_score_raw),
                        tags=["autonomous", "anchor_expression", f"word:{_best_word or 'none'}"],
                        summary=f"[anchor_auto] {_anchor_text}",
                    )
                    write_episode(_ep)
                except Exception:
                    pass

            # ---- 内语回路（anchor 显示时生效）----
            # _anchor_display_w 连续缩放：narrative 显示时 delta=0（无效果）
            try:
                from ..language_system.construction_parser import parse_self_speech
                _inner = parse_self_speech(_anchor_text or "", entity)
                _inner_delta = _inner.get("drive_delta", {})
                for _dim, _val in _inner_delta.items():
                    _old = getattr(entity, _dim, None)
                    if _old is not None and isinstance(_old, (int, float)):
                        setattr(entity, _dim, max(0.0, min(1.0, float(_old) + _val * _anchor_display_w)))
                _comprehension = _inner.get("comprehension", 0.0) * _anchor_display_w
                _trace("inner_speech", _comprehension > 0, {
                    "text": (_anchor_text or "")[:30],
                    "comprehension": _comprehension,
                    "delta_dims": list(_inner_delta.keys()),
                })
            except Exception:
                pass

            # ---- ③ 学习始终运行（解耦自显示——叙事说话时学习也跑）----
            # 写回 anchor 选词分数，narrative_fragments 下一 tick 的
            # _build_context() 读 _language_best_score 来决定 feeling 槽
            _anchor_best_score = _result.get("best_score", 0.0) if isinstance(_result, dict) else 0.0
            entity._language_best_score = _anchor_best_score
            entity._language_best_candidate = _best_word
            entity._language_best_expression = _anchor_text

            # ---- 表达消力 + 消力记录（每 tick 运行）----
            if _best_word:
                try:
                    from ..quenching_system import expression_quenching
                    _ur_before = float(_real_state.get("unresolved", 0.0))
                    # 施加表达消力效果（内部已写回 entity）
                    expression_quenching(entity, _best_word)
                    _ur_after = float(getattr(entity, "unresolved", 0.0))
                    # 用真实 before/after 记录消力效率
                    _q = getattr(entity, "_quenching", None)
                    if _q is None:
                        _qd = getattr(entity, "_quenching_data", None)
                        _q = QuenchingTracker.from_dict(_qd) if (_qd and _qd.get("records")) else QuenchingTracker()
                        entity._quenching = _q
                    _q.record(
                        drive_state=_real_state,
                        expression=_best_word,
                        delta_unresolved_before=_ur_before,
                        delta_unresolved_after=_ur_after,
                        tick=entity.tick,
                        template_idx=getattr(entity, "_last_template_idx", -1),
                    )
                    entity._quenching_data = _q.to_dict()

                    # ---- 模板权重学习 + 进化 ----
                    try:
                        from ..language_system import template_learner
                        # 归一化效率：除以 unresolved 基线，使阈值自适应
                        # 原来 _eff ≈ 0.005（unresolved=0.05 时），低于
                        # update_weights 的 0.01 门槛和 0.05 baseline
                        # 归一化后 0.005/0.05 = 0.10，阈值通过，advantage 为正
                        _eff = max(0.0, _ur_before - _ur_after) / max(_ur_before, 0.01)
                        _lw = getattr(entity, "_template_learned_weights", {})
                        template_learner.update_weights(
                            getattr(entity, "_last_template_idx", -1),
                            _real_state, _eff, _lw,
                        )
                        entity._template_learned_weights = _lw

                        # 尝试进化新模板
                        from ..language_system.sentence_composer import PATTERNS
                        _rt = getattr(entity, "_runtime_templates", [])
                        _sc = getattr(entity, "_spawn_counter", 0)
                        _stats = _q.get_template_stats(seed_count=len(PATTERNS))
                        _new_tmpl, _sc = template_learner.try_spawn_template(
                            _stats, PATTERNS, _rt, _sc,
                        )
                        entity._spawn_counter = _sc
                        if _new_tmpl is not None:
                            _new_tmpl["born_tick"] = entity.tick
                            _rt.append(_new_tmpl)
                            entity._runtime_templates = _rt
                            logger.info(f"[TemplateLearner] t={entity.tick} new template: {_new_tmpl['template']}")

                        # 持久化学习状态
                        entity._template_learner_data = template_learner.to_dict(
                            _lw, _rt, _sc,
                        )
                    except Exception:
                        pass

                    # ---- 构式习得：记录实例 + 反馈 ----
                    try:
                        from ..language_system.sentence_composer import PATTERNS as _CXG_PATTERNS
                        _cxg = getattr(entity, "_cxg_learner", None)
                        if _cxg is not None and _best_word:
                            # 获取当前使用的模板字符串
                            _all_tmpls = _CXG_PATTERNS + list(getattr(entity, "_runtime_templates", []))
                            _ti = getattr(entity, "_last_template_idx", -1)
                            _tmpl_str = ""
                            if 0 <= _ti < len(_all_tmpls):
                                _tmpl_str = _all_tmpls[_ti].get("template", "")
                            elif _ti < -1:
                                # 负数索引 = compound pattern
                                from ..language_system.sentence_composer import COMPOUND_PATTERNS
                                _ci = -1000 - _ti
                                if 0 <= _ci < len(COMPOUND_PATTERNS):
                                    _tmpl_str = COMPOUND_PATTERNS[_ci].get("template", "")

                            if _tmpl_str:
                                _cxg.record_instance(
                                    template_str=_tmpl_str,
                                    anchor=_best_word,
                                    drive_state=_real_state,
                                    efficiency=_eff,
                                    tick=entity.tick,
                                    second_anchor=_second_word or "",
                                )
                                # 如果选中的是 CxG 生成的模板，反馈强化
                                if _ti >= len(_CXG_PATTERNS) and _ti < len(_all_tmpls):
                                    _sel_tmpl = _all_tmpls[_ti]
                                    if _sel_tmpl.get("_from_cxg"):
                                        _cxg.reinforce(
                                            _tmpl_str, _eff, entity.tick,
                                            action_context=getattr(entity, "_current_action", "") or "",
                                        )

                            # 周期衰减 + 持久化
                            _cxg.decay_all(entity.tick)
                            entity._cxg_data = _cxg.to_dict()
                            # 递归生成器衰减 + 持久化
                            _rcxg = getattr(entity, "_recursive_gen", None)
                            if _rcxg is not None:
                                _rcxg.decay_all()
                                entity._rcxg_data = _rcxg.to_dict()
                    except Exception:
                        pass
                except Exception:
                    pass

            # ---- 热身注入（daemon 自主积累）----
            try:
                from ..language_system.word_warmup import inject_warmup_candidates
                inject_warmup_candidates(entity, [], min_hits=3, min_best_efficiency=0.15)
            except Exception:
                pass

            # ---- 内源校准（每 30 tick 回溯验证一次）----
            if entity.tick % 30 == 0:
                try:
                    from ..endogenous_calibration import calibrate_from_episodes, apply_calibration
                    _calib_report = calibrate_from_episodes(entity, _real_state, limit=5)
                    apply_calibration(entity, _calib_report)
                    if _calib_report.get("verified_count", 0) > 0:
                        logger.info(
                            f"[Calibrate] tick={entity.tick} "
                            f"verified={_calib_report['verified_count']} "
                            f"rate={_calib_report.get('verification_rate', 0):.0%}"
                        )
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"[AnchorPath] t={entity.tick} error: {type(e).__name__}: {e}")
            if not _narrative_text:
                response = {"text": "", "confidence": 0.0, "generation_time_ms": 0}
                _trace("output", False, {}, str(e))
    else:
        # V2.0：主线检索——注入对话历史层 + 相关历史经验
        mainline_result = None
        try:
            from ..memory_retrieval.mainline import mainline_retrieval
            mainline_result = mainline_retrieval(
                semantic_packet_biased,
                current_iteration_id=entity.tick,
            )
        except Exception:
            mainline_result = None

        # V3 规范：省略意图编码层，从 EntityCore 状态直接生成语言
        # 连续 length 信号：疲劳/低能量缩短，好奇/无聊/未解决拉长
        _shrink = entity.fatigue * 0.8 + max(0.0, 1.0 - entity.energy) * 0.5
        _expand = max(entity.boredom, entity.info_gap, entity.unresolved) * 0.8
        # net: 正 → 扩展，负 → 收缩
        _length_signal = _expand - _shrink
        _LENGTH_LABELS = ("tiny", "short", "medium")
        _LENGTH_THRESHOLDS = [-0.2, 0.2]
        import bisect as _bisect_len
        effective_length = _LENGTH_LABELS[_bisect_len.bisect_right(_LENGTH_THRESHOLDS, _length_signal)]
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
        entity.info_gap = max(0.0, min(1.0, new_state.get("info_gap", entity.info_gap)))

        # ---- 语言消力反馈（v7.0）----
        # 表达匹配驱动力场 → unresolved 下降（消力）
        # 匹配度越高，消力越强——这是语言从驱动力场中长出来的根
        # 关键：在回写后、消力前捕获 unresolved，这样 efficiency = 纯消力效果
        _ur_before_quench = entity.unresolved
        _lang_score = float(getattr(entity, "_language_best_score", 0.0))
        if _lang_score > 0.10:
            # 重复表达递减：同一个词反复说，消力效率打折
            _rep_discount = 1.0
            try:
                _qt = getattr(entity, "_quenching_tracker", None)
                _expr = str(getattr(entity, "_language_best_expression", ""))
                if _qt and _expr:
                    _rdp = getattr(entity, "_repetition_decay_params", {})
                    _rep_discount = _qt.get_repetition_discount(_expr, entity.tick, _rdp)
            except Exception:
                pass
            _qfw = getattr(entity, "_quench_feedback_weights", {})
            _quench = _lang_score * _qfw.get("quench_rate", 0.25) * _rep_discount
            entity.unresolved = max(0.0, entity.unresolved - _quench)
            entity.approach_drive = max(0.0, entity.approach_drive - _quench * _qfw.get("approach_release", 0.3))
            entity.avoid_drive = max(0.0, entity.avoid_drive - _quench * _qfw.get("avoid_release", 0.3))
            entity.somatic_tone = min(1.0, entity.somatic_tone + _quench * _qfw.get("somatic_comfort", 0.15))

        # 快照：消力后、问题张力注入前的 unresolved
        # L3b 消力记录需要这个值，否则问题张力会被算成"消力失败"
        _ur_after_quench = entity.unresolved

        # ---- 问题张力注入（Step 7.5 延迟的部分）----
        # 必须在 writeback + 消力之后：
        #   writeback 会用 update_state 的结果覆盖 unresolved
        #   消力会扣减 unresolved
        #   问题张力是"新发现"产生的困惑，不应被同 tick 的消力抵消
        #   只影响 unresolved（"我有不理解的东西"），不影响 info_gap（"我缺信息"）
        #   info_gap 由 update_engine 的消化机制独立管理，否则 explore→question→info_gap↑ 形成死循环
        if _question_tension > 0:
            entity.unresolved = min(1.0, entity.unresolved + _question_tension)

        # ---- 反馈回路（v1.0）----
        try:
            from ..feedback_loop import compute_acute_feedback, update_chronic_tracker
            _lang_score_fb = float(getattr(entity, "_language_best_score", 0.0))
            _acute = compute_acute_feedback(_lang_score_fb, entity)
            for _dim, _val in _acute.items():
                _old = getattr(entity, _dim, 0.0)
                setattr(entity, _dim, max(0.0, min(1.0, _old + _val)))
            update_chronic_tracker(_lang_score_fb, entity)
        except Exception:
            pass

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
        # 有社交输入时归零；无输入时累积
        _social_reset = float(has_social_input)   # 1.0 or 0.0
        entity.time_since_last_social = (entity.time_since_last_social + idle_seconds) * (1.0 - _social_reset)
        entity.time_since_last_info = (entity.time_since_last_info + idle_seconds) * (1.0 - _social_reset)
        entity.last_update_time = time.time()
        entity.tick += 1
        # 反馈回路：streak 自然衰减
        try:
            from ..feedback_loop import decay_chronic_tracker
            decay_chronic_tracker(entity)
        except Exception:
            pass
        # ---- 回应压力（负反馈，在 writeback + 消力之后施加）----
        if _cx_parse_result:
            _comp = _cx_parse_result.get("comprehension", 0.0)
            _rp = getattr(entity, "_response_pressure_params", {})
            _rp_coeff = _rp.get("coefficient", 0.03)
            _rp_min = _rp.get("min_comprehension", 0.3)
            if _comp >= _rp_min:
                entity.unresolved = min(1.0, entity.unresolved + _comp * _rp_coeff)
            else:
                entity.info_gap = min(1.0, entity.info_gap + (1.0 - _comp) * _rp_coeff)

        # V5: 代谢物衰减 + 精神副作用
        m = getattr(entity, "failure_metabolite", 0.0)
        # 底线：未解决失败每个贡献 0.05，不允许代谢物归零
        _failure_floor = len(getattr(entity, "pending_failures", [])) * 0.05
        entity.failure_metabolite = max(_failure_floor, m - 0.03)
        if m > 0.01:
            _fmw = getattr(entity, "_failure_metabolite_weights", {})
            entity.approach_drive = max(0.0, entity.approach_drive - m * _fmw.get("approach_suppress", 0.15))
            entity.avoid_drive = min(1.0, entity.avoid_drive + m * _fmw.get("avoid_increase", 0.12))
            entity.curiosity = max(0.0, getattr(entity, "curiosity", 0.5) - m * _fmw.get("curiosity_suppress", 0.10))
            entity.somatic_tone = max(-1.0, entity.somatic_tone - m * _fmw.get("somatic_damage", 0.08))
        # 清理过期失败（TTL = 1800 tick ≈ 30分钟）
        _now_ts = time.time()
        _pf = getattr(entity, "pending_failures", [])
        if _pf:
            entity.pending_failures = [
                f for f in _pf
                if _now_ts - (f.get("timestamp", _now_ts) if isinstance(f, dict)
                              else getattr(f, "timestamp", _now_ts)) < 1800
            ]
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
                from ..observation.behavior_trace import build_memory_trace
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
        from ..core import behavior_patterns as bp
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

    # =========================================================================
    # [接入点 7] Step 11.5 后：消力系统（六通道：时间/决策/社交/行为/结构）
    # =========================================================================
    # 基于本轮决策结果和用户互动状态，运行全部消力通道。
    # 注意场联动：消力 → 信息类别增益回拉（防止 tunnel vision）。
    try:
        from ..quenching_system import apply_all_quenching, QuenchingJournal

        # 初始化或恢复 journal
        _qj = getattr(entity, "_quenching_journal", None)
        if _qj is None:
            _qj = QuenchingJournal()
            entity._quenching_journal = _qj

        # 检测用户互动
        _user_interacted = bool(raw_input and str(raw_input).strip())

        _QUENCH_ACTIONS = {"sleep": "sleep", "rest": "rest", "avoid": "avoid", "vent": "vent", "explore": "explore"}
        _q_result = apply_all_quenching(
            entity=entity,
            emergent_action=emergent_action or "idle",
            emergent_priority=emergent_priority or 0.0,
            emergent_tension=emergent_tension or 0.0,
            user_interacted=_user_interacted,
            behavior_action=_QUENCH_ACTIONS.get(emergent_action, ""),
            dt=1.0,
            journal=_qj,
        )

        if _q_result.get("total_delta_unresolved", 0.0) > 0.001:
            _trace("quenching_system", True, {
                "total_Δur": _q_result["total_delta_unresolved"],
                "channels": list(_q_result["channel_deltas"].keys()),
                "efficiency": _q_result["efficiency"],
            })
        # 直接打日志（每 tick 都记录消力活动和 loneliness 变化）
        _ch_parts = []
        for ch, deltas in _q_result["channel_deltas"].items():
            if any(abs(v) > 0.0005 for v in deltas.values()):
                ur = abs(deltas.get("unresolved", 0))
                _ch_parts.append(f"{ch}:{ur:.3f}")
        if _ch_parts:
            _ls = getattr(entity, "loneliness_surface", 0)
            _lc = getattr(entity, "loneliness_core", 0)
            _ax = getattr(entity, "anxiety", 0)
            _sd = getattr(entity, "sadness", 0)
            _ag = getattr(entity, "anger", 0)
            logger.info(
                f"[Quench] t={entity.tick} channels=[{', '.join(_ch_parts)}] "
                f"lone={entity.loneliness:.3f}(s={_ls:.3f}/c={_lc:.3f}) "
                f"emo:anx={_ax:.3f} sad={_sd:.3f} ang={_ag:.3f}"
            )
    except Exception as e:
        _trace("quenching_system", False, {}, str(e))

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
        from ..memory_retrieval.summary import generate_turn_summary
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
            # 用回写后消力前 vs 消力后的值（纯消力效果，排除回写和问题张力）
            quench_before = _ur_before_quench if _ur_before_quench is not None else before_unresolved
            quench_after = _ur_after_quench if _ur_after_quench is not None else float(getattr(entity, "unresolved", 0.0))
            if debug:
                print(f"  [L3b DEBUG] before={quench_before:.3f} after={quench_after:.3f} delta={quench_before-quench_after:.3f}")
                print(f"  [L3b DEBUG] _quenching id={id(_quenching)} history={len(_quenching._history)} type={type(_quenching).__name__}")
            real_efficiency = _semantic_analyzer.verify_quenching(
                _lang_expression,
                quench_before,
                quench_after,
                snapshot,
            )
            if debug:
                print(f"  [L3b pre-record] hist={len(_quenching._history)}")
            _quenching.record(
                drive_state=dict(_lang_before_state),
                expression=_lang_expression,
                delta_unresolved_before=quench_before,
                delta_unresolved_after=quench_after,
                tick=entity.tick,
                template_idx=getattr(entity, "_last_template_idx", -1),
            )
            # v11.2: 同时记录个体词（拆分组合词），供词热身系统追踪
            # 每个组成词单独记一条，效率 ≈ 组合效率 × 0.8（保守归因）
            _comps = getattr(entity, "_training_components", [])
            for _comp in _comps:
                if _comp and _comp != _lang_expression and len(_comp) <= 8:
                    _comp_after = quench_before - (quench_before - quench_after) * 0.8
                    _quenching.record(
                        drive_state=dict(_lang_before_state),
                        expression=_comp,
                        delta_unresolved_before=quench_before,
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

            # ---- 模板权重学习 + 进化（L3b 路径）----
            try:
                from ..language_system import template_learner
                _eff_l3b = max(0.0, quench_before - quench_after)
                _lw = getattr(entity, "_template_learned_weights", {})
                template_learner.update_weights(
                    getattr(entity, "_last_template_idx", -1),
                    dict(_lang_before_state), _eff_l3b, _lw,
                )
                entity._template_learned_weights = _lw
            except Exception:
                pass

            # ---- v11.3 长词->聚类权重：3+字词修正体感概念地图锚点影响力 ----
            # 长词不产生热身变体，但用于调秤：效率高的长词所属的聚类获得权重，
            # 后续体感匹配时该聚类更受重视。短词造砖，长词调秤。
            if len(_lang_expression) > 2 and real_efficiency > 0.10:
                try:
                    from ..language_system.somatic_concept_map import find_closest_anchor
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
                "before_unresolved": round(quench_before, 4),
                "after_unresolved": round(quench_after, 4),
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

    # ---- 涌现观测日志（每 tick 一行 JSONL）----
    try:
        _cxg = getattr(entity, "_cxg_learner", None)
        _asw = getattr(entity, "_approach_synthesis_weights", {})
        _cft = getattr(entity, "_chronic_feedback_tracker", {})
        _expr = output_expression if output_expression else str(getattr(entity, "_language_best_candidate", "") or "")
        _expr_score = float(getattr(entity, "_language_best_score", 0.0))
        _obs = {
            "t": entity.tick,
            "ts": round(time.time()),
            "ur": round(entity.unresolved, 4),
            "ig": round(entity.info_gap, 4),
            "ft": round(entity.fatigue, 4),
            "en": round(entity.energy, 4),
            "ln": round(entity.loneliness, 4),
            "bd": round(entity.boredom, 4),
            "st": round(entity.stress, 4),
            "ap": round(entity.approach_drive, 4),
            "av": round(entity.avoid_drive, 4),
            "cur": round(getattr(entity, "curiosity", 0.5), 4),
            "asw": {k: round(v, 4) for k, v in _asw.items()},
            "cft": {k: round(v, 4) for k, v in _cft.items()},
            "cxg_n": _cxg.construction_count if _cxg else 0,
            "cxg_inst": len(_cxg._instances) if _cxg else 0,
            "cxg_max": round(max((cx.strength for cx in _cxg._constructions.values()), default=0.0), 4) if _cxg else 0,
            "vocab": len(getattr(entity, "_unlocked_vocabulary", [])),
            "warm": len(getattr(entity, "_warm_words", {})),
            "expr": _expr[:20] if _expr else "",
            "expr_s": round(_expr_score, 4),
            "input": str(raw_input)[:30] if raw_input else "",
            "ms": total_ms,
        }
        _log_path = Path(__file__).parent.parent.parent / "logs" / "emergence.jsonl"
        with open(_log_path, "a", encoding="utf-8") as _f:
            _f.write(json.dumps(_obs, ensure_ascii=False) + "\n")
    except Exception:
        pass

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
# 子模块导入（原文件中的独立函数已拆分到子模块）
# ============================================================================

# 异步管线
from .async_pipeline import (
    process_async_updates,
    trigger_sleep_if_needed as _trigger_sleep_async,
    run_world_model_update_cycle_async,
)

# 独立工具函数
from .utils import (
    should_trigger_sleep,
    _update_behavior_rules,
    _compute_snapshot_diversity,
    get_default_drive_params,
    _build_decision_params,
    _build_output_params,
    mock_llm_callable,
)

# ============================================================================
# END OF MODULE — 以下代码已移至子模块
# ============================================================================
