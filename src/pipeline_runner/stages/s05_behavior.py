"""Stage 05 — 连接深度 + 孤独更新 + 行为进化 + 动作派发（Steps 8.4–8.6）。

职责：somatic_tone_delta 计算、connection_depth、loneliness 双通道、催产素更新、
      观测层采集、行为模式选择与执行、反馈闭环、decision dict 装配。
输入：ctx.snapshot, ctx._snapshot_dict, ctx.somatic_tone_start, ctx.state_snapshot,
      ctx.emergent, ctx.emergent_action/priority/tension/target/dom_state/suggested_tool/bv/frag_tone,
      ctx.drive_vector_final, ctx.wm_context, ctx.semantic_packet_biased,
      ctx.concept_tags, ctx.thought_packet,
      ctx._candidate_gen, ctx._semantic_analyzer, ctx._quenching, ctx._five_rights,
      ctx._behavior_profiler, ctx._thermal
输出：ctx.selected_candidate, ctx.dispatched_actions, ctx.all_results, ctx.all_action_results,
      ctx.connection_depth_eff, ctx.somatic_tone_end, ctx.somatic_tone_delta,
      ctx.connection_signature, ctx.connection_intermediates,
      ctx.loneliness_target, ctx.loneliness_intermediates,
      ctx.connection_trace, ctx.counterfactual_report,
      ctx.decision, ctx.thought_packet (updated)
"""

import logging
import time
from collections import deque
from typing import Any, Dict, List, Optional

from ...state_update.compute_connection import (
    compute_connection_depth_ex,
    compute_loneliness_target_ex,
)
from ...observation.behavior_trace import (
    build_connection_trace,
    build_loneliness_trace,
    compute_trend,
    compute_profile,
    _infer_loneliness_reason,
)
from ...observation.counterfactual_probe import run_counterfactual_probe
from ...observation.probe_logger import get_probe_logger
from ...core.action_dispatcher import (
    dispatch_async_action as _dispatch_async_action,
    select_primitive_candidate as _select_primitive_candidate,
)
from ...decision_system.submodules.web_search import drain_pending_searches
from ...parameter_system.access import get_param

logger = logging.getLogger(__name__)


def run_stage(ctx, entity) -> None:
    _trace = ctx._trace
    snapshot = ctx.snapshot
    _snapshot_dict = ctx._snapshot_dict
    somatic_tone_start = ctx.somatic_tone_start
    emergent = ctx.emergent
    emergent_action = ctx.emergent_action
    emergent_priority = ctx.emergent_priority
    emergent_tension = ctx.emergent_tension
    emergent_target = ctx.emergent_target
    emergent_dom_state = ctx.emergent_dom_state
    emergent_suggested_tool = ctx.emergent_suggested_tool
    emergent_bv = ctx.emergent_bv
    emergent_frag_tone = ctx.emergent_frag_tone
    drive_vector_final = ctx.drive_vector_final
    wm_context = ctx.wm_context
    semantic_packet_biased = ctx.semantic_packet_biased
    concept_tags = ctx.concept_tags
    thought_packet = ctx.thought_packet
    decision = ctx.decision  # initial {}
    raw_input = ctx.raw_input

    # ---- Step 8.4: connection_depth 计算（v3.0 + v3.5a/b/c）----
    try:
        somatic_tone_end = float(getattr(entity, "somatic_tone", 0.0))
        somatic_tone_delta = somatic_tone_end - somatic_tone_start

        recent_deltas = getattr(entity, "recent_deltas", None)
        if recent_deltas is None:
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
        somatic_tone_end = float(getattr(entity, "somatic_tone", 0.0))
        somatic_tone_delta = somatic_tone_end - somatic_tone_start
        connection_depth_eff = 0.5
        connection_signature = {"prediction": 0.5, "somatic": 0.0, "tension": 0.5}
        connection_intermediates = {}
        _trace("connection_depth", False, {}, str(e))

    # ---- Step 8.4b: loneliness 双通道更新 ----
    has_social_input = bool(raw_input and str(raw_input).strip())
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
            "loneliness_core": round(loneliness_core_target, 4),
            "loneliness_surface": round(loneliness_surface_target, 4),
        })
        if loneliness_intermediates.get("rebound_triggered"):
            logger.warning(
                f"[Loneliness] REBOUND! core surged to {loneliness_core_target:.3f}, "
                f"surface refilled to {loneliness_surface_target:.3f} "
                f"(events: {loneliness_intermediates.get('events', [])})"
            )
        entity.loneliness_core = loneliness_core_target
        entity.loneliness_surface = loneliness_surface_target
        entity.loneliness = loneliness_target
        entity._sync_loneliness()
        logger.info(f"[Step8.4 DIAG] OK core={entity.loneliness_core:.4f} surf={entity.loneliness_surface:.4f}")
    except Exception as e:
        loneliness_target = None
        loneliness_intermediates = {}
        _trace("loneliness_update", False, {}, str(e))
        logger.warning(f"[Step8.4 DIAG] loneliness update FAILED: {e!r}")

    # ---- Step 8.4c: 催产素基调更新（v11.x）----
    try:
        from ...state_update.oxytocin_signal import compute_oxytocin_tone_delta_ex
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

    # ---- Step 8.5: 观测层采集 ----
    connection_trace = {}
    counterfactual_report = {}
    try:
        if getattr(entity, "observation_buffer", None) is None:
            buf_size = int(get_param(snapshot, "observation.buffer_size", 50))
            entity.observation_buffer = deque(maxlen=buf_size)

        connection_trace = build_connection_trace(
            tick=entity.tick,
            connection_depth_effective=connection_depth_eff,
            connection_signature=connection_signature,
            intermediates=connection_intermediates,
        )

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

        try:
            probe_logger = get_probe_logger()
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
            pass
    except Exception as e:
        _trace("observation_collect", False, {}, str(e))

    # ---- Step 8.2（前置）：联想召回 — 驱动力触发的记忆召回 ----
    # attempt_recall 返回 Optional[dict]，成功时有 "expression"/"benefit"/"topic" 等字段。
    # 召回结果注入 ctx，供后续语言候选层使用（直接输出回忆内容，而不触发新行动）。
    _recall_result = None
    try:
        from ...language_system.associative_recall import attempt_recall
        _recall_result = attempt_recall(
            entity=entity,
            action_type=emergent_action or "explore",
            drive_state=state_snapshot,
        )
        if _recall_result:
            entity._recall_counts = _recall_result.get("recall_counts", {})
            _trace("associative_recall", True, {
                "expression": _recall_result.get("expression"),
                "benefit": round(_recall_result.get("benefit", 0.0), 3),
                "topic": _recall_result.get("topic"),
            })
    except Exception as e:
        _trace("associative_recall", False, {}, str(e))

    # ---- Step 8.2: 行为进化层 — 从 pattern pool 选择最佳候选 ----
    selected_candidate = None
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
    all_results = []
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

    # ---- Step 8.5: 行为进化反馈闭环 ----
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
        _fail_signal = float(failure)
        _success_signal = float(success) * (1.0 - _fail_signal)
        short_reward = _success_signal * 1.5 - 0.5
        result_count = len(all_action_results)
        satisfaction = (
            0.5
            + min(result_count / 5.0, 0.3)
            - _fail_signal * 0.3
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
        entity._bp_identity = 0.5
        entity._bp_unresolved_src = "external"
        state_for_bp = entity.to_state_snapshot()
        try:
            from ...core import behavior_patterns as bp
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
                "candidate": candidate_name, "intent": intent, "drive": drive,
                "base": round(base_score, 3),
                "wm_reward": round(wm_pred["reward"], 3),
                "wm_uncertainty": round(wm_pred["uncertainty"], 3),
                "bias_bonus": round(bias_bonus, 4),
                "bias": dict(entity.long_term_bias),
            }
            entity._bp_identity = entity.update_behavior_signature(
                decision.get("action_type", "") or emergent_action
            )
            raw_input_str = str(raw_input or "").strip()
            entity._bp_unresolved_src = "external" if raw_input_str else "self_generated"
            enriched_result = dict(result_for_feedback)
            enriched_result["identity_signal"] = entity._bp_identity
            enriched_result["unresolved_source"] = entity._bp_unresolved_src
            bp.apply_result(selected_candidate, enriched_result, state_for_bp)
            bias_info = bp.update_long_term_bias(
                entity_state=entity,
                pattern_or_intent=selected_candidate,
                pre_state=pre_bp_state,
                post_state=state_for_bp,
                action_result=enriched_result,
            )
            if entity.tick % 20 == 0:
                removed = bp.get_pool().prune()
                if removed:
                    _trace("pattern_prune", True, {"removed": removed})
            _trace("pattern_feedback", True, {
                "candidate": candidate_name, "intent": intent,
                "success": success, "satisfaction": satisfaction,
                "short_reward": short_reward,
                "score_breakdown": score_breakdown,
                "bias_update": bias_info,
            })
        except Exception as e:
            _trace("pattern_feedback", False, {}, str(e))

    # Step 8.1 结果即为最终决策
    decision = {
        "action_type": emergent_action,
        "target": emergent_target,
        "priority": emergent_priority,
        "payload": {"source": "emergence", "dominant_state": emergent_dom_state},
        "tension_level": emergent_tension,
        "emergent_action": emergent_action,
        "suggested_tool": emergent_suggested_tool,
        "behavior_vector": emergent_bv,
        "fragmentation_tone": emergent_frag_tone,
    }

    # ---- anti_stuck：检测行为死循环，必要时覆写 decision ----
    try:
        from ...anti_stuck.anti_stuck import anti_stuck_check, DEFAULT_PARAMS as _AS_PARAMS
        # entity.snapshots 中每条包含 "decision" 字段，取出作为决策历史
        _snapshots = getattr(entity, "snapshots", [])
        _decision_hist = [s.get("decision", {}) for s in _snapshots[-20:] if isinstance(s, dict)]
        decision = anti_stuck_check(
            decision,
            _decision_hist,
            entity.to_state_snapshot(),
            params=_AS_PARAMS,
        )
        if decision.get("_overridden"):
            _trace("anti_stuck", True, {
                "original": decision.get("_original_action"),
                "new": decision.get("action_type"),
            })
    except Exception as e:
        _trace("anti_stuck", False, {}, str(e))

    # ---- Step 8.6: 收集联网搜索结果 ----
    thought_packet["web_search_results"] = []

    # --- Outputs ---
    ctx.selected_candidate = selected_candidate
    ctx.dispatched_actions = dispatched_actions
    ctx.all_results = all_results
    ctx.all_action_results = all_action_results
    ctx.connection_depth_eff = connection_depth_eff
    ctx.somatic_tone_end = somatic_tone_end
    ctx.somatic_tone_delta = somatic_tone_delta
    ctx.connection_signature = connection_signature
    ctx.connection_intermediates = connection_intermediates
    ctx.loneliness_target = loneliness_target
    ctx.loneliness_intermediates = loneliness_intermediates
    ctx.connection_trace = connection_trace
    ctx.counterfactual_report = counterfactual_report
    ctx.recall_result = _recall_result  # 联想召回结果，供 s06a_candidates 使用
    ctx.decision = decision
    ctx.thought_packet = thought_packet
