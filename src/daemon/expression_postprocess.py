"""Expression post-processing helpers for daemon ticks."""

from __future__ import annotations


def run_expression_postprocess(entity, result: dict, logger) -> None:
    """Apply post-output expression feedback, self-counsel, and credit settling."""
    try:
        from ..language_system.expression_feedback import tag_intent

        expression = result.get("response", {}).get("text", "")
        expression_tick = result.get("tick", entity.tick)
        tag_intent(entity, expression, expression_tick)
    except Exception as intent_err:
        logger.debug(f"[TickEngine] tag_intent skipped: {intent_err}")

    try:
        from ..language_system.self_counsel import apply_self_counsel

        expression = result.get("response", {}).get("text", "")
        expression_tick = result.get("tick", entity.tick)
        apply_self_counsel(entity, expression, expression_tick)
    except Exception as self_counsel_err:
        logger.debug(f"[TickEngine] apply_self_counsel skipped: {self_counsel_err}")

    try:
        from ..language_system.expression_feedback import settle_epistemic_credit

        settle_epistemic_credit(entity, entity.tick)
    except Exception as settle_err:
        logger.debug(f"[TickEngine] settle_epistemic_credit skipped: {settle_err}")
