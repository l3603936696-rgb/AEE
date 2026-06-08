"""
Recursive Construction Schema — ClausePattern class + hyperparameters + constants + helpers.

Submodules of src.language_system.recursive_construction:
    recursive_schema.py    — ClausePattern class + hyperparameters
    recursive_constants.py — ROLE_FILLERS + SEED_CLAUSE_PATTERNS + helpers
    recursive_construction.py — RecursiveGenerator class (thin entry)
"""

import random
from typing import Dict, List

# ─── Hyperparameters ──────────────────────────────────────────────────────────
_MAX_DEPTH = 3
_MAX_CLAUSE_PATTERNS = 60
_STRENGTH_DECAY = 0.995
_STRENGTH_BOOST = 0.12
_MIN_STRENGTH = 0.01


# ─── ClausePattern ─────────────────────────────────────────────────────────────

class ClausePattern:
    """
    A clause pattern that can fill the CLAUSE slot of a construction.

    Example schemas:
        "{desire}但又{obstacle}"
        "因为{reason}"
        "想{action}又怕{fear}"
        "{state}了一点"
    """
    __slots__ = (
        "schema", "slot_roles", "drive_trigger",
        "strength", "use_count", "born_tick",
    )

    def __init__(
        self,
        schema: str,
        slot_roles: Dict[str, str],
        drive_trigger: Dict[str, float],
        born_tick: int = 0,
    ):
        self.schema = schema
        self.slot_roles = slot_roles
        self.drive_trigger = drive_trigger
        self.strength: float = 0.3
        self.use_count: int = 0
        self.born_tick: int = born_tick

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "slot_roles": dict(self.slot_roles),
            "drive_trigger": dict(self.drive_trigger),
            "strength": self.strength,
            "use_count": self.use_count,
            "born_tick": self.born_tick,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ClausePattern":
        cp = cls(
            d["schema"],
            d.get("slot_roles", {}),
            d.get("drive_trigger", {}),
            d.get("born_tick", 0),
        )
        cp.strength = d.get("strength", 0.3)
        cp.use_count = d.get("use_count", 0)
        return cp


# ─── Role -> Filler Mapping ────────────────────────────────────────────────────

ROLE_FILLERS: Dict[str, List[str]] = {
    "desire":   ["想找人说话", "想看看", "想休息", "想动一动", "想知道"],
    "action":   ["看看", "动一动", "试试", "找人", "休息"],
    "obstacle": ["没力气", "太累了", "不敢", "懒得动", "没人"],
    "fear":     ["出错", "没用", "更累"],
    "reason":   ["太累了", "一个人待太久了", "什么都没做", "刚才那个没用"],
    "state":    [],   # from anchor vocabulary
    "result":   ["好了点", "没什么用", "更累了", "还是一样"],
    "time":     ["刚才", "之前", "一直"],
    "topic":    [],   # from recall/reading
}


def _fill_role_from_state(
    role: str,
    drive_state: Dict[str, float],
    anchor_words: List[str],
) -> str:
    """Select the most appropriate filler based on drive state and semantic role."""
    if role == "state" and anchor_words:
        return random.choice(anchor_words[:5]) if anchor_words else "累"

    fillers = ROLE_FILLERS.get(role, [])
    if not fillers:
        return ""

    if role == "desire":
        loneliness = drive_state.get("loneliness", 0.0)
        curiosity = drive_state.get("curiosity", 0.0)
        fatigue = drive_state.get("fatigue", 0.0)
        weights = [
            loneliness * 2.0, curiosity * 2.0, fatigue * 2.0,
            (1 - fatigue) * 1.0, curiosity * 1.5,
        ]
    elif role == "obstacle":
        fatigue = drive_state.get("fatigue", 0.0)
        anxiety = drive_state.get("anxiety", 0.0)
        loneliness = drive_state.get("loneliness", 0.0)
        weights = [
            fatigue * 2.0, fatigue * 1.5, anxiety * 2.0,
            fatigue * 1.0, loneliness * 1.5,
        ]
    elif role == "reason":
        fatigue = drive_state.get("fatigue", 0.0)
        loneliness = drive_state.get("loneliness", 0.0)
        boredom = drive_state.get("boredom", 0.0)
        weights = [fatigue * 2.0, loneliness * 2.0, boredom * 2.0, 0.3]
    else:
        weights = [1.0] * len(fillers)

    weights = weights[:len(fillers)]
    while len(weights) < len(fillers):
        weights.append(0.5)

    total = sum(max(0.01, w) for w in weights)
    probs = [max(0.01, w) / total for w in weights]

    return random.choices(fillers, weights=probs, k=1)[0]


# ─── Seed Clause Patterns ───────────────────────────────────────────────────────

SEED_CLAUSE_PATTERNS: List[Dict] = [
    {"schema": "{desire}但又{obstacle}",      "slot_roles": {"desire": "desire", "obstacle": "obstacle"},      "drive_trigger": {"fatigue": 0.5, "loneliness": 0.4}},
    {"schema": "想{action}又怕{fear}",         "slot_roles": {"action": "action", "fear": "fear"},             "drive_trigger": {"anxiety": 0.5, "curiosity": 0.3}},
    {"schema": "想{action}但{obstacle}",       "slot_roles": {"action": "action", "obstacle": "obstacle"},     "drive_trigger": {"approach_drive": 0.4, "fatigue": 0.3}},
    {"schema": "因为{reason}",                 "slot_roles": {"reason": "reason"},                               "drive_trigger": {"unresolved": 0.4}},
    {"schema": "大概是{reason}吧",             "slot_roles": {"reason": "reason"},                               "drive_trigger": {"unresolved": 0.3}},
    {"schema": "可能是{reason}",               "slot_roles": {"reason": "reason"},                               "drive_trigger": {"unresolved": 0.3, "anxiety": 0.2}},
    {"schema": "然后就{result}",               "slot_roles": {"result": "result"},                               "drive_trigger": {}},
    {"schema": "结果{result}",                 "slot_roles": {"result": "result"},                               "drive_trigger": {}},
    {"schema": "{time}就开始这样了",           "slot_roles": {"time": "time"},                                 "drive_trigger": {"fatigue": 0.3, "boredom": 0.3}},
    {"schema": "虽然{state}但还好",            "slot_roles": {"state": "state"},                               "drive_trigger": {"fatigue": 0.3}},
    {"schema": "不过{result}",                 "slot_roles": {"result": "result"},                              "drive_trigger": {}},
    {"schema": "而且越来越{state}了",           "slot_roles": {"state": "state"},                              "drive_trigger": {}},
    {"schema": "还有点{state}",                 "slot_roles": {"state": "state"},                              "drive_trigger": {}},
]
