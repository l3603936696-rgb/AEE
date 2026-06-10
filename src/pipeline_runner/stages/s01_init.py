"""Stage 01 — 参数快照 + 语言模块初始化。

职责：创建本轮参数快照、冻结状态快照、惰性恢复/创建所有语言系统模块实例。
输入：entity（全局单例）
输出：ctx.snapshot, ctx._snapshot_dict, ctx.somatic_tone_start, ctx.state_snapshot,
      ctx._quenching, ctx._strategy_map, ctx._thermal, ctx._mirror, ctx._five_rights,
      ctx._semantic_analyzer, ctx._candidate_gen, ctx._behavior_profiler, ctx._decay_engine
"""

import logging
from typing import Any, Dict, List

from ...parameter_system.access import create_snapshot, get_param
from ...language_system import (
    QuenchingTracker, StrategyMap, ThermalController, MirrorLearner,
    FiveRightsController, SemanticAnalyzer, CandidateGenerator,
)
from ...behavior_profiler import BehaviorProfiler
from ...emotion_system import DecayEngine
from ..helpers import SnapshotDictWrapper

logger = logging.getLogger(__name__)


def run_stage(ctx, entity) -> None:
    _trace = ctx._trace
    params_override = ctx.params_override

    # ---- Step 0: 创建参数快照（每个 Tick 一次）----
    snapshot = create_snapshot(overrides=params_override)
    _trace("create_snapshot", True)

    # ---- Step 0a: 转换为 dict（供语言/情绪系统模块使用）----
    _snapshot_dict = SnapshotDictWrapper(snapshot)

    # ---- Step 0b: 记录 somatic_tone_start（供 Step 8.4 somatic_tone_delta 计算）----
    somatic_tone_start = float(getattr(entity, "somatic_tone", 0.0))

    # ---- Step 1: 冻结状态快照（所有模块共享的只读视图）----
    state_snapshot = entity.to_state_snapshot()
    _trace("freeze_state", True, {"energy": state_snapshot.get("energy"), "fatigue": state_snapshot.get("fatigue")})

    # =========================================================================
    # [语言系统 L1] Step 1 后、Step 2（感性认识）前：初始化 + 顶撞权检查
    # =========================================================================
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
        try:
            from ...language_system.bge_analyzer import SemanticAnalyzerV2
            _semantic_analyzer = SemanticAnalyzerV2()
            logger.info("[s01_init] Using BGE SemanticAnalyzerV2")
        except Exception:
            _semantic_analyzer = SemanticAnalyzer()
            logger.info("[s01_init] BGE unavailable, using LLM SemanticAnalyzer")
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
            from ...language_system.seed_map import seed_strategy_map
            seeded = seed_strategy_map(_strategy_map, _quenching)
            logger.info(f"[s01_init] 策略地图播种: {seeded} 条初始锚点")
            _trace("seed_map", True, {"entries": seeded})
        except Exception as e:
            _trace("seed_map", False, {}, str(e))

    if _thermal is None:
        _thermal = ThermalController()
    if _mirror is None:
        _mirror = MirrorLearner(bias_strength=float(get_param(snapshot, "language.mirror.bias_strength", 0.40)))
    if _five_rights is None:
        _five_rights = FiveRightsController()

    # 初始化 _warm_words（word_warmup.py 依赖此属性；重启后从 persistence 恢复）
    if getattr(entity, "_warm_words", None) is None:
        entity._warm_words = {}

    # 绑定各模块之间的依赖关系
    _five_rights.set_mirror(_mirror)
    _candidate_gen.bind_strategy_map(_strategy_map)
    _candidate_gen.bind_thermal(_thermal)
    _candidate_gen.bind_semantic_analyzer(_semantic_analyzer)
    _candidate_gen.bind_five_rights(_five_rights)

    # --- Outputs ---
    ctx.snapshot = snapshot
    ctx._snapshot_dict = _snapshot_dict
    ctx.somatic_tone_start = somatic_tone_start
    ctx.state_snapshot = state_snapshot
    ctx._quenching = _quenching
    ctx._strategy_map = _strategy_map
    ctx._thermal = _thermal
    ctx._mirror = _mirror
    ctx._five_rights = _five_rights
    ctx._semantic_analyzer = _semantic_analyzer
    ctx._candidate_gen = _candidate_gen
    ctx._behavior_profiler = _behavior_profiler
    ctx._decay_engine = _decay_engine
