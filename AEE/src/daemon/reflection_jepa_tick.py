"""Diary, reflection, and JEPA maintenance for daemon ticks."""

from __future__ import annotations

NARRATIVE_PREVIEW_LENGTH = 40


def write_tick_diary(entity, decision, logger, debug_label: str = "inner_diary") -> None:
    """Write the tick diary entry without blocking the daemon tick."""
    try:
        from ..inner_diary import write_diary_entry

        write_diary_entry(
            state=entity,
            decision=decision,
            prev_state=None,
        )
    except Exception as err:
        logger.debug(f"[TickEngine] {debug_label} write skipped: {err}")


def run_reflection_and_jepa(entity, logger) -> None:
    """Run reflective and JEPA background learning steps."""
    try:
        from ..language_system.reflection_layer import reflect, should_reflect

        if should_reflect(entity):
            result = reflect(entity)
            if result.get("applied"):
                narrative = (entity._self_narrative or "")[:NARRATIVE_PREVIEW_LENGTH]
                logger.info(f"[Reflection] t={entity.tick} applied, narrative='{narrative}'")
            else:
                logger.debug(f"[Reflection] t={entity.tick} skipped: {result.get('reason', '')}")
    except Exception as err:
        logger.debug(f"[Reflection] error: {err}")

    try:
        from ..jepa.i_jepa import get_i_jepa

        error = get_i_jepa().step(entity)
        logger.debug(f"[I-JEPA] t={entity.tick} recon_err={error:.4f}")
    except Exception as err:
        logger.debug(f"[I-JEPA] error: {err}")

    try:
        from ..jepa.v_jepa import get_v_jepa

        v_jepa = get_v_jepa()
        if v_jepa.should_run(entity):
            result = v_jepa.summarize(entity)
            if result.get("applied"):
                logger.info(
                    f"[V-JEPA] t={entity.tick} "
                    f"surprise={result.get('surprise_density', 0):.3f} "
                    f"transitions={len(result.get('transition_ticks', []))}"
                )
    except Exception as err:
        logger.debug(f"[V-JEPA] error: {err}")
