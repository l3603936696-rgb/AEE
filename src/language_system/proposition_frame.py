"""Minimal proposition frame for inspectable language understanding."""

from __future__ import annotations

from typing import Dict


_TENSE_MARKERS = {
    "past": ("昨天", "刚才", "之前", "以前"),
    "present": ("今天", "现在", "正在"),
    "future": ("明天", "以后", "将会"),
}
_CONDITIONAL_MARKERS = ("如果", "假如", "要是")
_NEGATION_MARKERS = ("不", "没", "未", "别", "莫", "勿")

_KNOWN_SLOT_CONFIDENCE = 0.95
_INFERRED_SLOT_CONFIDENCE = 0.70
_UNKNOWN_SLOT_CONFIDENCE = 0.10
_DIRECTION_CONFIDENCE = {
    "speaker": _KNOWN_SLOT_CONFIDENCE,
    "xia": _KNOWN_SLOT_CONFIDENCE,
    "external": _UNKNOWN_SLOT_CONFIDENCE,
}

# 裸代词（封闭类词汇事实，非行为规则）：充当槽位填充却不提供具体指称的占位词。
# 命名实体（光合作用/线粒体）= 已落地，不该追问"是谁"；裸代词（它/他）= 指称悬空，该追问。
# 与"我=speaker、你=xia"同类：是词汇事实，不是 if/else 行为门控。
_PRONOUN_FILLERS = (
    "它", "他", "她", "它们", "他们", "她们", "你们", "咱们",
    "这", "那", "这个", "那个", "这些", "那些", "其", "之",
)

# 指称占位词（封闭类词汇事实，与代词同处理）：填了槽却不给具体指称的不定/疑问词。
# "有人/某个/什么"= 指称悬空，该追问；不能与命名实体（光合作用）一样算落地（GPT P2：修过宽）。
_REFERENTIAL_PLACEHOLDERS = (
    "谁", "什么", "哪", "哪个", "哪些", "有人", "某人", "某个", "某些",
    "东西", "一些", "一点", "怎么", "如何",
)

_UNGROUNDED_FILLERS = frozenset(_PRONOUN_FILLERS) | frozenset(_REFERENTIAL_PLACEHOLDERS)


def _presence_weight(value: str) -> float:
    return min(1.0, float(len(str(value or ""))))


def _filler_groundedness(filler: str) -> float:
    """外部指称的落地度 ∈ [0,1]：命名实体→1，裸代词/指称占位词/空→0。
    连续，用 parse_svo 已抽出的填充文本。"""
    text = str(filler or "").strip()
    presence = min(1.0, float(len(text)))
    is_ungrounded = float(text in _UNGROUNDED_FILLERS)
    return presence * (1.0 - is_ungrounded)


def _slot_referent_confidence(direction: str, filler: str) -> float:
    """槽位置信度 = "我知不知道这个槽指什么"，而非"是不是我/你"。

    speaker/xia → 她天然知道指代（0.95）；external → 看填充是否具体命名实体
    （落地→高 0.95；裸代词/空→低 0.10）。取代旧的"external 一律 0.10"——那会把清楚
    命名的外部实体（光合作用）误判成理解缺口，使她对命名乱问"是谁"（Risk 1 病灶）。
    """
    speaker_xia = _DIRECTION_CONFIDENCE.get(direction, 0.0) * float(direction in ("speaker", "xia"))
    grounded = _UNKNOWN_SLOT_CONFIDENCE + _filler_groundedness(filler) * (
        _KNOWN_SLOT_CONFIDENCE - _UNKNOWN_SLOT_CONFIDENCE
    )
    return max(speaker_xia, grounded)


def _marker_weight(text: str, markers: tuple[str, ...]) -> float:
    return min(1.0, float(sum(text.count(marker) for marker in markers)))


def _pick_weighted_label(weights: Dict[str, float], fallback: str) -> str:
    ranked = {**weights, fallback: max(weights.get(fallback, 0.0), _UNKNOWN_SLOT_CONFIDENCE)}
    return max(ranked, key=ranked.get)


def _inferred_presence_confidence(value: str) -> float:
    return _UNKNOWN_SLOT_CONFIDENCE + _presence_weight(value) * (
        _INFERRED_SLOT_CONFIDENCE - _UNKNOWN_SLOT_CONFIDENCE
    )


def build_proposition_frame(text: str, svo: Dict) -> Dict:
    """Build an inspectable semantic skeleton without changing entity state."""
    raw = str(text or "")
    tense_weights = {
        tense: _marker_weight(raw, markers)
        for tense, markers in _TENSE_MARKERS.items()
    }
    negation_count = sum(raw.count(marker) for marker in _NEGATION_MARKERS)
    polarity = ("positive", "negative")[negation_count % 2]
    question_weight = float(bool(svo.get("question", False)))
    conditional_weight = _marker_weight(raw, _CONDITIONAL_MARKERS)
    modality = _pick_weighted_label(
        {
            "conditional": conditional_weight,
            "question": question_weight * (1.0 - conditional_weight),
            "statement": (1.0 - question_weight) * (1.0 - conditional_weight),
        },
        "unknown",
    )
    tense = _pick_weighted_label(tense_weights, "unspecified")
    actor = str(svo.get("agent_dir", "external"))
    predicate = str(svo.get("predicate", ""))
    patient = str(svo.get("patient_dir", "external"))
    slot_relevance = {
        "actor": _presence_weight(svo.get("subject", "")),
        "predicate": _presence_weight(predicate),
        "patient": _presence_weight(svo.get("object", "")),
        "tense": max(tense_weights.values(), default=0.0),
    }
    return {
        "actor": actor,
        "predicate": predicate,
        "patient": patient,
        "polarity": polarity,
        "negation_count": negation_count,
        "tense": tense,
        "modality": modality,
        "slot_relevance": slot_relevance,
        "slot_confidence": {
            "actor": _slot_referent_confidence(actor, svo.get("subject", "")),
            "predicate": _inferred_presence_confidence(predicate),
            "patient": _slot_referent_confidence(patient, svo.get("object", "")),
            "polarity": _INFERRED_SLOT_CONFIDENCE,
            "tense": _UNKNOWN_SLOT_CONFIDENCE + max(tense_weights.values(), default=0.0) * (
                _KNOWN_SLOT_CONFIDENCE - _UNKNOWN_SLOT_CONFIDENCE
            ),
            "modality": _INFERRED_SLOT_CONFIDENCE,
        },
    }
