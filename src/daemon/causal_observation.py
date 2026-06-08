"""Causal observation buffer helpers for daemon ticks."""

from __future__ import annotations

CAUSAL_OBSERVATION_DIMS = (
    "energy",
    "loneliness",
    "fatigue",
    "boredom",
    "stress",
    "info_gap",
    "unresolved",
    "approach_drive",
    "avoid_drive",
    "curiosity",
    "joy",
    "fear",
    "sadness",
    "anxiety",
)

CAUSAL_OBSERVATION_WINDOW = 200
CAUSAL_DELTA_PRECISION = 6


def record_causal_observation(
    entity,
    prev_state_snapshot: dict,
    source: str,
) -> None:
    """Append a source/state-delta observation to entity._causal_observations."""
    try:
        post_snapshot = entity.to_state_snapshot()
        delta = {}
        for dim in CAUSAL_OBSERVATION_DIMS:
            raw_delta = float(post_snapshot.get(dim, 0)) - float(prev_state_snapshot.get(dim, 0))
            delta[dim] = round(raw_delta, CAUSAL_DELTA_PRECISION)

        observations = entity._causal_observations
        observations.append({
            "tick": entity.tick,
            "source": source,
            "delta": delta,
        })
        excess = len(observations) - CAUSAL_OBSERVATION_WINDOW
        entity._causal_observations = observations[max(0, excess):]
    except Exception:
        pass
