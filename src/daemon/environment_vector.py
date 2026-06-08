"""Environment-vector maintenance helpers for daemon ticks."""

from __future__ import annotations


DEFAULT_ENVIRONMENT_VECTOR = {
    "semantic_residue": {},
    "social_prediction_tension": 0.0,
    "physical": {},
}

SEMANTIC_RESIDUE_DECAY = 0.8
SEMANTIC_RESIDUE_PRUNE_BELOW = 0.001
SOCIAL_PREDICTION_TENSION_MAX = 5.0
SOCIAL_PREDICTION_TENSION_STEP = 1.0
SOURCE_RESIDUE_INCREMENT = 1.0


def decay_environment_vector(entity) -> None:
    """Apply the per-tick decay/update step for entity._environment_vector."""
    try:
        env = getattr(entity, "_environment_vector", None)
        if env is None:
            env = {
                "semantic_residue": dict(DEFAULT_ENVIRONMENT_VECTOR["semantic_residue"]),
                "social_prediction_tension": DEFAULT_ENVIRONMENT_VECTOR["social_prediction_tension"],
                "physical": dict(DEFAULT_ENVIRONMENT_VECTOR["physical"]),
            }
            entity._environment_vector = env

        semantic_residue = env.get("semantic_residue", {})
        for source_id in list(semantic_residue.keys()):
            semantic_residue[source_id] = semantic_residue[source_id] * SEMANTIC_RESIDUE_DECAY
            if semantic_residue[source_id] < SEMANTIC_RESIDUE_PRUNE_BELOW:
                del semantic_residue[source_id]
        env["semantic_residue"] = semantic_residue

        tension = float(env.get("social_prediction_tension", 0.0))
        tension = min(
            SOCIAL_PREDICTION_TENSION_MAX,
            tension
            + SOCIAL_PREDICTION_TENSION_STEP
            * (1.0 - tension / SOCIAL_PREDICTION_TENSION_MAX),
        )
        env["social_prediction_tension"] = tension
    except Exception:
        pass


def inject_source_residue(entity, source_id: str) -> None:
    """Record recent semantic presence for a non-empty input source."""
    try:
        env = getattr(entity, "_environment_vector", {})
        semantic_residue = env.setdefault("semantic_residue", {})
        semantic_residue[source_id] = min(
            1.0,
            semantic_residue.get(source_id, 0.0) + SOURCE_RESIDUE_INCREMENT,
        )
        env["social_prediction_tension"] = 0.0
        entity._environment_vector = env
    except Exception:
        pass
