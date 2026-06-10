"""Stage 07b — 经验快照 + 记忆 + Episode写入 + 交互时间戳（Steps 12–15b）。

职责：Step 12 经验快照记录、Step 13 记忆样本记录、Step 14 清空联网搜索池、
      Step 15 episode 异步写入 + [接入点5] InsightWriter + [接入点6] 情绪粒子场持久化
      + connection_episode + Step 15b UNRESOLVABLE episode + 交互时间戳更新。

输入：ctx._trace, ctx._snapshot_dict, ctx.state_snapshot,
      ctx.somatic_tone_start, ctx.emergent_tension, ctx.connection_depth_eff,
      ctx.decision, ctx.drive_vector_final, ctx.concept_tags, ctx.dispatched_actions,
      ctx.semantic_packet_biased, ctx.raw_input, ctx.response, ctx.intent_repr,
      ctx.wm_context, ctx._particle_field, ctx._projection_ctrl,
      ctx.connection_signature, ctx.loneliness_target,
      ctx._state_for_update (from s07a), ctx._unresolvable_episodes (from s07a)
"""

import logging
import time

from ...memory_hub import build_episode, write_episode_async
from ...emotion_system import InsightWriter
from ..helpers import _compute_prediction_error_map

logger = logging.getLogger(__name__)


def run_stage(ctx, entity) -> None:  # noqa: C901
    _trace = ctx._trace
    _snapshot_dict = ctx._snapshot_dict
    state_snapshot = ctx.state_snapshot
    somatic_tone_start = ctx.somatic_tone_start
    emergent_tension = ctx.emergent_tension
    connection_depth_eff = ctx.connection_depth_eff
    decision = ctx.decision
    drive_vector_final = ctx.drive_vector_final
    concept_tags = ctx.concept_tags
    dispatched_actions = ctx.dispatched_actions
    semantic_packet_biased = ctx.semantic_packet_biased
    raw_input = ctx.raw_input
    response = ctx.response
    intent_repr = ctx.intent_repr
    wm_context = ctx.wm_context
    _particle_field = ctx._particle_field
    _projection_ctrl = ctx._projection_ctrl
    connection_signature = ctx.connection_signature
    loneliness_target = ctx.loneliness_target
    # cross-stage from s07a
    state_for_update = ctx._state_for_update
    unresolvable_episodes = ctx._unresolvable_episodes

    # ---- Step 12: 经验快照记录 ----
    identity_signal = getattr(entity, "_bp_identity", 0.5)
    unresolved_src = getattr(entity, "_bp_unresolved_src", "external")
    # ②a：有 raw_input 时给快照标输入主题（input_class），供 induct_input 旁路归纳
    #      「输入→后果」规则；空输入（daemon 自主拍）classify 返回 ""，零影响 action 路径。
    from ...world_model_update.input_theme import classify_input
    input_class = classify_input(entity, raw_input or "")
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
        "input_class": input_class,
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
    try:
        from ...decision_system.submodules.web_search import clear_pending_searches
        clear_pending_searches()
    except Exception:
        pass

    # ---- Step 15: 写入原始事件日志（异步，不阻塞）----
    idle_seconds = time.time() - entity.last_update_time

    try:
        from ...memory_retrieval.summary import generate_turn_summary
        turn_summary = generate_turn_summary(
            raw_input=raw_input,
            output_text=response.get("text", ""),
            intent=semantic_packet_biased.get("intent", ""),
        )
    except Exception:
        turn_summary = ""

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
        summary=turn_summary,
    )

    # =========================================================================
    # [接入点 5] Step 11 后（记忆固化前）：高冲击惊讶写入 Insights
    # =========================================================================
    try:
        _insight_writer = InsightWriter()
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
        entity.last_emotion_tick = time.time()
        entity.emotion_particle_field = _particle_field.to_dict()
        entity.emotion_accumulators = {
            "_projection_controller": _projection_ctrl.to_dict(),
        }
    except Exception as e:
        _trace("emotion_persist", False, {}, str(e))

    # ---- Step 15: 记录 connection_episode ----
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
                summary="",
            )
            write_episode_async(unres_episode)
        except Exception:
            pass

    # ---- 更新最后交互时间戳 ----
    if raw_input and str(raw_input).strip():
        entity.last_interaction_timestamp = time.time()
        entity.last_interaction_context = {
            "emotion": float(semantic_packet_biased.get("emotion", 0.0)),
            "intensity": float(semantic_packet_biased.get("intensity", 0.0)),
            "action_type": str(decision.get("action_type", "comfort")),
        }
