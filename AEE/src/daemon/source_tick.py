"""Source-profile maintenance helpers for daemon ticks."""

from __future__ import annotations

import math

FAMILIARITY_DECAY_TICKS = 20.0
LONELINESS_SUPPRESSION_GAIN = 0.4
LONELINESS_SUPPRESSION_SCALE = 0.001


def update_source_tick(entity, result: dict, input_source: str, source_identity: dict, logger) -> str:
    """Update source profile, reply drive, and familiarity-based loneliness suppression."""
    source_id = "none"

    if input_source != "none":
        try:
            from ..language_system.source_profiler import get_source_id, update_profile
            from .environment_vector import inject_source_residue

            source_id = source_identity.get("source_id") or get_source_id(input_source, entity)
            observations = entity._causal_observations
            last_delta = observations[-1]["delta"] if observations else {}
            update_profile(
                entity,
                source_id,
                result.get("cx_recognized_words", []),
                result.get("cx_social_intent", "unknown"),
                last_delta,
                entity.tick,
                source_identity=source_identity,
            )
            logger.debug(f"[SourceProfiler] updated profile for {source_id}")
            inject_source_residue(entity, source_id)
        except Exception as source_err:
            logger.debug(f"[SourceProfiler] update skipped: {source_err}")

    if source_id != "none":
        try:
            from ..language_system.reply_motivator import inject_reply_drive

            injected = inject_reply_drive(
                entity,
                source_id,
                result.get("cx_social_intent", "unknown"),
            )
            logger.debug(
                f"[ReplyMotivator] injected {injected:.4f} -> "
                f"approach_social={entity.approach_social:.4f}"
            )
        except Exception as reply_err:
            logger.debug(f"[ReplyMotivator] skipped: {reply_err}")

    try:
        from ..language_system.source_profiler import get_familiarity

        profiles = getattr(entity, "_source_profiles", {})
        current_tick = entity.tick
        best_familiarity_decayed = 0.0
        for sid, profile in profiles.items():
            ticks_ago = current_tick - profile.get("last_tick", 0)
            familiarity = get_familiarity(entity, sid)
            familiarity_decayed = familiarity * math.exp(-ticks_ago / FAMILIARITY_DECAY_TICKS)
            best_familiarity_decayed = max(best_familiarity_decayed, familiarity_decayed)
        suppression = (
            best_familiarity_decayed
            * LONELINESS_SUPPRESSION_GAIN
            * LONELINESS_SUPPRESSION_SCALE
        )
        loneliness_core = float(getattr(entity, "loneliness_core", 0.0))
        entity.loneliness_core = max(0.0, loneliness_core - suppression)
    except Exception as familiarity_err:
        logger.debug(f"[SourceProfiler L3] skipped: {familiarity_err}")

    return source_id
