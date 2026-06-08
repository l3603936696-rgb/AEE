"""Response-cache pre-warming helper for daemon ticks."""

from __future__ import annotations


def update_response_cache(response_cache, result: dict, entity, logger) -> None:
    """Store this tick's response text by drive vector when cache inputs exist."""
    try:
        drive_vector = result.get("drive_vector", {})
        text = result.get("response", {}).get("text", "")
        tick = result.get("tick", entity.tick)
        has_cache = min(1.0, float(response_cache is not None))
        has_drive_vector = min(1.0, float(bool(drive_vector)))
        store_weight = has_cache * has_drive_vector
        skip_weight = 1.0 - min(1.0, store_weight)
        max(
            {
                "store": (
                    store_weight,
                    lambda: response_cache.update(drive_vector, text, tick),
                ),
                "skip": (skip_weight, lambda: None),
            }.items(),
            key=lambda kv: kv[1][0],
        )[1][1]()
    except Exception as cache_err:
        logger.debug(f"[TickEngine] response_cache update skipped: {cache_err}")
