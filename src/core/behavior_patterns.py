"""
BehaviorPattern — 经验驱动的行为进化模块 v2。

本文件为入口模块，负责：
1. 从 `behavior_patterns_schema` 导出 dataclass 和常量
2. 从 `behavior_patterns_pool` 导出 PatternPool 和 world_model
3. 提供顶层便捷函数：compute_drive_match, world_model_predict, record_outcome,
   score_candidate, select_best_candidate, apply_result, get_pool
"""

from __future__ import annotations

import random
import threading
from typing import Any, Dict, List, Optional

from .behavior_patterns_pool import (
    PatternPool,
    _wm_db,
    wm_predict,
)
from .behavior_patterns_schema import (
    ACTION_TO_TYPE,
    INTENT_TO_DRIVE,
    PRIMITIVE_ACTIONS,
    BehaviorPattern,
    update_long_term_bias,
    _make_wm_key,
)


# Re-export everything from schema for backward compatibility
__all__ = [
    "BehaviorPattern",
    "PatternPool",
    "INTENT_TO_DRIVE",
    "PRIMITIVE_ACTIONS",
    "ACTION_TO_TYPE",
    "compute_drive_match",
    "world_model_predict",
    "record_outcome",
    "score_candidate",
    "select_best_candidate",
    "apply_result",
    "get_pool",
    "update_long_term_bias",
    "wm_predict",
]


def compute_drive_match(candidate: Any, state: Dict[str, float]) -> float:
    if isinstance(candidate, BehaviorPattern):
        actions = candidate.actions
    else:
        actions = [str(candidate)]

    types = [ACTION_TO_TYPE.get(a, "explore") for a in actions]
    dominant_type = types[0]

    curiosity = state.get("curiosity", state.get("info_gap", 0.3))
    loneliness = state.get("loneliness", 0.3)
    fatigue = state.get("fatigue", 0.1)
    energy = state.get("energy", 0.8)
    boredom = state.get("boredom", 0.3)
    unresolved = state.get("unresolved", 0.2)

    if dominant_type == "explore":
        return 0.3 * curiosity + 0.3 * boredom + 0.2 * unresolved + 0.2 * (1 - fatigue)
    elif dominant_type == "rest":
        return 0.5 * fatigue + 0.3 * (1 - energy) + 0.2 * (1 - boredom)
    elif dominant_type == "seek":
        return loneliness
    elif dominant_type == "avoid":
        return state.get("danger_level", 0.0) * 0.5 + fatigue * 0.3
    return 0.2


def world_model_predict(
    candidate: Any,
    state: Dict[str, float],
) -> Dict[str, float]:
    if isinstance(candidate, BehaviorPattern):
        base = _wm_db.predict(candidate.pattern_id)
        reward = float(base["reward"])
        if candidate.intent_tag == "seek_connection" and state.get("loneliness", 0.3) > 0.5:
            reward += 0.1
        elif candidate.intent_tag == "explore_topic" and state.get("boredom", 0.3) > 0.5:
            reward += 0.1
        uncertainty = float(base["uncertainty"])
        count = 0
        with _wm_db._lock:
            if candidate.pattern_id in _wm_db._db:
                count = _wm_db._db[candidate.pattern_id].get("reward_count", 0)
        if count < 3:
            uncertainty = min(1.0, uncertainty + (3 - count) * 0.15)
        return {"reward": max(-1.0, min(1.0, reward)), "uncertainty": max(0.0, min(1.0, uncertainty))}
    else:
        action = str(candidate)
        wm_key = _make_wm_key(action, state)
        base = _wm_db.predict(wm_key)
        reward = float(base["reward"])
        uncertainty = float(base["uncertainty"])
        boredom = state.get("boredom", 0.3)
        if action.startswith("web_"):
            reward += boredom * 0.1
        count = 0
        with _wm_db._lock:
            if wm_key in _wm_db._db:
                count = _wm_db._db[wm_key].get("reward_count", 0)
        if count < 3:
            uncertainty = min(1.0, uncertainty + (3 - count) * 0.15)
        return {"reward": max(-1.0, min(1.0, reward)), "uncertainty": max(0.0, min(1.0, uncertainty))}


def record_outcome(
    candidate: Any,
    success: bool,
    prediction_error: float,
    state_snapshot: Optional[Dict[str, float]] = None,
) -> None:
    if isinstance(candidate, BehaviorPattern):
        key = candidate.pattern_id
    else:
        key = _make_wm_key(str(candidate), state_snapshot or {}) if state_snapshot else str(candidate)
    _wm_db.record(key, success, prediction_error)
    _wm_db.save()


def score_candidate(
    candidate: Any,
    state: Dict[str, float],
    pool: Optional[PatternPool] = None,
    entity_state: Any = None,
) -> float:
    base = compute_drive_match(candidate, state)
    pred = world_model_predict(candidate, state)
    pred_reward = pred["reward"]
    pred_uncertainty = pred["uncertainty"]

    pattern_weight = 0.0
    long_term_bonus = 0.0
    if isinstance(candidate, BehaviorPattern):
        pattern_weight = candidate.weight
        if candidate.long_term_tracked:
            long_term_bonus = candidate.long_term_effect * 0.3

    bias_bonus = 0.0
    if entity_state is not None and hasattr(entity_state, "long_term_bias"):
        intent = (
            candidate.intent_tag
            if isinstance(candidate, BehaviorPattern)
            else "unknown"
        )
        drive = INTENT_TO_DRIVE.get(intent, "explore")
        bias = entity_state.long_term_bias.get(drive, 0.0)
        bias_bonus = 0.15 * bias

    score = (
        base
        + 0.6 * pred_reward
        - 0.4 * pred_uncertainty
        + pattern_weight
        + long_term_bonus
        + bias_bonus
    )
    return max(-1.0, min(1.0, score))


def get_pool() -> PatternPool:
    return PatternPool.get_instance()


def select_best_candidate(state: Dict[str, float], entity_state: Any = None) -> Any:
    pool = get_pool()
    candidates = pool.get_candidates()

    if not candidates:
        return random.choice(PRIMITIVE_ACTIONS)

    boredom = state.get("boredom", 0.3)
    recent_err = _wm_db.predict("__global__").get("uncertainty", 0.5)

    scored = [(c, score_candidate(c, state, pool, entity_state)) for c in candidates]
    scored.sort(key=lambda x: x[1], reverse=True)
    best = scored[0][0]

    if len(scored) > 1 and random.random() < 0.15:
        best = scored[1][0]

    if pool.should_mutate(boredom, recent_err):
        if random.random() < 0.3:
            intent = "unknown"
            if boredom > 0.6:
                intent = "kill_time"
            elif state.get("loneliness", 0.3) > 0.5:
                intent = "seek_connection"
            new_p = pool.mutate(intent_tag=intent)
            if new_p is not None:
                new_score = score_candidate(new_p, state, pool, entity_state)
                if new_score > scored[0][1]:
                    best = new_p

    if len(scored) >= 3 and random.random() < 0.10:
        best = random.choice(scored[:3])[0]
    elif len(scored) >= 2 and random.random() < 0.10:
        best = random.choice(scored[:2])[0]

    return best


def apply_result(
    candidate: Any,
    result: Dict[str, Any],
    state_snapshot: Optional[Dict[str, float]] = None,
) -> None:
    pool = get_pool()
    if isinstance(candidate, BehaviorPattern):
        pool.update_pattern(candidate.pattern_id, result, state_snapshot)
    elif isinstance(candidate, str) and candidate in PRIMITIVE_ACTIONS:
        pool.update_primitive(candidate, result, state_snapshot)

    record_outcome(
        candidate,
        result.get("success", False),
        result.get("prediction_error", 1.0),
        state_snapshot,
    )
