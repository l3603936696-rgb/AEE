"""Continuous uncertainty signal and clarification expression candidates."""

from typing import Dict, List, Optional


# Seed values for calibration. Squaring separates mildly unfamiliar input from
# genuinely opaque input without adding a threshold gate.
UNCERTAINTY_POWER = 2.0
# Probe-calibrated seeds: confidence=0.20 yields clarification in roughly half
# of samples, while confidence=0.52 remains below one percent.
CLARIFY_SCORE_BASE = -1.5
CLARIFY_SCORE_GAIN = 5.0
CLARIFY_CURIOSITY_GAIN = 0.08
SLOT_CLARIFY_SCORE_BASE = -1.7
SLOT_CLARIFY_GLOBAL_GAIN = 3.0
SLOT_CLARIFY_LOCAL_GAIN = 2.0


def compute_understanding_uncertainty(confidence: float, input_text: str) -> float:
    """Map current-input confidence to a bounded uncertainty signal."""
    input_gate = min(1.0, float(len(str(input_text or ""))))
    bounded_confidence = max(0.0, min(1.0, float(confidence)))
    return input_gate * (1.0 - bounded_confidence) ** UNCERTAINTY_POWER


def inject_understanding_uncertainty(entity, state: Dict, input_text: str) -> None:
    """Expose uncertainty to expression scoring for the current input only."""
    state["_understanding_uncertainty"] = compute_understanding_uncertainty(
        getattr(entity, "_understanding_confidence", 0.5),
        input_text,
    )


def inject_proposition_uncertainty(state: Dict, proposition_frame: Dict) -> None:
    """Expose uncertain parsed slots without treating absent slots as errors.

    局部槽缺口 = relevance × (1-conf)，**不再乘全局陌生度**（GPT 开放问题2：解耦——
    悬空代词即使在熟悉句里也该可被追问；误触发由 _slot_score 的低先验 SLOT_CLARIFY_SCORE_BASE 控制）。
    """
    confidence = proposition_frame.get("slot_confidence", {})
    relevance = proposition_frame.get("slot_relevance", {})
    for slot in ("actor", "predicate", "patient"):
        state[f"_slot_uncertainty_{slot}"] = (
            float(relevance.get(slot, 0.0))
            * (1.0 - float(confidence.get(slot, 0.0)))
        )


def _slot_score(state: Dict, slot: str) -> float:
    return (
        SLOT_CLARIFY_SCORE_BASE
        + state.get("_understanding_uncertainty", 0.0) * SLOT_CLARIFY_GLOBAL_GAIN
        + state.get(f"_slot_uncertainty_{slot}", 0.0) * SLOT_CLARIFY_LOCAL_GAIN
    )


def get_uncertainty_patterns() -> List[Dict]:
    """Return low-prior clarification candidates for sentence composition."""
    return [
        {
            "template": "这句……我没太懂",
            "score_fn": lambda s: (
                CLARIFY_SCORE_BASE
                + s.get("_understanding_uncertainty", 0.0) * CLARIFY_SCORE_GAIN
            ),
            "use_connector": False,
            "anchor_pos": "none",
            "clarification_kind": "generic",
            "clarification_slot": None,
        },
        {
            "template": "是说什么呢……",
            "score_fn": lambda s: (
                CLARIFY_SCORE_BASE
                + s.get("_understanding_uncertainty", 0.0) * CLARIFY_SCORE_GAIN
                + s.get("curiosity", 0.0) * CLARIFY_CURIOSITY_GAIN
            ),
            "use_connector": False,
            "anchor_pos": "none",
            "clarification_kind": "generic",
            "clarification_slot": None,
        },
        {
            "template": "是谁在这样呢……",
            "score_fn": lambda s: _slot_score(s, "actor"),
            "use_connector": False,
            "anchor_pos": "none",
            "clarification_kind": "targeted",
            "clarification_slot": "actor",
        },
        {
            "template": "你说的是谁，或者什么呢……",
            "score_fn": lambda s: _slot_score(s, "patient"),
            "use_connector": False,
            "anchor_pos": "none",
            "clarification_kind": "targeted",
            "clarification_slot": "patient",
        },
        {
            "template": "你说的这是怎么回事呢……",
            "score_fn": lambda s: _slot_score(s, "predicate"),
            "use_connector": False,
            "anchor_pos": "none",
            "clarification_kind": "targeted",
            "clarification_slot": "predicate",
        },
    ]

_VALID_CLARIFICATION_META = frozenset({
    ("generic", None),
    ("targeted", "actor"),
    ("targeted", "patient"),
    ("targeted", "predicate"),
})


def clarification_meta(template: Dict) -> Optional[Dict]:
    """
    给定模板 dict，返回澄清 metadata ``{"kind": ..., "slot": ...}``，
    或 ``None``（非澄清模板）。

    直接读模板自带的内联元数据（单一真相源：随模板走，对文案编辑鲁棒）。
    非澄清模板（无 ``clarification_kind`` 键）返回 None。
    """
    if not isinstance(template, dict):
        return None
    kind = template.get("clarification_kind")
    slot = template.get("clarification_slot")
    if (kind, slot) not in _VALID_CLARIFICATION_META:
        return None
    return {"kind": kind, "slot": slot}
