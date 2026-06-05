"""Tests for honest clarification expression candidates."""

from types import SimpleNamespace

from src.pipeline_runner.stages.s02c_delayed_understanding import (
    _FAMILIARITY_FLOOR,
    _familiarity_coverage,
    run_stage,
)
from src.language_system.uncertainty_expression import (
    compute_understanding_uncertainty,
    get_uncertainty_patterns,
    inject_proposition_uncertainty,
)


def test_uncertainty_only_applies_to_current_input():
    assert compute_understanding_uncertainty(0.2, "") == 0.0
    assert compute_understanding_uncertainty(0.2, "陌生输入") > 0.0


def test_opaque_input_scores_clarification_above_mild_uncertainty():
    patterns = get_uncertainty_patterns()
    opaque = {"_understanding_uncertainty": (1.0 - 0.2) ** 2, "curiosity": 0.5}
    familiar = {"_understanding_uncertainty": (1.0 - 0.8) ** 2, "curiosity": 0.5}
    assert min(p["score_fn"](opaque) for p in patterns) > 0.0
    assert max(p["score_fn"](familiar) for p in patterns) < 0.0


def test_mid_confidence_is_suppressed_relative_to_opaque_input():
    pattern = get_uncertainty_patterns()[0]
    opaque = pattern["score_fn"]({"_understanding_uncertainty": (1.0 - 0.2) ** 2})
    partial = pattern["score_fn"]({"_understanding_uncertainty": (1.0 - 0.52) ** 2})
    assert opaque > partial


def test_familiarity_coverage_distinguishes_known_words_from_opaque_terms():
    entity = SimpleNamespace(
        _unlocked_vocabulary=["我", "你", "担心"],
        _word_exposure_tracker={},
    )
    assert _familiarity_coverage("我担心你", entity) == 1.0
    assert _familiarity_coverage("量子纠缠导致退相干", entity) == 0.0


def test_familiarity_floor_is_calibrated_for_honest_uncertainty():
    assert _FAMILIARITY_FLOOR == 0.20


def test_delayed_understanding_exposes_confidence_to_output_state():
    winner = SimpleNamespace(interpretation="陌生术语")
    competition = SimpleNamespace(tension_type="attractor", winner=winner)
    entity = SimpleNamespace(
        tick=1,
        _last_interpretation_result=competition,
        _last_tension_level=0.1,
        _pending_understandings=[],
        _unlocked_vocabulary=[],
        _word_exposure_tracker={},
    )
    ctx = SimpleNamespace(
        raw_input="量子纠缠导致退相干",
        _interpretation_result=competition,
        _tension_level=0.1,
        _trace=lambda *args, **kwargs: None,
    )
    run_stage(ctx, entity)
    assert entity._understanding_confidence == ctx._understanding_confidence
    assert entity._understanding_confidence < 0.3


def test_absent_slots_do_not_create_targeted_questions():
    state = {"_understanding_uncertainty": 0.9}
    inject_proposition_uncertainty(state, {
        "slot_confidence": {"patient": 0.1},
        "slot_relevance": {"patient": 0.0},
    })
    assert state["_slot_uncertainty_patient"] == 0.0


def test_uncertain_relevant_patient_raises_targeted_question():
    state = {"_understanding_uncertainty": 0.9}
    inject_proposition_uncertainty(state, {
        "slot_confidence": {"patient": 0.1},
        "slot_relevance": {"patient": 1.0},
    })
    patient_pattern = get_uncertainty_patterns()[3]
    assert state["_slot_uncertainty_patient"] > 0.0
    assert patient_pattern["score_fn"](state) > 0.0
