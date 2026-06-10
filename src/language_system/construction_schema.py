"""
Construction Schema — data structures and hyperparameters for construction grammar.

Submodules of src.language_system.construction_grammar:
    construction_schema.py — hyperparameters + class definitions
    construction_grammar.py — ConstructionLearner class + helpers
"""

import math
from typing import Any, Dict, List, Set

# ─── Hyperparameters ───────────────────────────────────────────────────────────
_MAX_INSTANCES = 500
_MIN_INSTANCES_FOR_SCHEMA = 3
_MIN_EFFICIENCY = 0.0
_BASELINE_EFFICIENCY = 0.05
_STRENGTH_DECAY = 0.995
_STRENGTH_BOOST = 0.15
_MAX_CONSTRUCTIONS = 40
_MAX_FILLERS_PER_SLOT = 30
_SLOT_AFFINITY_DECAY = 0.98
_MIN_STRENGTH = 0.01


# ─── ExpressionInstance ────────────────────────────────────────────────────────

class ExpressionInstance:
    """一次成功表达的记录。"""
    __slots__ = ("structure", "fillers", "drive_state", "efficiency", "tick", "action_context", "is_heard")

    def __init__(
        self,
        structure: str,
        fillers: List[str],
        drive_state: Dict[str, float],
        efficiency: float,
        tick: int,
        action_context: str = "",
        is_heard: bool = False,
    ):
        self.structure = structure
        self.fillers = fillers
        self.drive_state = drive_state
        self.efficiency = efficiency
        self.tick = tick
        self.action_context = action_context
        self.is_heard = is_heard


# ─── Construction ──────────────────────────────────────────────────────────────

class Construction:
    """一个学到的构式。"""
    __slots__ = (
        "schema", "slot_fillers", "slot_affinity",
        "drive_profile", "strength", "use_count",
        "born_tick", "last_used_tick",
        "action_profile",
        "heard_ratio",
    )

    def __init__(self, schema: str, born_tick: int = 0):
        self.schema = schema
        self.slot_fillers: Dict[int, Dict[str, float]] = {}
        self.slot_affinity: Dict[int, int] = {}
        self.drive_profile: Dict[str, float] = {}
        self.strength: float = 0.1
        self.use_count: int = 0
        self.born_tick: int = born_tick
        self.last_used_tick: int = born_tick
        self.action_profile: Dict[str, int] = {}
        self.heard_ratio: float = 0.0

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "slot_fillers": {
                str(k): dict(v) for k, v in self.slot_fillers.items()
            },
            "drive_profile": dict(self.drive_profile),
            "strength": self.strength,
            "use_count": self.use_count,
            "born_tick": self.born_tick,
            "last_used_tick": self.last_used_tick,
            "action_profile": dict(self.action_profile),
            "heard_ratio": self.heard_ratio,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Construction":
        cx = cls(d.get("schema", ""), born_tick=d.get("born_tick", 0))
        cx.slot_fillers = {
            int(k): v for k, v in d.get("slot_fillers", {}).items()
        }
        cx.drive_profile = d.get("drive_profile", {})
        cx.strength = d.get("strength", 0.0)
        cx.use_count = d.get("use_count", 0)
        cx.born_tick = d.get("born_tick", 0)
        cx.last_used_tick = d.get("last_used_tick", 0)
        cx.action_profile = d.get("action_profile", {})
        cx.heard_ratio = d.get("heard_ratio", 0.0)
        return cx


# ─── Helper Functions ─────────────────────────────────────────────────────────

def _drive_match_score(
    current: Dict[str, float],
    profile: Dict[str, float],
) -> float:
    """当前驱动力状态和构式驱动力画像的匹配度（余弦相似度）。"""
    if not profile:
        return 0.5

    dot = 0.0
    norm_c = 0.0
    norm_p = 0.0
    for dim in profile:
        c = max(0.0, min(1.0, float(current.get(dim, 0.5))))
        p = max(0.0, min(1.0, float(profile[dim])))
        dot += c * p
        norm_c += c * c
        norm_p += p * p

    denom = math.sqrt(max(norm_c, 1e-9)) * math.sqrt(max(norm_p, 1e-9))
    return dot / denom
