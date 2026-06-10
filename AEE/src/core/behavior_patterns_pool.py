"""
BehaviorPatterns Pool — PatternPool + _WorldModelDB。

提取自 behavior_patterns.py（PatternPool 类 + _WorldModelDB 类）。
"""

from __future__ import annotations

import json
import logging
import random
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from .behavior_patterns_schema import (
    PATTERNS_FILE,
    PRIMITIVE_ACTIONS,
    BehaviorPattern,
    _classify_intent,
    _make_wm_key,
)

logger = logging.getLogger(__name__)


class PatternPool:
    _instance: Optional["PatternPool"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._patterns: List[BehaviorPattern] = []
        self._dirty = False
        self._save_timer: Optional[threading.Timer] = None
        self._suppressed: Dict[str, int] = {}
        self._long_term_queue: Dict[str, List[Tuple[int, Dict[str, float]]]] = {}
        self._load()

    @classmethod
    def get_instance(cls) -> "PatternPool":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def _load(self) -> None:
        if not PATTERNS_FILE.exists():
            return
        try:
            with open(PATTERNS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            patterns_data = data.get("patterns", [])
            self._patterns = [BehaviorPattern.from_dict(p) for p in patterns_data]
            logger.info(f"[PatternPool] loaded {len(self._patterns)} patterns")
        except Exception as e:
            logger.warning(f"[PatternPool] load failed: {e}")

    def _save_async(self) -> None:
        def _do_save():
            try:
                data = {
                    "patterns": [p.to_dict() for p in self._patterns],
                    "updated_at": time.time(),
                }
                with open(PATTERNS_FILE, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.warning(f"[PatternPool] save failed: {e}")

        if self._save_timer is not None:
            self._save_timer.cancel()
        self._save_timer = threading.Timer(5.0, _do_save)
        self._save_timer.start()

    def get_candidates(self) -> List[Any]:
        candidates: List[Any] = list(PRIMITIVE_ACTIONS)
        with self._lock:
            for p in self._patterns:
                remaining = self._suppressed.get(p.pattern_id, 0)
                if remaining <= 0:
                    candidates.append(p)
        return candidates

    def get_pattern(self, pattern_id: str) -> Optional[BehaviorPattern]:
        with self._lock:
            for p in self._patterns:
                if p.pattern_id == pattern_id:
                    return p
        return None

    def update_pattern(
        self,
        pattern_or_id: Any,
        result: Dict[str, Any],
        state_snapshot: Optional[Dict[str, float]] = None,
    ) -> None:
        pid = (
            pattern_or_id.pattern_id
            if isinstance(pattern_or_id, BehaviorPattern)
            else str(pattern_or_id) if pattern_or_id else None
        )
        if pid is None:
            return

        with self._lock:
            for p in self._patterns:
                if p.pattern_id == pid:
                    break
            else:
                return

            p.usage += 1
            p.last_used_at = time.time()

            success = result.get("success", False)
            pred_err = float(result.get("prediction_error", 1.0))
            short_reward = float(result.get("short_term_reward", 0.0))
            satisfaction = float(result.get("satisfaction", 0.5))

            content = result.get("content", "")
            reason = result.get("reason", "")
            new_intent = _classify_intent(content, reason)
            if new_intent != "unknown":
                p.intent_tag = new_intent

            p.short_term_reward = 0.8 * p.short_term_reward + 0.2 * short_reward

            reward_total = 0.6 * short_reward + 0.4 * p.long_term_effect
            if success:
                p.success += 1
                p.weight = min(1.0, p.weight + 0.05 * (1 + satisfaction))
            else:
                p.weight = max(-1.0, p.weight - 0.1 * (1 + satisfaction))

            p.avg_pred_err = 0.8 * p.avg_pred_err + 0.2 * pred_err

            TRACK_DELAY = 10
            if state_snapshot and p.usage >= 2:
                if p.pattern_id not in self._long_term_queue:
                    self._long_term_queue[p.pattern_id] = []
                self._long_term_queue[p.pattern_id].append(
                    (int(time.time()), dict(state_snapshot))
                )
                if len(self._long_term_queue[p.pattern_id]) > TRACK_DELAY:
                    self._long_term_queue[p.pattern_id].pop(0)

            if satisfaction > 0.7:
                suppress_ticks = int((satisfaction - 0.7) * 30)
                self._suppressed[p.pattern_id] = max(
                    self._suppressed.get(p.pattern_id, 0), suppress_ticks
                )
                logger.info(
                    f"[PatternPool] suppressed {p.pattern_id} for {suppress_ticks} ticks "
                    f"(satisfaction={satisfaction:.2f})"
                )

            self._dirty = True
            self._save_async()

    def update_primitive(
        self,
        action: str,
        result: Dict[str, Any],
        state_snapshot: Optional[Dict[str, float]] = None,
    ) -> None:
        success = result.get("success", False)
        pred_err = float(result.get("prediction_error", 1.0))
        if state_snapshot:
            wm_key = _make_wm_key(action, state_snapshot)
            wm_predict.record_situation(wm_key, success, pred_err)
        else:
            wm_predict.record_primitive_outcome(action, success, pred_err)

    def tick_suppress(self) -> None:
        expired = []
        for pid, remaining in self._suppressed.items():
            self._suppressed[pid] = remaining - 1
            if self._suppressed[pid] <= 0:
                expired.append(pid)
        for pid in expired:
            del self._suppressed[pid]
            logger.info(f"[PatternPool] suppress expired: {pid}")

    def compute_long_term_effects(
        self,
        current_tick: int,
        state_history: Optional[List[Dict[str, float]]] = None,
        action_history: Optional[List[str]] = None,
    ) -> None:
        TRACK_DELAY = 10
        with self._lock:
            for pid, queue in list(self._long_term_queue.items()):
                if len(queue) < 2:
                    continue
                oldest_tick, oldest_state = queue[0]
                newest_tick, newest_state = queue[-1]
                if newest_tick - oldest_tick < TRACK_DELAY:
                    continue

                boredom_delta = oldest_state.get("boredom", 0.5) - newest_state.get("boredom", 0.5)
                loneliness_delta = oldest_state.get("loneliness", 0.5) - newest_state.get("loneliness", 0.5)
                state_improvement = boredom_delta * 0.6 + loneliness_delta * 0.4

                raw_entropy = 0.0
                if state_history and len(state_history) >= 3:
                    raw_entropy = self._state_entropy(state_history[-20:])

                coherence = 0.0
                if action_history and len(action_history) >= 3:
                    coherence = self._action_coherence(action_history[-20:])

                structured_progress = raw_entropy * coherence
                effect = 0.7 * state_improvement + 0.3 * structured_progress

                for p in self._patterns:
                    if p.pattern_id == pid:
                        p.long_term_effect = 0.8 * p.long_term_effect + 0.2 * effect
                        p.long_term_tracked = True
                        logger.info(
                            f"[PatternPool] LTE {pid}: "
                            f"improvement={state_improvement:.3f} "
                            f"entropy={raw_entropy:.3f} "
                            f"coherence={coherence:.3f} "
                            f"→ structured={structured_progress:.3f} "
                            f"effect={effect:.3f} avg={p.long_term_effect:.3f}"
                        )
                        break

    @staticmethod
    def _action_coherence(history: List[str]) -> float:
        if len(history) < 3:
            return 0.5
        transitions = 0
        total = len(history) - 1
        for i in range(total):
            if history[i] != history[i + 1]:
                transitions += 1
        change_rate = transitions / total
        return 1.0 - change_rate

    @staticmethod
    def _state_entropy(history: List[Dict[str, float]]) -> float:
        if len(history) < 3:
            return 0.0
        dimensions = ["boredom", "loneliness", "energy", "fatigue"]
        total_var = 0.0
        count = 0
        for dim in dimensions:
            values = [s.get(dim, 0.5) for s in history]
            if not values:
                continue
            mean = sum(values) / len(values)
            variance = sum((v - mean) ** 2 for v in values) / len(values)
            total_var += variance
            count += 1
        if count == 0:
            return 0.0
        raw_entropy = min(total_var / count * 4, 1.0)
        return raw_entropy

    def should_mutate(self, boredom: float, recent_pred_err: float) -> bool:
        return boredom > 0.8 or recent_pred_err > 0.5

    def mutate(self, intent_tag: str = "unknown") -> Optional[BehaviorPattern]:
        with self._lock:
            if len(self._patterns) >= 20:
                return None

            if self._patterns:
                base = random.choice(self._patterns)
                actions = base.actions.copy()
            else:
                base = random.choice(PRIMITIVE_ACTIONS)
                actions = [base]

            op = random.choice(["insert", "replace", "chain"])
            if op == "insert" and len(actions) < 5:
                new_action = random.choice(PRIMITIVE_ACTIONS)
                pos = random.randint(0, len(actions))
                actions.insert(pos, new_action)
            elif op == "replace":
                pos = random.randint(0, len(actions) - 1)
                new_action = random.choice(PRIMITIVE_ACTIONS)
                actions[pos] = new_action
            elif op == "chain" and len(actions) < 5:
                new_action = random.choice(PRIMITIVE_ACTIONS)
                actions.append(new_action)

            for existing in self._patterns:
                if existing.actions == actions:
                    return self._mutate_retry(attempts=3)

            new_pattern = BehaviorPattern(
                actions=actions,
                intent_tag=intent_tag,
                weight=-0.1,
            )
            self._patterns.append(new_pattern)
            self._dirty = True
            self._save_async()
            logger.info(f"[PatternPool] mutated: {actions} [{intent_tag}]")
            return new_pattern

    def _mutate_retry(self, attempts: int = 3) -> Optional[BehaviorPattern]:
        for _ in range(attempts):
            new_actions = [
                random.choice(PRIMITIVE_ACTIONS)
                for _ in range(random.randint(1, 3))
            ]
            for existing in self._patterns:
                if existing.actions == new_actions:
                    break
            else:
                new_pattern = BehaviorPattern(actions=new_actions, weight=-0.1)
                self._patterns.append(new_pattern)
                self._dirty = True
                self._save_async()
                return new_pattern
        return None

    def prune(self) -> List[str]:
        removed: List[str] = []
        with self._lock:
            before = len(self._patterns)
            self._patterns = [p for p in self._patterns if not p.is_failed]
            removed = [p.pattern_id for p in self._patterns[before:]]
            if len(self._patterns) < before:
                self._dirty = True
                self._save_async()
        if removed:
            logger.info(f"[PatternPool] pruned {len(removed)} patterns")
        return removed

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "pattern_count": len(self._patterns),
                "total_usage": sum(p.usage for p in self._patterns),
                "total_success": sum(p.success for p in self._patterns),
                "avg_weight": (
                    sum(p.weight for p in self._patterns) / len(self._patterns)
                    if self._patterns else 0.0
                ),
                "high_performing": [
                    {"id": p.pattern_id, "intent": p.intent_tag, "weight": round(p.weight, 2),
                     "long_term": round(p.long_term_effect, 3)}
                    for p in self._patterns if p.weight > 0.2
                ],
                "suppressed": {pid: r for pid, r in self._suppressed.items() if r > 0},
            }


# ============================================================================
# _WorldModelDB
# ============================================================================


class _WorldModelDB:
    """situation-level world model DB."""

    def __init__(self) -> None:
        self._db: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def record(self, key: str, success: bool, pred_err: float) -> None:
        with self._lock:
            if key not in self._db:
                self._db[key] = {
                    "reward_sum": 0.0, "reward_count": 0,
                    "pred_err_sum": 0.0, "pred_err_count": 0,
                }
            d = self._db[key]
            d["reward_sum"] += (1.0 if success else -0.5)
            d["reward_count"] += 1
            d["pred_err_sum"] += pred_err
            d["pred_err_count"] += 1

    def record_situation(self, wm_key: str, success: bool, pred_err: float) -> None:
        self.record(wm_key, success, pred_err)

    def record_primitive_outcome(self, action: str, success: bool, pred_err: float) -> None:
        self.record(action, success, pred_err)

    def predict(self, key: str) -> Dict[str, float]:
        with self._lock:
            if key not in self._db or self._db[key]["reward_count"] == 0:
                return {"reward": 0.0, "uncertainty": 1.0}
            d = self._db[key]
            avg_reward = d["reward_sum"] / d["reward_count"]
            avg_err = d["pred_err_sum"] / d["pred_err_count"]
            return {
                "reward": avg_reward,
                "uncertainty": min(1.0, avg_err),
            }

    def save(self) -> None:
        path = PATTERNS_FILE.parent / "world_model_db.json"
        with self._lock:
            data = dict(self._db)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"[WMDB] save failed: {e}")

    def load(self) -> None:
        path = PATTERNS_FILE.parent / "world_model_db.json"
        if not path.exists():
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            with self._lock:
                self._db = data
            logger.info(f"[WMDB] loaded {len(self._db)} entries")
        except Exception as e:
            logger.warning(f"[WMDB] load failed: {e}")


_wm_db = _WorldModelDB()
_wm_db.load()
wm_predict = _wm_db
