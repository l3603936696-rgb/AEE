"""Periodic causal-learning and weathering maintenance for daemon ticks."""

from __future__ import annotations

CAUSAL_LEARNING_INTERVAL_TICKS = 100
CAUSAL_MIN_OBSERVATIONS = 10
WEATHERING_DRIFT_INTERVAL_TICKS = 300
WEATHERING_MIN_SAMPLES = 50
TENSION_SNAPSHOT_INTERVAL_TICKS = 600
CONTRADICTION_TENSION_GAIN = 0.05
TENSION_ROUND_DIGITS = 4


def run_causal_learning(entity, logger) -> None:
    """Extract causal associations from the observation buffer on schedule."""
    if entity.tick % CAUSAL_LEARNING_INTERVAL_TICKS == 0 and len(entity._causal_observations) >= CAUSAL_MIN_OBSERVATIONS:
        try:
            from ..causal_learner import extract_causal_associations

            effects = extract_causal_associations(entity._causal_observations)
            entity._causal_associations = effects
            if effects:
                logger.info(f"[CausalLearner] Associations updated: {list(effects.keys())}")
        except Exception as causal_err:
            logger.debug(f"[CausalLearner] skipped: {causal_err}")


def run_weathering_drift(entity, covariance_tracker, logger) -> None:
    """Run periodic weathering drift based on covariance correlations."""
    if entity.tick % WEATHERING_DRIFT_INTERVAL_TICKS == 0 and covariance_tracker.sample_count >= WEATHERING_MIN_SAMPLES:
        try:
            from ..weathering.param_sync import reverse_sync_conversion_params

            reverse_sync_conversion_params(entity)
        except Exception:
            pass

        try:
            from ..weathering.drift import apply_drift_cycle
            from ..weathering.param_writer import read_current_params, write_drifted_params
            from ..weathering.registry import list_all as list_driftable
            from ..weathering.signal_bridge import correlations_to_drift_signals

            correlations = covariance_tracker.get_correlations()
            if correlations:
                drift_signals = correlations_to_drift_signals(correlations)
                if drift_signals:
                    all_params = list_driftable()
                    defaults = {p.path: p.baseline_default for p in all_params}
                    current = read_current_params(
                        [p.path for p in all_params],
                        defaults,
                    )
                    drifted = apply_drift_cycle(
                        current,
                        drift_signals,
                        entity.tick_index,
                    )
                    if drifted:
                        write_drifted_params(drifted)
                        logger.info(
                            f"[weathering] Normal drift applied: "
                            f"{len(drifted)} params: {drifted}"
                        )
        except Exception as drift_err:
            logger.info(f"[weathering] Drift cycle skipped: {drift_err}")

        try:
            from ..weathering.param_sync import sync_conversion_params

            sync_conversion_params(entity)
        except Exception:
            pass


def emit_tension_snapshot_tick(entity, tick_count: int, last_tension_total: float, logger) -> float:
    """Emit periodic weathering tension snapshots and return the latest total."""
    if entity.tick % TENSION_SNAPSHOT_INTERVAL_TICKS == 0:
        try:
            from ..observability import TensionSnapshot, emit_event
            from ..weathering.shattering import load_suppressed_tension
            from ..world_model_update.contradiction import detect_contradictions

            tension_data = load_suppressed_tension()
            wm_rules = getattr(entity, "wm_rules", [])
            contradiction_pairs = detect_contradictions(wm_rules) if wm_rules else []

            if contradiction_pairs:
                from ..weathering.shattering import _save_suppressed_tension

                for contradiction_pair in contradiction_pairs:
                    domain = contradiction_pair.get("domain", "general")
                    tension_data[domain] = (
                        tension_data.get(domain, 0.0)
                        + contradiction_pair["strength"] * CONTRADICTION_TENSION_GAIN
                    )
                _save_suppressed_tension(tension_data)

            total_tension = sum(tension_data.values())
            updated_total = round(total_tension, TENSION_ROUND_DIGITS)
            emit_event(TensionSnapshot(
                tick=tick_count,
                total_tension=updated_total,
                suppressed_tension=updated_total,
                active_contradictions=len(contradiction_pairs),
                contradiction_pairs=contradiction_pairs,
                parameter_drift_summary={},
            ))
            return updated_total
        except Exception as tension_err:
            logger.debug(f"[weathering] TensionSnapshot emit skipped: {tension_err}")
    return last_tension_total
