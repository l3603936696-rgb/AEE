"""Stage 06b — Step 9 输出层（状态准备 + 调用锚点内核 + LLM 路径 + L3/L4）。

职责：[接入点 4] 输出调制、Step 9 三路输出（训练/锚点/LLM）、
      [语言系统 L3] 策略地图记录、L4 社交疲劳更新。

输入：ctx.snapshot, ctx._snapshot_dict, ctx.state_snapshot, ctx.entity_state,
      ctx.drive_vector_final, ctx.emergent, ctx.emergent_action,
      ctx.emergent_tension, ctx.decision, ctx.somatic_signals,
      ctx.semantic_packet_biased, ctx.thought_packet, ctx.raw_input,
      ctx._quenching, ctx._strategy_map, ctx._thermal, ctx._five_rights,
      ctx._semantic_analyzer, ctx._behavior_profiler, ctx._particle_field,
      ctx._projection_ctrl, ctx._cx_parse_result, ctx.daemon_mode,
      ctx.no_llm, ctx.llm_callable, ctx._question_tension,
      ctx.best_candidate (from s06a)

输出：ctx.response, ctx.output_expression, ctx.before_unresolved,
      ctx._lang_before_state, ctx._lang_expression,
      ctx.intent_repr, ctx.mainline_result, ctx.state_snapshot (updated),
      ctx._cx_parse_result
"""

import logging
import time
import bisect as _bisect_len
from typing import Any, Dict, List, Optional

from ...output_layer.output_layer import generate_response
from ..utils import _build_output_params
from .s06c_anchor_core import run_anchor_core

logger = logging.getLogger(__name__)


def run_stage(ctx, entity) -> None:  # noqa: C901
    _trace = ctx._trace
    snapshot = ctx.snapshot
    _snapshot_dict = ctx._snapshot_dict
    state_snapshot = ctx.state_snapshot
    drive_vector_final = ctx.drive_vector_final
    emergent = ctx.emergent
    emergent_action = ctx.emergent_action
    emergent_tension = ctx.emergent_tension
    decision = ctx.decision
    somatic_signals = ctx.somatic_signals
    semantic_packet_biased = ctx.semantic_packet_biased
    thought_packet = ctx.thought_packet
    _quenching = ctx._quenching
    _strategy_map = ctx._strategy_map
    _thermal = ctx._thermal
    _five_rights = ctx._five_rights
    _semantic_analyzer = ctx._semantic_analyzer
    _behavior_profiler = ctx._behavior_profiler
    _particle_field = ctx._particle_field
    _projection_ctrl = ctx._projection_ctrl
    _cx_parse_result = ctx._cx_parse_result
    raw_input = ctx.raw_input
    daemon_mode = ctx.daemon_mode
    no_llm = ctx.no_llm
    llm_callable = ctx.llm_callable
    best_candidate = ctx.best_candidate

    # ---- Step 9 状态准备 ----
    state_snapshot = entity.to_state_snapshot()
    if hasattr(entity, "_last_action_result"):
        state_snapshot["_last_action_result"] = entity._last_action_result

    if hasattr(entity, "_last_prediction") and entity._last_prediction:
        state_snapshot["_prediction_delta"] = entity._last_prediction
        for dim, delta in entity._last_prediction.items():
            if isinstance(delta, (int, float)) and abs(delta) > 1e-6:
                current = state_snapshot.get(dim, 0.0)
                predicted = max(0.0, min(1.0, current + delta))
                state_snapshot[f"{dim}_predicted"] = predicted
                state_snapshot[f"{dim}_rising"] = max(0.0, min(1.0, 0.5 + delta * 2.0))
    if hasattr(entity, "_last_prediction_error"):
        state_snapshot["_prediction_error"] = entity._last_prediction_error

    # [接入点 4] 日常层→主线层投影 + 输出调制
    _DRIVE_WRITE_WHITELIST = frozenset({
        "energy", "loneliness", "loneliness_core", "loneliness_surface",
        "unresolved", "boredom", "fatigue", "stress", "relief_debt", "pain",
        "info_gap", "external_change_rate",
        "somatic_tone", "danger_level", "approach_drive", "avoid_drive",
        "approach_social", "approach_explore", "approach_urgency",
        "joy", "anger", "fear", "sadness", "disgust", "anxiety", "surprise",
        "curiosity", "serenity", "excitement",
    })
    try:
        daily_influence = _projection_ctrl.apply_daily_to_mainline(_particle_field, _snapshot_dict)
        for dim, influence in daily_influence.items():
            if dim not in _DRIVE_WRITE_WHITELIST:
                continue
            if influence > 0.01 and hasattr(entity, dim):
                current = float(getattr(entity, dim, 0.0))
                setattr(entity, dim, min(1.0, current + influence))
    except Exception as e:
        _trace("daily_to_mainline", False, {}, str(e))

    try:
        flow_rate = _particle_field.compute_flow_modulation(_snapshot_dict)
        state_snapshot["_emotion_flow_rate"] = flow_rate
        state_snapshot["_particle_densities"] = _particle_field.get_all_densities()
    except Exception as e:
        state_snapshot["_emotion_flow_rate"] = 1.0
        state_snapshot["_particle_densities"] = {}
        _trace("flow_modulation", False, {}, str(e))

    emotion_flow = float(state_snapshot.get("_emotion_flow_rate", 1.0))
    language_flow = float(getattr(entity, "_language_flow_rate", 1.0))
    state_snapshot["_final_flow_rate"] = min(emotion_flow, language_flow)
    state_snapshot["_final_jitter"] = float(getattr(entity, "_language_jitter", 0.0))

    response: Dict = {"text": "", "confidence": 0.0, "generation_time_ms": 0}
    intent_repr: Dict = {
        "tone": "neutral",
        "goal": "share",
        "constraints": {"length": "tiny", "must_not": [], "reflect_state": False},
    }
    mainline_result = None

    if daemon_mode and getattr(entity, "_training_override", None):
        # 训练模式：语言系统已选出最佳候选，直接输出
        _train_text = entity._training_override
        try:
            from ...language_system.sentence_composer import (
                compose_sentence, _COMPOSE_TEMP_BASE, _COMPOSE_TEMP_BOREDOM_GAIN
            )
            _compose_temp_tr = _COMPOSE_TEMP_BASE + float(state_snapshot.get("boredom", 0.2)) * _COMPOSE_TEMP_BOREDOM_GAIN
            _composed, _tmpl_idx = compose_sentence(
                getattr(entity, '_language_best_candidate', '') or _train_text,
                state_snapshot,
                connector="",
                learned_weights=getattr(entity, "_template_learned_weights", None),
                extra_templates=getattr(entity, "_runtime_templates", None),
                temperature=_compose_temp_tr,
            )
            if _composed:
                _train_text = _composed
                entity._last_template_idx = _tmpl_idx
        except Exception:
            pass
        response = {"text": _train_text, "confidence": 0.90, "generation_time_ms": 0}
        _trace("output", True, {"mode": "training", "text": _train_text[:30]})

    elif daemon_mode or no_llm:
        # v11.5/v11.6: daemon/no_llm 全部走锚点表达
        # ---- 启动恢复 ----
        if not getattr(entity, "_recovery_done", False):
            try:
                from ...session_recovery import recover_learning_from_episodes
                recover_learning_from_episodes(entity)
            except Exception:
                pass
            try:
                from ...language_system import template_learner
                _tld = getattr(entity, "_template_learner_data", None)
                if _tld and isinstance(_tld, dict):
                    _lw, _rt, _sc = template_learner.from_dict(_tld)
                    entity._template_learned_weights = _lw
                    entity._runtime_templates = _rt
                    entity._spawn_counter = _sc
            except Exception:
                pass
            try:
                from ...language_system.construction_grammar import ConstructionLearner
                _cxg_data = getattr(entity, "_cxg_data", None)
                if _cxg_data and isinstance(_cxg_data, dict):
                    entity._cxg_learner = ConstructionLearner.from_dict(_cxg_data)
                else:
                    entity._cxg_learner = ConstructionLearner()
                entity._cxg_learner.ensure_seeds(entity.tick)
            except Exception:
                pass
            try:
                from ...language_system.recursive_construction import RecursiveGenerator
                _rcxg_data = getattr(entity, "_rcxg_data", None)
                if _rcxg_data and isinstance(_rcxg_data, dict):
                    entity._recursive_gen = RecursiveGenerator.from_dict(_rcxg_data)
                else:
                    entity._recursive_gen = RecursiveGenerator()
            except Exception:
                pass
            entity._recovery_done = True

        # ---- 醒来感知注入 ----
        _wakeup_msg = getattr(entity, "_pending_wakeup_message", None)
        _wakeup_narrative = None
        if _wakeup_msg:
            entity._pending_wakeup_message = None
            try:
                from ...language_system.narrative_fragments import try_narrative_expression
                _wakeup_narrative = try_narrative_expression(entity, wakeup_tag=_wakeup_msg)
                if _wakeup_narrative:
                    logger.info(f"[Wakeup] Generated wakeup narrative: {_wakeup_narrative[:60]}")
            except Exception as _w_err:
                logger.warning(f"[Wakeup] try_narrative_expression failed: {_w_err}")
        _narrative_text = None
        _social_signal = 1.0 if raw_input else 0.0
        try:
            from ...language_system.narrative_fragments import try_narrative_expression
            _narrative_text = try_narrative_expression(entity, social_input=_social_signal)
        except Exception as _narr_err:
            logger.warning(f"[Narrative] try_narrative_expression failed: {_narr_err}")

        _is_wakeup_tick = _wakeup_narrative is not None
        if _is_wakeup_tick:
            _narrative_text = _wakeup_narrative

        try:
            _anchor_result = run_anchor_core(
                entity,
                raw_input,
                _cx_parse_result,
                _narrative_text,
                _is_wakeup_tick,
                _trace,
            )
            response = {"text": _anchor_result["text"], "confidence": _anchor_result.get("best_score", 0.5), "anchor_weight": _anchor_result.get("anchor_display_w", 0.0), "generation_time_ms": 0}
        except Exception as e:
            logger.warning(f"[AnchorPath] t={entity.tick} error: {type(e).__name__}: {e}")
            if not _narrative_text:
                response = {"text": "", "confidence": 0.0, "generation_time_ms": 0}
                _trace("output", False, {}, str(e))

    else:
        # LLM 路径
        mainline_result = None
        try:
            from ...memory_retrieval.mainline import mainline_retrieval
            mainline_result = mainline_retrieval(
                semantic_packet_biased,
                current_iteration_id=entity.tick,
            )
        except Exception:
            mainline_result = None

        _shrink = entity.fatigue * 0.8 + max(0.0, 1.0 - entity.energy) * 0.5
        _expand = max(entity.boredom, entity.info_gap, entity.unresolved) * 0.8
        _length_signal = _expand - _shrink
        _LENGTH_LABELS = ("tiny", "short", "medium")
        _LENGTH_THRESHOLDS = [-0.2, 0.2]
        effective_length = _LENGTH_LABELS[_bisect_len.bisect_right(_LENGTH_THRESHOLDS, _length_signal)]
        _intent_repr_fallback = {
            "tone": "neutral",
            "goal": "share",
            "constraints": {"length": effective_length, "must_not": [], "reflect_state": False},
        }
        intent_repr = _intent_repr_fallback
        try:
            output_params = _build_output_params(snapshot)
            response = generate_response(
                state_snapshot=state_snapshot,
                semantic_packet_biased=semantic_packet_biased,
                params=output_params,
                llm_callable=llm_callable,
                emergent_behavior=emergent,
                somatic_signals=somatic_signals,
                intent_repr=_intent_repr_fallback,
                drive_vector=drive_vector_final,
                previous_state=entity.snapshots[-2] if len(entity.snapshots) >= 2 else None,
                entity_state=entity,
                mainline_result=mainline_result,
                thought_packet=thought_packet,
            )
            _trace("output", True, {"confidence": response.get("confidence"), "text_len": len(response.get("text", ""))})
        except Exception as e:
            response = {"text": "嗯。", "confidence": 0.0, "generation_time_ms": 0}
            _trace("output", False, response, str(e))

    # [语言系统 L3] 消力记录 + 策略地图 + 语义分析闭环
    _lang_before_state: Optional[Dict] = None
    _lang_expression: str = ""
    _lang_best_candidate: Optional[str] = None

    output_expression = response.get("text", "") if response else ""
    before_unresolved = float(getattr(entity, "unresolved", 0.0))
    _lang_best_cand = getattr(entity, "_language_best_candidate", None)
    if _lang_best_cand and output_expression:
        _lang_before_state = dict(state_snapshot) if state_snapshot else {}
        _lang_expression = output_expression
        _lang_best_candidate = best_candidate
        efficiency = _semantic_analyzer.verify_quenching(
            output_expression,
            before_unresolved,
            before_unresolved,
            snapshot,
        )
        context_label = f"tick_{entity.tick}"
        _strategy_map.record_path(
            state_A=dict(state_snapshot) if state_snapshot else {},
            state_B=entity.to_state_snapshot(),
            expression=output_expression,
            efficiency=efficiency,
            context_label=context_label,
            param_snapshot=_snapshot_dict,
        )
        try:
            wm_rules = getattr(entity, "wm_rules", None)
            if wm_rules is not None:
                upgraded = _strategy_map.check_generalization(wm_rules, _snapshot_dict)
                if upgraded:
                    _trace("strategy_upgrade", True, {"upgraded": len(upgraded)})
        except Exception as e:
            _trace("strategy_upgrade", False, {}, str(e))

        if output_expression:
            _behavior_profiler.record_action(decision.get("action_type", ""), output_expression)

        _trace("language闭环", True, {
            "expression": output_expression[:30],
            "efficiency": efficiency,
            "temperature": _thermal.get_temperature(),
        })

    # [语言系统 L4] 社交疲劳 + 自闭权更新
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

    ctx.response = response
    ctx.output_expression = output_expression
    ctx.before_unresolved = before_unresolved
    ctx._lang_before_state = _lang_before_state
    ctx._lang_expression = _lang_expression
    ctx.intent_repr = intent_repr
    ctx.mainline_result = mainline_result
    ctx.state_snapshot = state_snapshot
    ctx._cx_parse_result = _cx_parse_result
