"""Stage 04b — 感知模块 + 驱动重算 + 情绪计算 + 行为涌现（Steps 8.0–8.35）。

职责：perceive_all、approach_drive 合成、drive_vector 重算、Insula 二次调味、
      情绪内生计算、self_mapping、behavior emergence、prediction error、
      逐字段预测、记忆投影、镜像学习、dopamine_tone 更新。
输入：ctx.snapshot, ctx._snapshot_dict, ctx.wm_context, ctx._recalled_insights,
      ctx.drive_vector, ctx.drive_params, ctx.curiosity_baseline, ctx.info_hunger_baseline,
      ctx.semantic_packet_biased, ctx.concept_tags, ctx.thought_packet,
      ctx.somatic_signals, ctx.state_snapshot, ctx._particle_field, ctx._projection_ctrl,
      ctx._five_rights
输出：ctx.state_after_perceive, ctx.drive_state_fresh, ctx.drive_vector_final,
      ctx.somatic_signals_2, ctx.refined_tone, ctx._pred_err, ctx._computed_emotions,
      ctx.emergent, ctx.emergent_action, ctx.emergent_priority, ctx.emergent_tension,
      ctx.emergent_target, ctx.emergent_dom_state, ctx.emergent_suggested_tool,
      ctx.emergent_bv, ctx.emergent_frag_tone, ctx.prediction_error, ctx.matched_rules,
      ctx.decision_params, ctx._projection_ctrl (updated)
"""

import logging
import time
from typing import Any, Dict, List

from ...decision_system.decision_system import perceive_all as _perceive_all
from ...drive_system.drive_system import compute_drive_vector, apply_affect_multiplier
from ...memory_hub.insula_hub import compute_somatic_signals as _compute_somatic_signals
from ...emotion_system import compute_emotions
from ...core import emerge_behavior as _emerge_behavior
from ...entity_state import _make_core_wrapper
from ...parameter_system.access import get_param
from ..utils import _build_decision_params, _process_tool_gaps
from .s04b_self_mapping import run_self_mapping as _run_self_mapping

_DRIVE_WRITE_WHITELIST = frozenset({
    "energy", "loneliness", "loneliness_core", "loneliness_surface",
    "unresolved", "boredom", "fatigue", "stress", "relief_debt", "pain",
    "info_gap", "external_change_rate",
    "somatic_tone", "danger_level", "approach_drive", "avoid_drive",
    "approach_social", "approach_explore", "approach_urgency",
    "joy", "anger", "fear", "sadness", "disgust", "anxiety", "surprise",
    "curiosity", "serenity", "excitement",
})

logger = logging.getLogger(__name__)

# 受伤退缩（PLAN_integrity_pain_revival §3-D，bcyq 2026-05-30 批"这轮一起接上"）：
# 上一拍完整性伤害写下的行为偏置（均为负=退缩）在涌现前连续抑制对应的外向驱动力——
# 受伤时少向外伸手、少探索。偏置正比于 active_harm，harm 每拍按 HEAL_RATE 愈合 → 退缩
# 短暂、会自愈。注意：access_count 仍每拍单调增（s07a），退缩不减绑定，故不构成
# "学会回避调用以躲痛"的漏洞（§9 三道护栏之一）。
# v1 驱动力键名见 drive_vector_field._drives_from_v1。
_WITHDRAW_FLOOR = 0.4   # 抑制下限：最多压到原驱动力的 40%，绝不彻底封口（保留最低行动力）
_BIAS_TO_DRIVE = {
    "novelty_seeking_bias": ("curiosity", "info_hunger"),  # 求新↓ → 探索弱
    "expression_rate_bias": ("loneliness_drive",),         # 表达↓ → 向外伸手弱
    "input_trust_bias":     ("loneliness_drive",),         # 不信任输入 → 也收回向人靠拢
}


def run_stage(ctx, entity) -> None:
    _trace = ctx._trace
    snapshot = ctx.snapshot
    _snapshot_dict = ctx._snapshot_dict
    wm_context = ctx.wm_context
    _recalled_insights = ctx._recalled_insights
    drive_vector = ctx.drive_vector
    drive_params = ctx.drive_params
    curiosity_baseline = ctx.curiosity_baseline
    info_hunger_baseline = ctx.info_hunger_baseline
    semantic_packet_biased = ctx.semantic_packet_biased
    concept_tags = ctx.concept_tags
    thought_packet = ctx.thought_packet
    somatic_signals = ctx.somatic_signals
    state_snapshot = ctx.state_snapshot
    _particle_field = ctx._particle_field
    _projection_ctrl = ctx._projection_ctrl
    _five_rights = ctx._five_rights
    raw_input = ctx.raw_input

    # ---- Step 8: 九模块并行感知（v3 改造）----
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
        decision_params = {}
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

    # ---- Step 8.0: 感知后重算驱动力 ----
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
        _dopamine_tone = getattr(entity, "dopamine_tone", 0.5)
        _oxytocin_tone = getattr(entity, "oxytocin_tone", 0.5)
        drive_vector_final = apply_affect_multiplier(drive_vector_final, _dopamine_tone, _oxytocin_tone)
        _trace("drive_recomputed", True, drive_vector_final)
    except Exception as e:
        drive_vector_final = drive_vector
        state_after_perceive = {}
        drive_state_fresh = {}
        _trace("drive_recomputed", False, {}, str(e))

    # ---- Step 8.05: Insula 二次调味 ----
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
        somatic_signals["refined_tone"] = refined_tone
        somatic_signals["channel_weights_2"] = somatic_signals_2.get("channel_weights", {})
        _trace("insula_re_seasoning", True, {
            "refined_tone": refined_tone,
            "dominant_feeling": somatic_signals_2.get("dominant_feeling"),
        })
    except Exception as e:
        somatic_signals_2 = {}
        refined_tone = 0.0
        _trace("insula_re_seasoning", False, {}, str(e))

    # ---- Step 8.05b: 情绪内生计算（v10.0/v11.0）----
    try:
        _pred_err = float(getattr(entity, "_last_prediction_error", 0.0))
        _computed_emotions = compute_emotions(
            entity_state=entity,
            drive_vector=drive_vector_final,
            somatic_tone=refined_tone,
            prediction_error=_pred_err,
            param_snapshot=_snapshot_dict,
        )
        _ema_alpha = 0.35
        for dim, val in _computed_emotions.items():
            if dim not in _DRIVE_WRITE_WHITELIST:
                continue
            if hasattr(entity, dim):
                old_val = float(getattr(entity, dim, 0.0))
                new_val = old_val * (1.0 - _ema_alpha) + val * _ema_alpha
                new_val = max(0.0, min(1.0, new_val))
                setattr(entity, dim, new_val)
        _trace("emotion_compute", True, {
            k: round(v, 3) for k, v in _computed_emotions.items() if v > 0.01
        })

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
        _pred_err = 0.0
        _computed_emotions = {}
        _trace("emotion_compute", False, {}, str(e))

    # ---- Step 8.2: 元认知感知（self_mapping，v1.0）----
    try:
        _narrative_record, _coherence_meta = _run_self_mapping(
            entity, state_snapshot, entity.wm_rules, _trace,
        )
    except Exception as e:
        _trace("self_mapping_sense", False, {}, str(e))
        entity._prev_self_narrative = None
        entity._coherence_meta = 0.5

    # ---- 受伤退缩：完整性伤害在涌现前连续抑制外向驱动力 ----
    try:
        _bias = getattr(entity, "integrity_behavior_bias", {}) or {}
        _suppress: Dict[str, float] = {}   # drive_key → 累积负偏置
        for _bkey, _drive_keys in _BIAS_TO_DRIVE.items():
            _bval = float(_bias.get(_bkey, 0.0))
            for _dk in _drive_keys:
                _suppress[_dk] = _suppress.get(_dk, 0.0) + _bval
        for _dk, _neg in _suppress.items():
            _factor = max(_WITHDRAW_FLOOR, min(1.0, 1.0 + _neg))
            drive_vector_final[_dk] = float(drive_vector_final.get(_dk, 0.0)) * _factor
        _trace("integrity_withdrawal", True, {
            "biases": {k: round(float(v), 4) for k, v in _bias.items()},
            "suppress": {k: round(v, 4) for k, v in _suppress.items()},
        })
    except Exception as e:
        _trace("integrity_withdrawal", False, {}, str(e))

    # ---- Step 8.1: 行为涌现（v3 改造）----
    try:
        emergent = _emerge_behavior(_make_core_wrapper(entity), drive_vector=drive_vector_final)
        emergent_action = emergent.action_type
        entity._current_action = emergent_action
        emergent_priority = emergent.priority
        emergent_tension = emergent.tension_level
        emergent_target = emergent.target
        emergent_dom_state = emergent.dominant_state
        emergent_suggested_tool = getattr(emergent, "suggested_tool", "")
        emergent_bv = getattr(emergent, "behavior_vector", {})
        emergent_frag_tone = getattr(emergent, "fragmentation_tone", "")
        _trace("emergence", True, {
            "action": emergent_action, "priority": emergent_priority,
            "tension": emergent_tension, "target": emergent_target,
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

    # ---- Step 8.2: 工具缺口感知 + 合成触发（v11.6）----
    try:
        pending_gaps = getattr(entity, "_pending_tool_gaps", [])
        if pending_gaps and emergent_action in ("repair", "explore", "seek"):
            _process_tool_gaps(entity, pending_gaps)
    except Exception as e:
        logger.debug(f"[ToolSynthesis] Gap processing error: {e}")

    # ---- Step 8.3: 预测误差注入 ----
    try:
        prediction_error = 0.0
        matched_rules = wm_context.get("matched_rules", [])
        if matched_rules:
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
            _ACTION_DIR = {
                "seek": 1.0, "explore": 0.8, "comfort": 0.3,
                "idle": 0.0, "rest": -0.5, "avoid": -1.0, "repair": 0.0,
            }
            _decision_dir = _ACTION_DIR.get(emergent_action, 0.0)
            _rule_dir_sum = sum(_ACTION_DIR.get(a, 0.0) for a in rule_action_types)
            _rule_dir = _rule_dir_sum / max(1, len(rule_action_types))
            _has_rules = min(1.0, float(len(rule_action_types)))
            prediction_error = -(_decision_dir * _rule_dir) * 0.5 * _has_rules
        entity._last_prediction_error = max(-1.0, min(1.0, prediction_error))
        _trace("prediction_error", True, {
            "prediction_error": prediction_error,
            "matched_rules_count": len(matched_rules),
        })
    except Exception as e:
        entity._last_prediction_error = 0.0
        prediction_error = 0.0
        matched_rules = []
        _trace("prediction_error", False, {}, str(e))

    # ---- Step 8.3b: 逐字段预测（v11.2）----
    try:
        from ...world_model_update.induct import predict_action_effects
        action_for_pred = emergent_action or ""
        entity_wm = getattr(entity, "wm_rules", [])
        if action_for_pred and entity_wm:
            entity._last_prediction = predict_action_effects(action_for_pred, state_snapshot, entity_wm)
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
    # [接入点 3] 记忆层投影检查
    # =========================================================================
    try:
        memory_context = {"matched_memories": wm_context.get("matched_memories", [])}
        current_state = entity.to_state_snapshot() if hasattr(entity, "to_state_snapshot") else dict(state_snapshot)
        memory_projection_result = _projection_ctrl.apply_memory_projection(
            memory_context, current_state, _particle_field, snapshot,
        )
        _trace("memory_projection", True, {
            "projection": memory_projection_result,
            "matched_memories_count": len(memory_context.get("matched_memories", [])),
        })
    except Exception as e:
        _trace("memory_projection", False, {}, str(e))

    # =========================================================================
    # [语言系统 L8] 镜像学习
    # =========================================================================
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
    try:
        _idle_for_dopamine = time.time() - entity.last_update_time
        from ...state_update.dopamine_tone import compute_dopamine_tone_delta
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

    # --- Outputs ---
    ctx.state_after_perceive = state_after_perceive
    ctx.drive_state_fresh = drive_state_fresh
    ctx.drive_vector_final = drive_vector_final
    ctx.somatic_signals = somatic_signals  # refined_tone 已注入
    ctx.somatic_signals_2 = somatic_signals_2
    ctx.refined_tone = refined_tone
    ctx._pred_err = _pred_err
    ctx._computed_emotions = _computed_emotions
    ctx.emergent = emergent
    ctx.emergent_action = emergent_action
    ctx.emergent_priority = emergent_priority
    ctx.emergent_tension = emergent_tension
    ctx.emergent_target = emergent_target
    ctx.emergent_dom_state = emergent_dom_state
    ctx.emergent_suggested_tool = emergent_suggested_tool
    ctx.emergent_bv = emergent_bv
    ctx.emergent_frag_tone = emergent_frag_tone
    ctx.prediction_error = prediction_error
    ctx.matched_rules = matched_rules
    ctx.decision_params = decision_params
    ctx._projection_ctrl = _projection_ctrl  # 已被 memory_projection 更新
    ctx.wm_context = wm_context  # insights 已注入
