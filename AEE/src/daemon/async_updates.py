"""Async experience update submission for daemon ticks."""

from __future__ import annotations


def submit_pipeline_async_updates(entity, result: dict, submit_async, process_async_updates, logger) -> None:
    """Submit fire-and-forget async memory/world-model updates for a pipeline result."""
    try:
        exp_log = type("EL", (), {
            "content": str(result.get("response", {}).get("text", "")),
            "tags": [f"action:{result.get('decision', {}).get('action_type', '')}"],
            "weight": 1.0,
        })()
        snap_obj = type("SS", (), {
            "fatigue": float(getattr(entity, "fatigue", 0.0)),
            "stress": float(getattr(entity, "stress", 0.0)),
        })()
        submit_async(
            process_async_updates(
                experience_log=exp_log,
                state_snapshot=snap_obj,
                entity_id="XIA",
                entity=entity,
                param_snapshot=None,
            )
        )
    except Exception as async_err:
        logger.debug(f"[TickEngine] process_async_updates skip: {async_err}")
