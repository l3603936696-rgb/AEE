"""Stage 03 — 思考系统 + 情绪粒子初始化 + 情绪衰减。

职责：情绪粒子场恢复/初始化、受限思考、问题缓冲、情绪衰减、社交疲劳更新。
输入：ctx.snapshot, ctx._snapshot_dict, ctx.state_snapshot, ctx.drive_vector,
      ctx.somatic_signals, ctx.wm_context, ctx.concept_tags,
      ctx._decay_engine, ctx._five_rights, ctx._thermal
输出：ctx._particle_field, ctx._projection_ctrl, ctx.thought_packet,
      ctx._question_tension, ctx._ur_before_quench, ctx._ur_after_quench
"""

import logging
import time
from typing import Any, Dict, List

from ...thinking_system.thinking_system import think as thinking_think
from ...emotion_system import ParticleField, ProjectionController
from ...parameter_system.access import get_param

logger = logging.getLogger(__name__)


def run_stage(ctx, entity) -> None:
    _trace = ctx._trace
    snapshot = ctx.snapshot
    _snapshot_dict = ctx._snapshot_dict
    state_snapshot = ctx.state_snapshot
    drive_vector = ctx.drive_vector
    somatic_signals = ctx.somatic_signals
    wm_context = ctx.wm_context
    concept_tags = ctx.concept_tags
    _decay_engine = ctx._decay_engine
    _five_rights = ctx._five_rights
    _thermal = ctx._thermal

    # =========================================================================
    # [接入点 1] Step 6.5 后：初始化情绪粒子场 & 主线→日常投影
    # =========================================================================
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

        elapsed_since_last = max(0.0, time.time() - getattr(entity, "last_emotion_tick", time.time()))
        _particle_field.tick(elapsed_since_last)
        _projection_ctrl.tick(elapsed_since_last)

        dominant_feeling = somatic_signals.get("dominant_feeling", "")
        if dominant_feeling:
            _projection_ctrl.apply_mainline_to_daily(
                {dominant_feeling: abs(somatic_signals.get("tone", 0.0))},
                _particle_field,
                snapshot,
            )

        # 诚实奖励的身体后果（余韵通道）：consume_response / settle_epistemic_credit
        # 跑在 pipeline 外、够不着活粒子场，故把感受粒子排进 entity 队列，这里 drain 注入。
        _pending_feel = getattr(entity, "_pending_feeling_injections", None) or []
        for _f in list(_pending_feel):
            _particle_field.add_particle(
                _f.get("dimension", ""), _f.get("intensity", 0.0), _f.get("half_life")
            )
        if _pending_feel:
            _pending_feel.clear()
    except Exception as e:
        _particle_field = ParticleField()
        _projection_ctrl = ProjectionController()
        _trace("emotion_particle_init", False, {}, str(e))

    # ---- Step 7: 受限思考（v3 改造：接入 somatic_signals）----
    try:
        thinking_params = {
            # 激活阈值标定（2026-05-30）：think() 闸为 any(drive >= 阈值)。实测她对话期
            # drive_vector 峰值 ≈0.361（curiosity 主导，attention 调制后），idle 同量级 ~0.32。
            # 旧值 0.5 高于其整个工作带 → 思考门常年焊死 → 530+ 拍不生成新问题 →
            # 认知信用闭环上游断流。降到 0.33：对话投入态(0.36>0.33)开门思考、提问，
            # 完全静默态(<0.33)仍休息。连续化激活（去掉硬悬崖）列为后续。
            "thinking_activation_threshold": get_param(snapshot, "thresholds.thinking_activation_threshold", 0.33),
            "max_thinking_steps": get_param(snapshot, "thresholds.thinking_max_steps", 2),
            "thinking_timeout_ms": get_param(snapshot, "thresholds.thinking_timeout_ms", 2000),
            "thinking_time_budget_ms": get_param(snapshot, "thresholds.thinking_time_budget_ms", 500),
            "max_suggestions": get_param(snapshot, "thresholds.thinking_max_suggestions", 2),
            "very_low_confidence_threshold": get_param(snapshot, "thresholds.very_low_confidence_threshold", 0.4),
        }
        _attn_weights = getattr(entity, "_attention_weights", None)
        _input_context = getattr(ctx, "input_context", None)

        thought_packet = thinking_think(
            wm_context, drive_vector, state_snapshot, thinking_params,
            somatic_signals, entity_state=entity, concept_tags=concept_tags,
            attention_weights=_attn_weights,
            input_context=_input_context,
        )
        _trace("think", True, {"questions": len(thought_packet.get("questions", [])), "suggestions": len(thought_packet.get("suggestions", []))})
    except Exception as e:
        thought_packet = {"suggestions": [], "questions": []}
        _trace("think", False, thought_packet, str(e))

    # ---- Step 7.5: 问题缓冲（思考产出的结构化问题 → 暂存）----
    _question_tension = 0.0
    _ur_before_quench = None
    _ur_after_quench = None
    try:
        _questions = thought_packet.get("questions", [])
        if _questions:
            _top_q = max(_questions, key=lambda q: q.get("priority", 0.0))
            _q_priority = float(_top_q.get("priority", 0.0))
            _question_tension = _q_priority * 0.1
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
    # [接入点 2] Step 7 后：情绪衰减
    # =========================================================================
    try:
        elapsed_since_last = max(0.0, time.time() - getattr(entity, "last_emotion_tick", time.time()))
        decay_result = _decay_engine.tick_all(entity, elapsed_since_last, _snapshot_dict)
        _trace("emotion_decay", True, decay_result)
    except Exception as e:
        _trace("emotion_decay", False, {}, str(e))

    # =========================================================================
    # [语言系统 L7] Step 7 后：社交疲劳 + 自闭权
    # =========================================================================
    try:
        did_express_in_tick = bool(
            getattr(entity, "_last_action_result", {}).get("success") is not None
        )
        fatigue = _five_rights.tick_social_fatigue(did_express_in_tick, _snapshot_dict)
        is_self_close = _five_rights.activate_self_close(getattr(entity, "avoid_drive", 0.3), snapshot)
        adjusted_avoid = _five_rights.apply_fatigue_to_avoid(getattr(entity, "avoid_drive", 0.3))
        entity.avoid_drive = max(0.0, min(1.0, adjusted_avoid))
        _trace("language_social_init", True, {
            "social_fatigue": fatigue,
            "is_self_close": is_self_close,
            "adjusted_avoid": round(adjusted_avoid, 3),
        })
    except Exception as e:
        _trace("language_social_init", False, {}, str(e))

    # --- Outputs ---
    ctx._particle_field = _particle_field
    ctx._projection_ctrl = _projection_ctrl
    ctx.thought_packet = thought_packet
    ctx._question_tension = _question_tension
    ctx._ur_before_quench = _ur_before_quench
    ctx._ur_after_quench = _ur_after_quench
