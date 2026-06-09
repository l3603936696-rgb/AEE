"""
Sentence Composer Schema — constants and helper functions for sentence_composer.

Submodules of src.language_system.sentence_composer:
    sentence_composer_schema.py   — hyperparameters + math helpers
    sentence_composer_patterns.py — PATTERNS + COMPOUND_PATTERNS data
    sentence_composer_helpers.py — standalone math helpers
    sentence_composer.py         — core composition logic
"""

import math
import random
from typing import Callable, Dict, List

# ─── Hyperparameters ───────────────────────────────────────────────────────────
_COMPOSE_TEMP_BASE         = 0.40
_COMPOSE_TEMP_BOREDOM_GAIN = 0.50
_ANCHOR_USE_BONUS          = 0.12
_ANCHOR_STRENGTH_GAIN      = 1.0
_ANCHOR_POS_WEIGHT: Dict[str, float] = {
    "none": 0.0, "adj": 1.0, "head": 1.0,
    "tail": 1.0, "embed": 1.0, "infix": 1.0,
}
_STRUCTURE_BONUS_SCALE = 0.15
_TEMPLATE_CONNECTOR_WEIGHTS: Dict[str, float] = {
    "因为": 0.80, "所以": 0.80, "原来": 0.80,
    "但是": 0.50, "但":   0.50, "虽然": 0.50,
    "其实": 0.50, "然后": 0.50, "突然": 0.50, "而且": 0.45,
    "可能": 0.25, "应该": 0.25, "也许": 0.25,
    "大概": 0.25, "好像": 0.25, "如果": 0.25,
}
_BASE_TEMPLATE_STRUCTURE = 0.15

# ─── Helper Functions ──────────────────────────────────────────────────────────

def _template_structure_score(template: str) -> float:
    """Template structural score: max weight of matching connector."""
    scores = [_BASE_TEMPLATE_STRUCTURE]
    scores.extend(
        w * float(conn in template)
        for conn, w in _TEMPLATE_CONNECTOR_WEIGHTS.items()
    )
    return max(scores)


def _g(x: float, mu: float, sigma: float = 0.20) -> float:
    """Gaussian scoring: closer to mu = higher score. Returns (0, 1]."""
    return math.exp(-0.5 * (abs(x - mu) / max(sigma, 0.001)) ** 2)


def _anchor_penalty(anchor_len: int, pos: str) -> float:
    """Penalty for anchor length and position."""
    base = min(0.15, anchor_len * 0.015)
    pos_map = {"none": 0.15, "tail": 0.10, "head": 0.08, "adj": 0.05, "embed": 0.03, "infix": 0.06}
    return base + pos_map.get(pos, 0.10)


def _softmax_sample(scores: List[float], temperature: float = 0.4) -> int:
    """Softmax sampling from scores."""
    if not scores:
        return 0
    max_s = max(scores)
    weights = [math.exp((s - max_s) / max(temperature, 0.01)) for s in scores]
    total = sum(weights)
    probs = [w / max(total, 1e-9) for w in weights]
    return random.choices(range(len(scores)), weights=probs, k=1)[0]
