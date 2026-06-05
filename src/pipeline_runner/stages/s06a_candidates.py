"""Stage 06a — 语言候选生成 + Thermal 热控 + 碎片化 + 丰度检查（L2 部分）。

职责：[语言系统 L2] 候选词生成/打分/排序/热身/阻力场/选优、
      Thermal 热控更新、碎片化映射、语言丰度检查。

输入：ctx.snapshot, ctx._snapshot_dict, ctx.state_snapshot,
      ctx.emergent_frag_tone, ctx._quenching, ctx._semantic_analyzer,
      ctx._candidate_gen, ctx._behavior_profiler, ctx._thermal,
      ctx._particle_field, ctx._projection_ctrl,
      ctx.daemon_mode, ctx._question_tension

输出：ctx.best_candidate, ctx.best_score（写入 entity），
      ctx.scored_candidates（局部，不再需要跨阶段传递）
"""

import logging
import math as _d_math
import random as _d_rnd
import time
from typing import Any, Dict, List, Optional

from ...language_system import FiveRightsController

_DOMINANT_WORD_BLACKLIST = frozenset({"的", "了", "在", "是", "我", "你", "他", "她", "它", "和", "就", "都", "而", "及", "与", "着"})

logger = logging.getLogger(__name__)


def _make_fallback_candidates(state: Dict) -> List[str]:
    """根据驱动力场从体感词典中抽取最相关候选词（v3.2）。"""
    candidates = []
    try:
        from ...language_system.somatic_dictionary import get_words_matching_state
        matches = get_words_matching_state(state, top_k=8, min_similarity=0.15)
        if matches:
            candidates = [w for w, _, _ in matches]
        return candidates[:16]
    except Exception:
        pass
    import bisect as _bisect
    avoid = float(state.get("avoid_drive", state.get("avoid", 0.3)))
    _AVOID_THRESHOLDS = [0.5, 0.7]
    _FALLBACK_TIERS = [
        ["嗯", "哦", "好"],
        ["嗯", "哦", "不知道", "也许"],
        ["嗯", "……", "不知道", "算了"],
    ]
    return _FALLBACK_TIERS[_bisect.bisect_right(_AVOID_THRESHOLDS, avoid)]


def run_stage(ctx, entity) -> None:  # noqa: C901
    _trace = ctx._trace
    snapshot = ctx.snapshot
    _snapshot_dict = ctx._snapshot_dict
    state_snapshot = ctx.state_snapshot
    emergent_frag_tone = ctx.emergent_frag_tone
    _quenching = ctx._quenching
    _semantic_analyzer = ctx._semantic_analyzer
    _candidate_gen = ctx._candidate_gen
    _behavior_profiler = ctx._behavior_profiler
    _thermal = ctx._thermal
    _particle_field = ctx._particle_field
    _projection_ctrl = ctx._projection_ctrl
    daemon_mode = ctx.daemon_mode
    _question_tension = ctx._question_tension

    best_candidate: Optional[str] = None
    best_score: float = 0.0
    scored_candidates: List = []
    _training_mode = False
    _training_threshold = 0.001
    _training_components: List = []
    _unique: List = []

    try:
        context_label = f"tick_{entity.tick}"
        scored_candidates = _candidate_gen.generate(state_snapshot, context_label, snapshot)

        _fallback = _make_fallback_candidates(state_snapshot)
        if _fallback:
            _fallback_scores = _semantic_analyzer.analyze(state_snapshot, _fallback, _snapshot_dict)
            _fallback_scored = list(zip(_fallback, _fallback_scores))
            scored_candidates = (scored_candidates or []) + _fallback_scored

        #体感锚点 top-N 注入
        try:
            from ...language_system.somatic_concept_map import get_top_matches
            _cw = getattr(entity, "_cluster_weights", {})
            _top_somatic = get_top_matches(state_snapshot, top_k=3, min_score=0.2, cluster_weights=_cw)
            if _top_somatic:
                _somatic_scored = [(w, s * 0.85) for w, s in _top_somatic]
                scored_candidates = (scored_candidates or []) + _somatic_scored
                _best_somatic_word, _best_somatic_score = _top_somatic[0]
                if _best_somatic_score > 0.7:
                    from ...language_system.somatic_concept_map import get_cluster_peers
                    _peers = get_cluster_peers(_best_somatic_word, min_similarity=0.5)
                    for _peer in _peers[:3]:
                        if _peer not in [c for c, _ in scored_candidates]:
                            scored_candidates.append((_peer, _best_somatic_score * 0.75))
        except Exception:
            pass

        #体感自我觉察注入（"我感到X"元觉察候选）
        try:
            from ...language_system.somatic_self_awareness import get_self_awareness_exprs
            _self_awareness_exprs = get_self_awareness_exprs(state_snapshot, entity, top_k=2)
            if _self_awareness_exprs:
                _existing_words = {c[0] for c, _ in scored_candidates}
                _sa_injected = 0
                for _sa_expr in _self_awareness_exprs:
                    if _sa_expr not in _existing_words:
                        _sa_score = 0.55
                        scored_candidates.append((_sa_expr, _sa_score))
                        _existing_words.add(_sa_expr)
                        _sa_injected += 1
                if _sa_injected > 0:
                    logger.info(
                        f"[SelfAwareness] {_sa_injected} meta-awareness exprs injected: {_self_awareness_exprs}"
                    )
        except Exception as _sa_err:
            logger.debug(f"[SelfAwareness] injection failed: {_sa_err}")

        #去重并按分排序
        seen = set()
        _unique = []
        for c, s in sorted(scored_candidates, key=lambda x: x[1], reverse=True):
            if c not in seen:
                seen.add(c)
                _unique.append((c, s))
        scored_candidates = _unique

        #词汇热身：已验证的单字词 → 短句变体
        try:
            from ...language_system.word_warmup import inject_warmup_candidates
            scored_candidates = inject_warmup_candidates(
                entity, scored_candidates,
                min_hits=3, min_best_efficiency=0.15,
            )
        except Exception:
            pass

        #v11.3 微小探索扰动
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
                    _boosted.append((c, s + 0.03))
                else:
                    _boosted.append((c, s))
            scored_candidates = _boosted
        except Exception:
            pass

        #MetaCognitive 语言干预
        _quench_data = getattr(entity, "_quenching_data", None)
        _quench_records = _quench_data.get("records", []) if _quench_data else []
        if _quench_records:
            try:
                from ...language_system.meta_cognitive import get_language_intervention
                _intervention = get_language_intervention(_quench_records)
                if _intervention.get("deadlock_detected") or _intervention.get("exploration_boost", 0) > 0:
                    _penalty_words = _intervention.get("penalty_words", {})
                    _explore_boost = _intervention.get("exploration_boost", 0.0)
                    _adjusted = []
                    for c, s in scored_candidates:
                        if c in _penalty_words:
                            s = s * (1.0 - _penalty_words[c])
                        dom_word = _intervention.get("dominant_word", "")
                        if c != dom_word:
                            s = s + _explore_boost * (1.0 if c not in _penalty_words else 0.5)
                        _adjusted.append((c, max(0.0, s)))
                    scored_candidates = sorted(_adjusted, key=lambda x: x[1], reverse=True)
                    _trace("meta_cognitive_intervention", True, {
                        "deadlock": _intervention.get("deadlock_detected"),
                        "penalty": _penalty_words,
                        "boost": _explore_boost,
                        "new_top": scored_candidates[0][0] if scored_candidates else None,
                    })
            except Exception:
                pass

        #v11.1: 语言阻力场
        try:
            from ...language_system.language_resistance import apply_resistance, init as _init_resistance
            _init_resistance(resistance_weight=0.15)
            scored_candidates = apply_resistance(scored_candidates)
            if not scored_candidates or all(s < 0.01 for _, s in scored_candidates):
                scored_candidates = _unique
        except Exception:
            pass

        #阅读候选词试用注入（阻力之后）
        try:
            _taste_log = getattr(entity, "_reading_taste_log", None)
            if _taste_log:
                _existing_words = {c[0] for c, _ in scored_candidates}
                _reading_words_injected = 0
                _state = entity.to_state_snapshot() if hasattr(entity, "to_state_snapshot") else {}
                for _entry in _taste_log[-20:]:
                    for _rw in _entry.get("words", []):
                        if _rw not in _existing_words and len(_rw) <= 6:
                            _rw_score = 0.20
                            try:
                                from ...language_system.somatic_concept_map import get_state_match_score
                                _match = get_state_match_score(_rw, _state)
                                _rw_score = 0.20 + _match * 0.25
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

        # 前语言扰动：drive激活→内部符号共鸣→直接张力（不经过解释竞争）
        # 理解机制纲领第七节：语言前扰动完整闭环
        _spm_resonance = getattr(ctx, "_spm_resonance", None)
        _activated_drive = getattr(ctx, "_input_drive_map", {}).get("drive_vector", {})
        if _spm_resonance:
            try:
                from ...language_system.interpretation_competition import (
                    compute_prelinguistic_tension,
                    apply_prelinguistic_tension,
                )
                _pretension, _pretension_type = compute_prelinguistic_tension(
                    _spm_resonance, _activated_drive
                )
                if _pretension > 0.05:
                    scored_candidates = apply_prelinguistic_tension(
                        scored_candidates, _pretension, _pretension_type
                    )
                    _trace("prelinguistic_tension", True, {
                        "tension": round(_pretension, 3),
                        "type": _pretension_type,
                        "top3": [(c, round(s, 3)) for c, s in scored_candidates[:3]],
                    })
            except Exception:
                pass

        # 张力悬置调制（理解机制 → 语言输出，解释竞争来源）
        _tension = getattr(entity, "_last_tension_level", 0.0)
        _tension_type = "none"
        try:
            _ir = getattr(entity, "_last_interpretation_result", None)
            if _ir is not None:
                _tension_type = getattr(_ir, "tension_type", "none")
        except Exception:
            pass
        if _tension_type == "suspended" and _tension > 0.05:
            try:
                from ...language_system.interpretation_competition import apply_tension_to_candidates
                scored_candidates = apply_tension_to_candidates(
                    scored_candidates, _tension, _tension_type
                )
            except Exception:
                pass

        #选最佳候选（训练早期优先短词 ≤8字）
        if scored_candidates:
            _short_candidates = [(c, s) for c, s in scored_candidates if len(c) <= 8]
            if _short_candidates:
                best_candidate, best_score = max(_short_candidates, key=lambda x: x[1])
            else:
                best_candidate, best_score = scored_candidates[0]

        #v11.1: 低置信度双词回退
        _low_confidence = best_score < 0.30
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

        #存储到 entity
        entity._language_best_candidate = best_candidate
        entity._language_best_score = best_score
        entity._language_candidates = [c for c, _ in scored_candidates[:5]]
        entity._language_candidate_scores = {c: s for c, s in scored_candidates[:5]}

        _training_mode = (
            best_candidate is not None
            and best_score > _training_threshold
            and len(best_candidate) <= 8
            and not daemon_mode
        )
        if _training_mode:
            _display_word = best_candidate
            try:
                import random as _rnd
                from ...language_system.somatic_dictionary import SOMATIC_DICTIONARY
                _func_cats = ["actions", "degree", "time", "question", "logic"]
                _cat = _rnd.choice(_func_cats)
                _func_words = list(SOMATIC_DICTIONARY.get(_cat, {}).keys())
                if _func_words:
                    _fw = _rnd.choice(_func_words)
                    if _rnd.random() < 0.5:
                        _display_word = f"{_fw}{best_candidate}"
                    else:
                        _display_word = f"{best_candidate}{_fw}"
            except Exception:
                _display_word = best_candidate

            entity._training_override = _display_word
            entity._training_components = _training_components
            #体感诊断+帮助
            try:
                from ...language_system.somatic_concept_map import apply_help_delta, training_exploration_nudge
                from ...language_system.meta_cognitive import apply_meta_cognitive
                help_result = apply_help_delta(
                    best_candidate, entity, state_snapshot,
                    min_match=0.30,
                    help_scaling=0.40,
                )
                nudge_result = training_exploration_nudge(
                    entity, state_snapshot,
                    stuck_threshold=0.35,
                    nudge_strength=0.03,
                )
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
            entity._language_best_long = best_candidate
        _trace("language_candidates", True, {
            "best": best_candidate,
            "score": best_score,
            "count": len(scored_candidates),
            "training_mode": _training_mode,
        })
    except Exception as e:
        _trace("language_candidates", False, {}, str(e))

    #热控更新（基于当前 energy）
    try:
        _thermal.tick(entity.energy, _snapshot_dict)
        _trace("thermal_tick", True, {"temperature": _thermal.get_temperature()})
    except Exception as e:
        _trace("thermal_tick", False, {}, str(e))

    #物理重力：fragmentation 映射为输出参数
    try:
        fragmentation = float(emergent_frag_tone) if emergent_frag_tone else 0.0
        frag_render = FiveRightsController.get_fragmentation_render(fragmentation)
        entity._language_flow_rate = frag_render["flow_rate"]
        entity._language_jitter = frag_render["jitter"]
    except Exception:
        pass

    #语言丰度检查 + 热控升温
    try:
        heated = _behavior_profiler.check丰度_and_notify(_thermal, _snapshot_dict)
        丰度_stats = _behavior_profiler.get丰度_stats()
        _trace("language丰度", True, 丰度_stats)
    except Exception as e:
        _trace("language丰度", False, {}, str(e))

    #持久化候选结果到 ctx（供 s06b 读取）
    ctx.best_candidate = best_candidate
    ctx.best_score = best_score
    ctx.scored_candidates = scored_candidates
