"""World-model periodic maintenance for daemon ticks."""

from __future__ import annotations

WORLD_MODEL_INTERVAL_TICKS = 10
WORLD_MODEL_MIN_SNAPSHOTS = 5
QUESTION_RELEASE_GAIN = 0.3
QUESTION_PRIORITY_DECAY_GAIN = 0.2


def run_world_model_tick(entity, logger) -> None:
    """Run periodic world-model induction, question tension release, and reading taste update."""
    if entity.tick % WORLD_MODEL_INTERVAL_TICKS == 0:
        try:
            snapshots = getattr(entity, "snapshots", [])
            if len(snapshots) >= WORLD_MODEL_MIN_SNAPSHOTS:
                from ..world_model_update.core import run_update_cycle

                state_snapshot = entity.to_state_snapshot()
                old_rules = getattr(entity, "wm_rules", [])
                new_rules, wm_stats = run_update_cycle(
                    old_rules=old_rules,
                    snaps=snapshots,
                    dialogue_log=[],
                    state_snapshot=state_snapshot,
                    param_snapshot=None,
                )
                if isinstance(new_rules, list):
                    entity.wm_rules = [
                        rule.to_dict() if hasattr(rule, "to_dict") else dict(rule)
                        for rule in new_rules
                    ]
                    entity.snapshots = snapshots[-WORLD_MODEL_MIN_SNAPSHOTS:]
                    logger.info(
                        f"[TickEngine] WM induction: "
                        f"{len(old_rules)} -> {len(entity.wm_rules)} rules "
                        f"(inducted={wm_stats.inducted})"
                    )
                    _release_question_tension(entity, logger)
        except Exception as wm_err:
            logger.debug(f"[TickEngine] WM induction skipped: {wm_err}")

        try:
            from .reading_taste import update_taste_from_efficiency

            update_taste_from_efficiency(entity)
        except Exception:
            pass


def _release_question_tension(entity, logger) -> None:
    pending_questions = getattr(entity, "_pending_questions", [])
    if pending_questions:
        try:
            rule_map = {}
            for rule_dict in entity.wm_rules:
                rule_id = rule_dict.get("id", "")
                if rule_id:
                    rule_map[rule_id] = rule_dict

            total_release = 0.0
            for question in pending_questions:
                matched_rule = rule_map.get(question.get("rule_id", ""))
                if not matched_rule:
                    continue

                rule_confidence = float(matched_rule.get("confidence", 0))
                confidence_at_ask = float(question.get("confidence_at_ask", 0))
                delta_confidence = max(0.0, rule_confidence - confidence_at_ask)
                if delta_confidence <= 0:
                    continue

                release = (
                    delta_confidence
                    * question.get("priority", 0.0)
                    * QUESTION_RELEASE_GAIN
                )
                total_release += release
                question["priority"] = max(
                    0.0,
                    question["priority"] - delta_confidence * QUESTION_PRIORITY_DECAY_GAIN,
                )
                question["confidence_at_ask"] = rule_confidence

            if total_release > 0:
                entity.unresolved = max(0.0, entity.unresolved - total_release)
                logger.info(
                    f"[TickEngine] Question tension released: "
                    f"{total_release:.4f}, "
                    f"remaining priority: "
                    f"{[round(q.get('priority', 0), 2) for q in pending_questions]}"
                )
        except Exception:
            pass
