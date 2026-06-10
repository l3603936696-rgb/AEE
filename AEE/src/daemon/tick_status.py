"""Status summary helpers for the daemon tick engine."""

from __future__ import annotations

import time

STATUS_ROUND_DIGITS = 3
UPTIME_ROUND_DIGITS = 1
PERSONALITY_CORE_TOP_N = 3
DIMENSION_VALUE_ROUND_DIGITS = 4


def build_tick_status(
    entity,
    covariance_tracker,
    uptime_s: float,
    tick_interval: float,
    tick_count: int,
    last_tension_total: float,
) -> dict:
    """Build the daemon status payload."""
    last_action = getattr(entity, "last_action_timestamp", 0.0)
    now = time.time()
    time_since_last_action = now - last_action if last_action > 0 else None
    return {
        "pid": entity.tick,
        "uptime_s": round(uptime_s, UPTIME_ROUND_DIGITS),
        "tick_interval_s": tick_interval,
        "ticks_since_start": tick_count,
        "current_tick": entity.tick,
        "energy": round(entity.energy, STATUS_ROUND_DIGITS),
        "loneliness": round(entity.loneliness, STATUS_ROUND_DIGITS),
        "fatigue": round(entity.fatigue, STATUS_ROUND_DIGITS),
        "boredom": round(entity.boredom, STATUS_ROUND_DIGITS),
        "stress": round(entity.stress, STATUS_ROUND_DIGITS),
        "last_interaction": (
            time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(entity.last_interaction_timestamp))
            if entity.last_interaction_timestamp > 0 else "never"
        ),
        "last_action": (
            time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(last_action))
            if last_action > 0 else "none"
        ),
        "time_since_last_action_s": (
            round(time_since_last_action) if time_since_last_action is not None else None
        ),
        "somatic_tone": round(entity.somatic_tone, STATUS_ROUND_DIGITS),
        "joy": round(getattr(entity, "joy", 0.0), STATUS_ROUND_DIGITS),
        "excitement": round(getattr(entity, "excitement", 0.0), STATUS_ROUND_DIGITS),
        "serenity": round(getattr(entity, "serenity", 0.0), STATUS_ROUND_DIGITS),
        "sadness": round(getattr(entity, "sadness", 0.0), STATUS_ROUND_DIGITS),
        "anger": round(getattr(entity, "anger", 0.0), STATUS_ROUND_DIGITS),
        "fear": round(getattr(entity, "fear", 0.0), STATUS_ROUND_DIGITS),
        "disgust": round(getattr(entity, "disgust", 0.0), STATUS_ROUND_DIGITS),
        "anxiety": round(getattr(entity, "anxiety", 0.0), STATUS_ROUND_DIGITS),
        "surprise": round(getattr(entity, "surprise", 0.0), STATUS_ROUND_DIGITS),
        "curiosity": round(getattr(entity, "curiosity", 0.5), STATUS_ROUND_DIGITS),
        "approach_drive": round(getattr(entity, "approach_drive", 0.0), STATUS_ROUND_DIGITS),
        "avoid_drive": round(getattr(entity, "avoid_drive", 0.0), STATUS_ROUND_DIGITS),
        "unresolved": round(getattr(entity, "unresolved", 0.2), STATUS_ROUND_DIGITS),
        "info_gap": round(getattr(entity, "info_gap", 0.5), STATUS_ROUND_DIGITS),
        "pain": round(getattr(entity, "pain", 0.0), STATUS_ROUND_DIGITS),
        "loneliness_core": round(getattr(entity, "loneliness_core", 0.0), STATUS_ROUND_DIGITS),
        "loneliness_surface": round(getattr(entity, "loneliness_surface", 0.0), STATUS_ROUND_DIGITS),
        "boredom_despair": round(getattr(entity, "boredom_despair", 0.0), STATUS_ROUND_DIGITS),
        "boredom_futility": round(getattr(entity, "boredom_futility", 0.0), STATUS_ROUND_DIGITS),
        "unlocked_vocab_count": len(getattr(entity, "_unlocked_vocabulary", [])),
        "template_learned_count": len(getattr(entity, "_template_learned_weights", {})),
        "runtime_template_count": len(getattr(entity, "_runtime_templates", [])),
        "covariance_samples": covariance_tracker.sample_count,
        "attention_weights": covariance_tracker.get_attention_weights(),
        "personality_core": _get_personality_core(entity),
        "dimension_values": _get_dimension_values(entity),
        "suppressed_tension": last_tension_total,
        "causal_observations_count": len(getattr(entity, "_causal_observations", [])),
        "causal_associations": dict(getattr(entity, "_causal_associations", {})),
    }


def _get_dimension_values(entity) -> dict:
    try:
        from ..world_model_update.dimension_cost import compute_dimension_values

        wm_rules = getattr(entity, "wm_rules", [])
        snapshots = getattr(entity, "snapshots", [])
        if not wm_rules:
            return {}
        values = compute_dimension_values(wm_rules, snapshots)
        return {key: round(value, DIMENSION_VALUE_ROUND_DIGITS) for key, value in values.items()}
    except Exception:
        return {}


def _get_personality_core(entity) -> list:
    try:
        from ..world_model_update.model_inertia import identify_personality_core
        from ..world_model_update.rules import Rule

        wm_rules = getattr(entity, "wm_rules", [])
        if not wm_rules:
            return []
        rule_objs = []
        for rule in wm_rules:
            if isinstance(rule, Rule):
                rule_objs.append(rule)
            elif isinstance(rule, dict):
                rule_objs.append(Rule.from_dict(rule))
        return [
            {"id": rule_id, "inertia": round(inertia, STATUS_ROUND_DIGITS)}
            for rule_id, inertia in identify_personality_core(rule_objs, top_n=PERSONALITY_CORE_TOP_N)
        ]
    except Exception:
        return []
