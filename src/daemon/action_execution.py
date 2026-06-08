"""Action-trigger execution helpers for daemon ticks."""

from __future__ import annotations

import time

from ..action_system import evaluate_triggers, execute_xia_choice
from ..action_system.types import XIAction
from ..daemon.autonomous_action_memory import record_autonomous_action
from ..daemon.sibling_tick import post_sibling_anchor

TOOL_ACTION_TYPES = {"repair", "write"}
TRAINING_TEXT_MAX_LENGTH = 20
ACTION_RESULT_PREVIEW_LENGTH = 100


def run_action_execution(entity, result: dict, sibling_channel, llm_callable, logger) -> tuple[dict, bool, str]:
    """Bridge pipeline decisions into daemon-triggered actions."""
    action_triggered = False
    action_result = ""
    decision = result.get("decision", {})
    emergent_behavior_dict = {
        "action_type": decision.get("action_type", "idle"),
        "priority": decision.get("priority", 0.0),
        "tension_level": decision.get("tension_level", 0.0),
        "dominant_state": decision.get("payload", {}).get("dominant_state", ""),
        "suggested_tool": decision.get("suggested_tool", ""),
        "behavior_vector": decision.get("behavior_vector", {}),
        "fragmentation_tone": decision.get("fragmentation_tone", ""),
    }

    try:
        from ..language_system.word_warmup import consolidate_during_rest

        action_type = emergent_behavior_dict.get("action_type", "idle")
        consolidate_during_rest(entity, action_type)
    except Exception as consolidation_err:
        logger.debug(f"[TickEngine] Rest consolidation skipped: {consolidation_err}")

    pipeline_text = result.get("response", {}).get("text", "")
    if pipeline_text and len(pipeline_text) <= TRAINING_TEXT_MAX_LENGTH:
        entity._training_override = pipeline_text

    post_sibling_anchor(sibling_channel, entity, result, logger)

    strength, reason = evaluate_triggers(entity, emergent_behavior_dict)
    if strength > 0:
        logger.info(f"[TickEngine] Trigger strength={strength:.3f}: {reason}")
        try:
            real_action = emergent_behavior_dict.get("action_type", "comfort")
            needs_tools = real_action in TOOL_ACTION_TYPES
            training_override = getattr(entity, "_training_override", None)
            if training_override and not needs_tools:
                response = training_override
                action = XIAction(
                    action_type=real_action,
                    reason=f"training: {training_override}",
                    intensity=strength,
                    tick=entity.tick,
                    context={"training_word": training_override},
                )
                logger.info(
                    f"[TickEngine] Training output: '{training_override}' "
                    f"(action={real_action}, skipping LLM)"
                )
                action_triggered = True
                action_result = training_override
                entity._training_override = None
            else:
                if training_override:
                    logger.info(
                        f"[TickEngine] Bypassing training override for "
                        f"tool action: {real_action}"
                    )
                    entity._training_override = None
                active_llm_callable = llm_callable
                if active_llm_callable is None:
                    from ..observability import create_wrapped_llm

                    active_llm_callable = create_wrapped_llm("tick_engine_action")

                pre_action_state = entity.to_state_snapshot()
                action, response = execute_xia_choice(
                    entity=entity,
                    llm_callable=active_llm_callable,
                    suggested_tool=emergent_behavior_dict.get("suggested_tool", ""),
                    action_type=emergent_behavior_dict.get("action_type", ""),
                    emergent_behavior=None,
                )
                entity.last_action_timestamp = time.time()
                action_triggered = True
                action_result = response[:ACTION_RESULT_PREVIEW_LENGTH] if response else "(no content)"
                logger.info(f"[TickEngine] Tool action: {action_result}")
                record_autonomous_action(
                    entity=entity,
                    action=action,
                    response_text=response,
                    pre_action_state=pre_action_state,
                )
        except Exception as err:
            logger.error(f"[TickEngine] Action execution failed: {err}")
            action_result = f"error: {err}"

    return decision, action_triggered, action_result
