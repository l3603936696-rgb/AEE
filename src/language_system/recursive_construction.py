"""
Recursive Construction — 递归构式（v1.0）

让构式的槽位可以填另一个构式，实现多层嵌套表达。

子模块：
    recursive_schema.py — ClausePattern + 超参 + ROLE_FILLERS + SEED_CLAUSE_PATTERNS + 辅助函数
    recursive_construction.py — RecursiveGenerator 类（瘦入口）
"""

import logging
import math
import random
from typing import Dict, List, Optional

from .recursive_schema import (
    ClausePattern,
    ROLE_FILLERS,
    SEED_CLAUSE_PATTERNS,
    _fill_role_from_state,
    _MAX_DEPTH,
    _MAX_CLAUSE_PATTERNS,
    _STRENGTH_DECAY,
    _STRENGTH_BOOST,
)

logger = logging.getLogger(__name__)


def _softmax_sample(scores: List[float], temperature: float = 0.5) -> int:
    """Softmax sampling from a list of scores."""
    if not scores:
        return 0
    max_s = max(scores)
    weights = [math.exp((s - max_s) / max(temperature, 0.01)) for s in scores]
    total = sum(weights)
    probs = [w / max(total, 1e-9) for w in weights]
    return random.choices(range(len(scores)), weights=probs, k=1)[0]


class RecursiveGenerator:
    """
    递归构式生成器。

    用法：
        gen = RecursiveGenerator()
        clause = gen.generate_clause(drive_state, anchor_words, depth=0)
    """

    def __init__(self):
        self._patterns: List[ClausePattern] = []
        self._load_seeds()

    def _load_seeds(self) -> None:
        for seed in SEED_CLAUSE_PATTERNS:
            cp = ClausePattern(
                schema=seed["schema"],
                slot_roles=seed["slot_roles"],
                drive_trigger=seed["drive_trigger"],
            )
            self._patterns.append(cp)

    def generate_clause(
        self,
        drive_state: Dict[str, float],
        anchor_words: List[str],
        depth: int = 0,
        avoid_words: Optional[List[str]] = None,
    ) -> Optional[str]:
        if depth >= _MAX_DEPTH:
            return None
        if not self._patterns:
            return None

        scores = []
        for cp in self._patterns:
            s = self._score_pattern(cp, drive_state) * cp.strength
            scores.append(s)

        idx = _softmax_sample(scores, temperature=0.5)
        chosen = self._patterns[idx]

        _avoid = set(avoid_words or [])
        filled = chosen.schema
        for slot_name, role in chosen.slot_roles.items():
            filler = _fill_role_from_state(role, drive_state, anchor_words)
            if not filler:
                return None
            if _avoid and any(aw in filler for aw in _avoid):
                filler = _fill_role_from_state(role, drive_state, anchor_words)
                if any(aw in filler for aw in _avoid):
                    continue
            filled = filled.replace("{" + slot_name + "}", filler, 1)

        chosen.use_count += 1
        return filled

    def _score_pattern(self, cp: ClausePattern, drive_state: Dict[str, float]) -> float:
        if not cp.drive_trigger:
            return 0.3
        score = 0.0
        for dim, weight in cp.drive_trigger.items():
            val = float(drive_state.get(dim, 0.0))
            score += val * weight
        return score

    def reinforce(self, schema: str, efficiency: float) -> None:
        for cp in self._patterns:
            if cp.schema == schema:
                delta = _STRENGTH_BOOST * (efficiency - 0.03)
                cp.strength = max(0.0, min(1.0, cp.strength + delta))
                break

    def decay_all(self) -> None:
        for cp in self._patterns:
            cp.strength *= _STRENGTH_DECAY

    def add_pattern(self, cp: ClausePattern) -> None:
        existing = {p.schema for p in self._patterns}
        if cp.schema in existing:
            return
        self._patterns.append(cp)
        if len(self._patterns) > _MAX_CLAUSE_PATTERNS:
            self._patterns.sort(key=lambda p: p.strength, reverse=True)
            self._patterns = self._patterns[:_MAX_CLAUSE_PATTERNS]
        logger.info(f"[RecCxG] New clause pattern: '{cp.schema}'")

    def to_dict(self) -> dict:
        return {"patterns": [p.to_dict() for p in self._patterns]}

    @classmethod
    def from_dict(cls, d: dict) -> "RecursiveGenerator":
        gen = cls.__new__(cls)
        gen._patterns = []
        for pd in d.get("patterns", []):
            gen._patterns.append(ClausePattern.from_dict(pd))
        existing = {p.schema for p in gen._patterns}
        for seed in SEED_CLAUSE_PATTERNS:
            if seed["schema"] not in existing:
                gen._patterns.append(ClausePattern(
                    seed["schema"], seed["slot_roles"], seed["drive_trigger"],
                ))
        return gen

    @property
    def pattern_count(self) -> int:
        return len(self._patterns)
