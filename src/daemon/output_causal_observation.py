"""Output-causal observation helpers for daemon ticks."""

from __future__ import annotations

OUTPUT_CAUSAL_DIMS = ("loneliness", "stress", "unresolved", "fatigue")


def close_pending_output_causal(entity, logger) -> None:
    """Close the previous output-causal observation using current state."""
    try:
        pending = getattr(entity, "_pending_output_causal", None)
        if pending:
            snap = pending["state_snapshot"]
            out_delta = {
                dim: float(getattr(entity, dim, 0.0)) - snap[dim]
                for dim in OUTPUT_CAUSAL_DIMS
            }
            observations = getattr(entity, "_causal_observations", [])
            observations.append({
                "tick": pending["tick"],
                "source": "output",
                "action_type": pending["action_type"],
                "delta": out_delta,
            })
            entity._pending_output_causal = {}
            logger.debug(
                f"[OutputCausal] closed tick={pending['tick']} delta={out_delta}"
            )
    except Exception:
        pass


def record_pending_output_causal(entity, result: dict) -> None:
    """Record the current output snapshot for closure on a later tick."""
    try:
        out_text = result.get("response", {}).get("text", "")
        if out_text:
            entity._pending_output_causal = {
                "tick": entity.tick,
                "action_type": result.get("decision", {}).get("action_type", "unknown"),
                "state_snapshot": {
                    dim: float(getattr(entity, dim, 0.0))
                    for dim in OUTPUT_CAUSAL_DIMS
                },
            }
    except Exception:
        pass
