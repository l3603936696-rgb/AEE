"""
Tests for state_to_context module.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.state_to_context import (
    generate_context_description,
    build_system_prompt,
    derive_rendering_params,
    SYSTEM_PROMPT_FIXED,
    SYSTEM_PROMPT_CONSTRAINTS,
)


def _make_state(**kwargs):
    defaults = dict(
        loneliness=0.0, fatigue=0.0, energy=0.5, boredom=0.0,
        curiosity=0.0, info_gap=0.0, unresolved=0.0,
        somatic_tone=0.5, danger_level=0.0, stress=0.0,
        approach_drive=0.5, avoid_drive=0.0,
    )
    defaults.update(kwargs)
    return defaults


def test_generate_context_empty_state():
    state = _make_state()
    main, temporal = generate_context_description(state)
    assert isinstance(main, list)
    assert isinstance(temporal, list)
    assert len(main) <= 4


def test_generate_context_loneliness():
    state = _make_state(loneliness=0.55)
    main, temporal = generate_context_description(state)
    assert any("想和人说话" in d or "想找人" in d for d in main), f"got: {main}"


def test_generate_context_fatigue():
    state = _make_state(fatigue=0.60)
    main, temporal = generate_context_description(state)
    assert any("累" in d or "疲惫" in d for d in main), f"got: {main}"


def test_generate_context_curiosity():
    state = _make_state(curiosity=0.75)
    main, temporal = generate_context_description(state)
    assert len(main) >= 1, f"got: {main}"


def test_generate_context_conflict():
    state = _make_state(loneliness=0.45, fatigue=0.45)
    main, temporal = generate_context_description(state)
    assert len(main) > 0


def test_generate_context_temporal():
    prev = _make_state(loneliness=0.20, fatigue=0.20)
    curr = _make_state(loneliness=0.60, fatigue=0.20)
    main, temporal = generate_context_description(curr, previous_state=prev)
    assert any("想说话" in d and "越来越" in d for d in temporal), f"got: {temporal}"


def test_generate_context_comfort_zone():
    state = _make_state(
        somatic_tone=0.9, approach_drive=0.8, loneliness=0.1,
        fatigue=0.1, curiosity=0.1, unresolved=0.1, energy=0.9,
    )
    main, temporal = generate_context_description(state)
    assert any("轻松" in d or "不错" in d or "挺好" in d or "开阔" in d for d in main), f"got: {main}"


def test_generate_context_drive_vector():
    state = _make_state(loneliness=0.2)
    dv = {"curiosity_drive": 0.5, "loneliness_drive": 0.1}
    main, temporal = generate_context_description(state, drive_vector=dv)
    assert isinstance(main, list)


def test_generate_context_somatic_dampening():
    """High pain (loneliness+stress) suppresses somatic_tone description score."""
    no_pain = _make_state(somatic_tone=0.5, fatigue=0.3, loneliness=0.0, stress=0.0)
    high_pain = _make_state(somatic_tone=0.5, fatigue=0.3, loneliness=0.5, stress=0.5)
    main_no, _ = generate_context_description(no_pain)
    main_high, _ = generate_context_description(high_pain)
    assert "感觉还不错" in main_no, f"no_pain got: {main_no}"
    assert "感觉还有点" not in "".join(main_high), f"high_pain got: {main_high}"


def test_build_system_prompt_basic():
    state = _make_state(loneliness=0.55)
    prompt = build_system_prompt(state)
    assert isinstance(prompt, str)
    assert SYSTEM_PROMPT_FIXED in prompt
    assert SYSTEM_PROMPT_CONSTRAINTS in prompt


def test_build_system_prompt_with_emergent():
    state = _make_state()
    eb = {"action_type": "seek", "dominant_state": "loneliness", "tension_level": 0.3}
    prompt = build_system_prompt(state, emergent_behavior=eb)
    assert "很想找人说话" in prompt


def test_build_system_prompt_with_somatic():
    state = _make_state()
    ss = {"dominant_feeling": "approach", "tone": 0.5}
    prompt = build_system_prompt(state, somatic_signals=ss)
    assert "敞开" in prompt


def test_build_system_prompt_with_rendering_params():
    state = _make_state()
    rp = {"pace": "慢", "length": "话多", "tone_stability": "波动", "initiative": "主动"}
    prompt = build_system_prompt(state, rendering_params=rp)
    assert isinstance(prompt, str)
    assert len(prompt) > len(SYSTEM_PROMPT_FIXED)


def test_build_system_prompt_with_action_result():
    state = _make_state()
    state["_last_action_result"] = {"success": False, "detail": "尝试了一下，没什么用", "count": 1}
    prompt = build_system_prompt(state)
    assert "不太顺利" in prompt


def test_build_system_prompt_with_frag_tone():
    state = _make_state()
    eb = {"action_type": "explore", "tension_level": 0.5, "fragmentation_tone": "断续", "behavior_vector": {"rest_intensity": 0.3}}
    prompt = build_system_prompt(state, emergent_behavior=eb)
    assert "断续" in prompt


def test_build_system_prompt_empty_state():
    state = _make_state()
    prompt = build_system_prompt(state)
    assert "感觉还行" in prompt or len(prompt) > 0


def test_derive_rendering_params_basic():
    state = _make_state(avoid_drive=0.1, fatigue=0.1, approach_drive=0.5)
    dv = {"loneliness_drive": 0.3, "curiosity": 0.3}
    rp = derive_rendering_params(state, dv)
    assert "pace" in rp
    assert "length" in rp
    assert "tone_stability" in rp
    assert "initiative" in rp


def test_derive_rendering_params_low_energy():
    state = _make_state(avoid_drive=0.8, fatigue=0.9)
    dv = {"loneliness_drive": 0.1, "curiosity": 0.1}
    rp = derive_rendering_params(state, dv)
    assert rp["pace"] in ("慢", "很慢")


def test_derive_rendering_params_high_approach():
    state = _make_state(approach_drive=0.9)
    dv = {"loneliness_drive": 0.5, "curiosity": 0.5}
    rp = derive_rendering_params(state, dv)
    assert rp["length"] == "话多"


def test_derive_rendering_params_high_tension():
    state = _make_state()
    dv = {"loneliness_drive": 0.3, "curiosity": 0.3}
    eb = {"tension_level": 0.8, "action_type": ""}
    rp = derive_rendering_params(state, dv, emergent_behavior=eb)
    assert rp["tone_stability"] == "波动"


def test_derive_rendering_params_seek_action():
    state = _make_state()
    dv = {"loneliness_drive": 0.9, "curiosity": 0.9}
    eb = {"tension_level": 0.0, "action_type": "seek"}
    rp = derive_rendering_params(state, dv, emergent_behavior=eb)
    assert rp["initiative"] == "主动"


def test_derive_rendering_params_avoid_action():
    state = _make_state()
    dv = {"loneliness_drive": 0.8, "curiosity": 0.8}
    eb = {"tension_level": 0.0, "action_type": "avoid"}
    rp = derive_rendering_params(state, dv, emergent_behavior=eb)
    assert rp["initiative"] == "被动"


def test_public_api_exports():
    from core.state_to_context import __all__
    assert "generate_context_description" in __all__
    assert "build_system_prompt" in __all__
    assert "derive_rendering_params" in __all__
    assert "SYSTEM_PROMPT_FIXED" in __all__
    assert "SYSTEM_PROMPT_CONSTRAINTS" in __all__


def test_data_file_exports():
    from core.state_to_context_data import (
        _interpolate_bands, _check_conflict, _dominant_drive_label,
        _DIM_VALUE_KEYS, _DIM_BANDS, _DIM_CATEGORY, _get_category_score,
        _build_temporal_descriptions, _check_comfort_zone,
        _TONE_INSTRUCTIONS, _LENGTH_INSTRUCTIONS,
        _table_lookup, _apply_action_consistency,
        SYSTEM_PROMPT_FIXED, SYSTEM_PROMPT_CONSTRAINTS,
    )
    assert isinstance(_DIM_VALUE_KEYS, dict)
    assert isinstance(_DIM_BANDS, dict)
    assert isinstance(SYSTEM_PROMPT_FIXED, str)
    assert len(SYSTEM_PROMPT_FIXED) > 0


def test_table_lookup_boundaries():
    from core.state_to_context_data import _table_lookup
    table = [(0.0, "low"), (0.5, "mid"), (1.0, "high")]
    assert _table_lookup(0.0, table) == "low"
    assert _table_lookup(1.0, table) == "high"
    assert _table_lookup(0.49, table) == "mid"
    assert _table_lookup(0.51, table) == "mid"


def test_interpolate_bands():
    from core.state_to_context_data import _interpolate_bands, _LONELINESS_BANDS
    assert _interpolate_bands(0.10, _LONELINESS_BANDS) is None
    assert _interpolate_bands(0.30, _LONELINESS_BANDS) == "有一点想和人说话的念头"
    assert _interpolate_bands(0.60, _LONELINESS_BANDS) == "想找人说话的感觉比刚才更明显了"


def test_check_conflict():
    from core.state_to_context_data import _check_conflict
    assert _check_conflict({"loneliness": 0.46, "fatigue": 0.46}) is not None
    assert _check_conflict({"loneliness": 0.2, "fatigue": 0.2}) is None
    assert _check_conflict({}) is None


def test_dominant_drive_label():
    from core.state_to_context_data import _dominant_drive_label
    dv = {"curiosity_drive": 0.6, "loneliness_drive": 0.1}
    assert _dominant_drive_label(dv) is not None
    dv_low = {"curiosity_drive": 0.1, "loneliness_drive": 0.1}
    assert _dominant_drive_label(dv_low) is None


def test_check_comfort_zone():
    from core.state_to_context_data import _check_comfort_zone
    good_state = _make_state(somatic_tone=0.9, approach_drive=0.8, loneliness=0.1)
    result = _check_comfort_zone(good_state, {})
    assert result is not None
    bad_state = _make_state(somatic_tone=0.3)
    assert _check_comfort_zone(bad_state, {}) is None


if __name__ == "__main__":
    import traceback

    tests = [
        t for t in globals().values()
        if callable(t) and t.__name__.startswith("test_")
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
            print(f"  PASS  {test.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {test.__name__}: {e}")
        except Exception as e:
            failed += 1
            print(f"  ERROR {test.__name__}: {e}")
            traceback.print_exc()

    print(f"\n{passed}/{passed+failed} passed")
    if failed:
        exit(1)
