"""Tests for the minimal proposition-frame language representation."""

from AEE.src.language_system.proposition_frame import build_proposition_frame
from AEE.src.language_system.syntax_parser import parse_svo


def _frame(text: str) -> dict:
    return build_proposition_frame(text, parse_svo(text))


def test_role_reversal_changes_actor_and_patient():
    speaker = _frame("我担心你。")
    xia = _frame("你担心我。")
    assert (speaker["actor"], speaker["patient"]) == ("speaker", "xia")
    assert (xia["actor"], xia["patient"]) == ("xia", "speaker")


def test_single_negation_and_double_negation_are_distinct():
    positive = _frame("我担心你。")
    negative = _frame("我不担心你。")
    double_negative = _frame("我不是不担心你。")
    assert positive["polarity"] == "positive"
    assert negative["polarity"] == "negative"
    assert double_negative["polarity"] == "positive"
    assert double_negative["negation_count"] == 2


def test_tense_markers_are_exposed():
    assert _frame("我昨天担心你。")["tense"] == "past"
    assert _frame("我今天担心你。")["tense"] == "present"
    assert _frame("我明天来看你。")["tense"] == "future"


def test_conditional_outweighs_question_modality():
    frame = _frame("如果我走了，你会难过吗？")
    assert frame["modality"] == "conditional"


def test_unknown_slots_keep_low_confidence():
    # 裸代词填充的槽（指代悬空）保持低置信；命名实体已落地（见 test_named_external_slot_grounded）。
    frame = _frame("它描述了那个")
    assert frame["slot_confidence"]["actor"] < frame["slot_confidence"]["predicate"]
    assert frame["slot_confidence"]["patient"] < frame["slot_confidence"]["predicate"]


def test_named_external_slot_grounded():
    # Risk-1 修复：清楚命名的外部主语（光合作用）落地 → 高置信，不再被误判成理解缺口
    # 而乱问"是谁"；裸代词（它）仍悬空 → 低置信 → 仍该问。
    frame = _frame("光合作用把二氧化碳变成糖")
    assert frame["slot_confidence"]["actor"] > 0.8
    frame2 = _frame("它把那个弄坏了")
    assert frame2["slot_confidence"]["actor"] < 0.3


def test_referential_placeholder_not_grounded():
    # GPT P2：指称占位词（有人/某个/什么）不能与命名实体一样算落地，仍该追问。
    frame = _frame("有人做了一件事")
    assert frame["slot_confidence"]["actor"] < 0.3


def test_absent_time_slot_is_not_relevant():
    assert _frame("我担心你。")["slot_relevance"]["tense"] == 0.0
    assert _frame("我昨天担心你。")["slot_relevance"]["tense"] == 1.0
