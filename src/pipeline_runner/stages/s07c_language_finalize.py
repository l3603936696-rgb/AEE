"""Stage 07c — L5遗忘权 + L3b消力闭环 + L6语言持久化 + 实体持久化 + 返回值（语言系统收尾）。

职责：[语言系统 L5] 遗忘权标记、[语言系统 L3b] 消力闭环重录（精确 after_unresolved）、
      [语言系统 L6] 语言模块状态持久化、持久化实体内核、涌现观测日志写入、
      返回值 result_dict 组装。

输入：ctx._trace, ctx._snapshot_dict, ctx.before_unresolved,
      ctx._lang_before_state, ctx._lang_expression, ctx._quenching, ctx._strategy_map,
      ctx._thermal, ctx._mirror, ctx._five_rights, ctx.debug,
      ctx._semantic_analyzer, ctx._candidate_gen, ctx._behavior_profiler, ctx._decay_engine,
      ctx.output_expression, ctx.response, ctx.decision, ctx.intent_repr,
      ctx.semantic_packet_biased, ctx.concept_tags, ctx.wm_context,
      ctx.drive_vector_final, ctx.thought_packet, ctx.trace, ctx.dispatched_actions,
      ctx._cx_parse_result, ctx.raw_input, ctx.t0,
      ctx._ur_before_quench, ctx._ur_after_quench (from s07a),
      ctx._lone_surf_before, ctx._lone_surf_after_quench (from s07a),
      ctx._boredom_before, ctx._boredom_after_quench (from s07a)

输出：ctx.result_dict
"""

import json
import logging
import time
from pathlib import Path

from ..helpers import ENTITY_CORE_PATH
from ..utils import _update_behavior_rules

logger = logging.getLogger(__name__)


def run_stage(ctx, entity) -> None:  # noqa: C901
    _trace = ctx._trace
    _snapshot_dict = ctx._snapshot_dict
    before_unresolved = ctx.before_unresolved
    _lang_before_state = ctx._lang_before_state
    _lang_expression = ctx._lang_expression
    _quenching = ctx._quenching
    _strategy_map = ctx._strategy_map
    _thermal = ctx._thermal
    _mirror = ctx._mirror
    _five_rights = ctx._five_rights
    debug = ctx.debug
    _semantic_analyzer = ctx._semantic_analyzer
    _candidate_gen = ctx._candidate_gen
    _behavior_profiler = ctx._behavior_profiler
    _decay_engine = ctx._decay_engine
    output_expression = ctx.output_expression
    response = ctx.response
    decision = ctx.decision
    intent_repr = ctx.intent_repr
    semantic_packet_biased = ctx.semantic_packet_biased
    concept_tags = ctx.concept_tags
    wm_context = ctx.wm_context
    drive_vector_final = ctx.drive_vector_final
    thought_packet = ctx.thought_packet
    trace = ctx.trace
    dispatched_actions = ctx.dispatched_actions
    _cx_parse_result = ctx._cx_parse_result
    raw_input = ctx.raw_input
    t0 = ctx.t0
    # cross-stage quench vars from s07a
    _ur_before_quench = ctx._ur_before_quench
    _ur_after_quench = ctx._ur_after_quench
    _lone_surf_before = ctx._lone_surf_before
    _lone_surf_after_quench = ctx._lone_surf_after_quench
    _boredom_before = ctx._boredom_before
    _boredom_after_quench = ctx._boredom_after_quench

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
    # [刻板印象树] Step 11 后：从对话历史学习说话者特征
    # =========================================================================
    try:
        if raw_input and str(raw_input).strip():
            from ...language_system.stereotype_learner import quick_learn
            _src_id = "external"
            _text = str(raw_input)
            _emotion = float(semantic_packet_biased.get("emotion", 0.0)) if semantic_packet_biased else 0.0
            quick_learn(entity, _src_id, _text, _emotion)
            _trace("stereotype_learn", True, {"speaker": _src_id})
    except Exception as e:
        _trace("stereotype_learn", False, {}, str(e))

    # =========================================================================
    # [语言系统 L3b] Step 11 后：消力闭环重录（精确 after_unresolved）
    # =========================================================================
    try:
        if _lang_before_state is not None and _lang_expression:
            quench_before = _ur_before_quench if _ur_before_quench is not None else before_unresolved
            quench_after = _ur_after_quench if _ur_after_quench is not None else float(getattr(entity, "unresolved", 0.0))
            if debug:
                print(f"  [L3b DEBUG] before={quench_before:.3f} after={quench_after:.3f} delta={quench_before-quench_after:.3f}")
                print(f"  [L3b DEBUG] _quenching id={id(_quenching)} history={len(_quenching._history)} type={type(_quenching).__name__}")
            _QUENCH_EFF_WEIGHTS = {"loneliness_surface": 0.50, "boredom": 0.30, "unresolved": 0.20}
            _qe_before = {
                "loneliness_surface": _lone_surf_before       if _lone_surf_before       is not None else 0.0,
                "boredom":            _boredom_before         if _boredom_before         is not None else 0.0,
                "unresolved":         quench_before,
            }
            _qe_after = {
                "loneliness_surface": _lone_surf_after_quench if _lone_surf_after_quench is not None else _qe_before["loneliness_surface"],
                "boredom":            _boredom_after_quench   if _boredom_after_quench   is not None else _qe_before["boredom"],
                "unresolved":         quench_after,
            }
            _wdelta = sum(_QUENCH_EFF_WEIGHTS[k] * max(0.0, _qe_before[k] - _qe_after[k]) for k in _QUENCH_EFF_WEIGHTS)
            _wbase  = sum(_QUENCH_EFF_WEIGHTS[k] * _qe_before[k] for k in _QUENCH_EFF_WEIGHTS) + 1e-9
            real_efficiency = min(1.0, _wdelta / _wbase)
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
            # v11.2: 同时记录个体词
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

            # ---- 模板权重学习（L3b 路径）----
            try:
                from ...language_system import template_learner
                _eff_l3b = max(0.0, quench_before - quench_after)
                _lw = getattr(entity, "_template_learned_weights", {})
                template_learner.update_weights(
                    getattr(entity, "_last_template_idx", -1),
                    dict(_lang_before_state), _eff_l3b, _lw,
                )
                entity._template_learned_weights = _lw
            except Exception:
                pass

            # ---- v11.3 长词->聚类权重 ----
            if len(_lang_expression) > 2 and real_efficiency > 0.10:
                try:
                    from ...language_system.somatic_concept_map import find_closest_anchor
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

            try:
                entity.quenching_eff_rolling = (
                    0.95 * entity.quenching_eff_rolling + 0.05 * real_efficiency
                )
            except Exception:
                pass

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
    try:
        _update_behavior_rules(entity, decision)
        logger.info(f"[PersistDIAG] t={entity.tick} pre-persist core={entity.loneliness_core!r} surf={entity.loneliness_surface!r}")
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
        _log_path = Path(__file__).parent.parent.parent.parent / "logs" / "emergence.jsonl"
        with open(_log_path, "a", encoding="utf-8") as _f:
            _f.write(json.dumps(_obs, ensure_ascii=False) + "\n")
    except Exception:
        pass

    # --- Final return dict ---
    ctx.result_dict = {
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
        "cx_recognized_words": _cx_parse_result.get("recognized_words", []),
        "cx_comprehension": _cx_parse_result.get("comprehension", 0.0),
        "cx_social_intent": _cx_parse_result.get("social_intent", "unknown"),
    }
