"""Memory write-back for autonomous daemon actions."""

from __future__ import annotations

import logging
import time


logger = logging.getLogger(__name__)


def record_autonomous_action(
    entity,
    action,
    response_text: str,
    pre_action_state: dict,
) -> None:
    """
    Write autonomous action results into memory and behavior rules.

    Kept separate from TickEngine so the daemon loop stays focused on tick
    orchestration rather than episode construction details.
    """
    try:
        from ..memory_hub.episodes_db import build_episode, write_episode_async
        from ..core.behavior_vector import update_rules_from_snapshot

        action_type = action.action_type if hasattr(action, "action_type") else "voice"

        semantic_packet = {
            "emotion": getattr(entity, "somatic_tone", 0.0),
            "intent": action_type,
            "intensity": 0.5,
            "anchors": [],
            "intent_confidence": 0.8,
        }

        decision = {
            "action_type": action_type,
            "target": "self",
            "priority": 0.5,
        }

        post_action_state = entity.to_state_snapshot()

        episode = build_episode(
            iteration_id=entity.tick,
            raw_input=None,
            semantic_packet_biased=semantic_packet,
            decision=decision,
            intent_repr={"tone": "neutral", "goal": "reflect", "constraints": {}},
            state_snapshot=post_action_state,
            drive_vector={},
            output_text=response_text or "",
            idle_seconds=0,
            was_override=False,
            tags=["autonomous", action_type],
            summary=f"XIA {action_type}: {(response_text or '')[:60]}",
        )
        write_episode_async(episode)

        snap_for_rules = {
            "action_type": action_type,
            "pre_state": pre_action_state,
            "post_state": post_action_state,
        }
        update_rules_from_snapshot(entity, snap_for_rules, entity.tick)

        entity.add_snapshot({
            "snap_index": entity.tick,
            "timestamp": time.time(),
            "action_type": action_type,
            "target": "self",
            "priority": 0.5,
            "pre_state": pre_action_state,
            "post_state": post_action_state,
            "wm_context": [],
            "decision": decision,
            "prediction_error": 0.0,
            "identity_signal": 0.5,
            "unresolved_source": "self_generated",
        })

        logger.info(
            f"[TickEngine] Memory recorded: action={action_type}, "
            f"text_len={len(response_text or '')}"
        )

        try:
            _pre_st = float(pre_action_state.get("somatic_tone", 0.0))
            _post_st = float(post_action_state.get("somatic_tone", 0.0))
            _pre_stress = float(pre_action_state.get("stress", 0.0))
            _post_stress = float(post_action_state.get("stress", 0.0))
            _negative_delta = (_pre_st - _post_st) + (_post_stress - _pre_stress)
            if _negative_delta > 0.05:
                _five_r = getattr(entity, "_five_rights", None)
                if _five_r and hasattr(_five_r, "mark_forget"):
                    _five_r.mark_forget(
                        episode_id=entity.tick,
                        negative_strength=min(1.0, _negative_delta),
                    )
                    logger.debug(
                        f"[TickEngine] Forget-right: marked tick={entity.tick} "
                        f"(negative_delta={_negative_delta:.3f})"
                    )
        except Exception:
            pass
    except Exception as e:
        logger.warning(f"[TickEngine] Failed to record autonomous action memory: {e}")
