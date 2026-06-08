"""Covariance tracker update helper for daemon ticks."""

from __future__ import annotations


def update_covariance_tracker(entity, covariance_tracker, logger) -> None:
    """Record this tick's state and prediction error into the covariance tracker."""
    try:
        prediction_error = float(getattr(entity, "_last_prediction_error", 0.0))
        covariance_tracker.update(entity.to_state_snapshot(), prediction_error)
        entity._covariance_tracker_data = covariance_tracker.to_dict()
        entity._attention_weights = covariance_tracker.get_attention_weights()
    except Exception as cov_err:
        logger.debug(f"[CovarianceTracker] update skipped: {cov_err}")
