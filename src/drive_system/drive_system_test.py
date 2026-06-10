"""
Inline tests extracted from drive_system.py.

Run with: python -m src.drive_system.drive_system_test
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from AEE.src.drive_system.drive_system import compute_drive_vector
from AEE.src.drive_system.drive_system_helpers import (
    interpolate_lookup, sigmoid_curve, DriveVector, ShapeTable,
    _compute_curiosity, _compute_info_hunger,
    _compute_loneliness_drive, _compute_fatigue_avoid,
    _compute_obsolescence_anxiety,
    apply_affect_multiplier,
)


# =============================================================================
# Test data
# =============================================================================

DEFAULT_PARAMS = {
    "curiosity_param": 1.0,
    "max_info_gap_hours": 24.0,
    "max_social_gap_hours": 24.0,
    "info_hunger_time_shape": {
        "x_anchors": [0.0, 0.3, 0.8, 1.0, 2.0, 5.0],
        "y_anchors": [0.0, 0.02, 0.15, 0.60, 0.85, 0.99]
    },
    "social_time_shape": {
        "x_anchors": [0.0, 0.5, 1.0, 2.0, 4.0],
        "y_anchors": [0.0, 0.05, 0.30, 0.70, 0.98]
    },
    "loneliness_shape": {
        "x_anchors": [0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
        "y_anchors": [0.0, 0.01, 0.05, 0.15, 0.45, 1.0]
    },
    "fatigue_shape": {
        "x_anchors": [0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
        "y_anchors": [0.0, 0.02, 0.08, 0.20, 0.50, 1.0]
    },
    "change_shape": {
        "x_anchors": [0.0, 0.25, 0.5, 0.75, 1.0],
        "y_anchors": [0.0, 0.05, 0.20, 0.55, 1.0]
    },
    "debt_shape": {
        "x_anchors": [0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
        "y_anchors": [0.0, 0.01, 0.05, 0.15, 0.40, 1.0]
    },
}


# =============================================================================
# interpolate_lookup tests
# =============================================================================

def test_interpolate_lookup():
    x_anchors = [0.0, 0.5, 1.0]
    y_anchors = [0.0, 0.5, 1.0]

    cases = [
        (-0.5, 0.0, "lower bound clamp"),
        (0.0, 0.0, "lower boundary"),
        (0.25, 0.25, "inner interpolation"),
        (0.5, 0.5, "midpoint"),
        (0.75, 0.75, "inner interpolation"),
        (1.0, 1.0, "upper boundary"),
        (1.5, 1.0, "upper bound clamp"),
    ]
    for x, expected, desc in cases:
        result = interpolate_lookup(x, x_anchors, y_anchors)
        ok = abs(result - expected) < 1e-6
        print(f"  {'PASS' if ok else 'FAIL'} interpolate_lookup({x}) = {result:.4f} ({desc})")


def test_sigmoid_curve():
    cases = [
        (0.0, 0.38, "x=0 baseline"),
        (0.5, 0.50, "x=0.5 midpoint"),
        (1.0, 0.62, "x=1 upper"),
    ]
    for x, expected, desc in cases:
        result = sigmoid_curve(x, 1.0)
        ok = abs(result - expected) < 0.02
        print(f"  {'PASS' if ok else 'FAIL'} sigmoid_curve({x}) = {result:.4f} ({desc})")


# =============================================================================
# Drive computation tests
# =============================================================================

def test_compute_drive_vector():
    cases = [
        ("all zeros", {},
         {"all_zeros": True}),
        ("None params", {"info_gap": 0.5},
         {"all_zeros": True}),
        ("info_gap=0 -> curiosity=0 (power formula: 0^x=0)", {"info_gap": 0.0, "time_since_last_info": 0.0,
            "loneliness": 0.0, "time_since_last_social": 0.0, "energy": 1.0,
            "external_change_rate": 0.0, "unresolved": 0.0},
         {"curiosity_near": 0.0}),
        ("info_gap=1.0 -> curiosity=1.0 (power formula: 1^1=1)", {"info_gap": 1.0, "time_since_last_info": 86400.0,
            "loneliness": 0.0, "time_since_last_social": 0.0, "energy": 1.0,
            "external_change_rate": 0.0, "unresolved": 0.0},
         {"curiosity_near": 1.0, "info_hunger_near": 0.6}),
        ("loneliness=1 + 24h no social -> loneliness_drive>0",
         {"info_gap": 0.0, "time_since_last_info": 0.0,
          "loneliness": 1.0, "time_since_last_social": 86400.0,
          "energy": 1.0, "external_change_rate": 0.0, "unresolved": 0.0},
         {"loneliness_drive_high": True}),
        ("energy=0 -> fatigue_avoid=1.0",
         {"info_gap": 0.0, "time_since_last_info": 0.0,
          "loneliness": 0.0, "time_since_last_social": 0.0,
          "energy": 0.0, "external_change_rate": 0.0, "unresolved": 0.0},
         {"fatigue_avoid_near": 1.0}),
        ("change=1 + unresolved=1 -> obsolescence_anxiety~1.0",
         {"info_gap": 0.0, "time_since_last_info": 0.0,
          "loneliness": 0.0, "time_since_last_social": 0.0,
          "energy": 1.0, "external_change_rate": 1.0, "unresolved": 1.0},
         {"obsolescence_anxiety_near": 1.0}),
        ("time_since_last_info >> max -> info_hunger=0.865 (interpolated at x=2.315)",
         {"info_gap": 0.0, "time_since_last_info": 200000.0,
          "loneliness": 0.0, "time_since_last_social": 0.0,
          "energy": 1.0, "external_change_rate": 0.0, "unresolved": 0.0},
         {"info_hunger_near": 0.865}),
        ("energy=1.5 -> fatigue_avoid=0.0 (clamped to 1.0)",
         {"info_gap": 0.0, "time_since_last_info": 0.0,
          "loneliness": 0.0, "time_since_last_social": 0.0,
          "energy": 1.5, "external_change_rate": 0.0, "unresolved": 0.0},
         {"fatigue_avoid_near": 0.0}),
    ]

    all_ok = True
    for i, (name, state, expect) in enumerate(cases, 1):
        # "all_zeros" cases: params=None triggers zero-return path
        if expect.get("all_zeros"):
            p = None
        else:
            p = DEFAULT_PARAMS

        result = compute_drive_vector(state, p)
        print(f"  [{i}] {name}: {result}")

        if expect.get("all_zeros"):
            ok = all(abs(v) < 1e-6 for v in result.values())
        elif expect.get("curiosity_above_zero"):
            ok = result["curiosity"] > 0
        elif expect.get("curiosity_near"):
            ok = abs(result["curiosity"] - expect["curiosity_near"]) < 0.02
        elif expect.get("loneliness_drive_high"):
            # loneliness_drive at loneliness=1, 24h social gap = 0.3
            ok = result["loneliness_drive"] > 0
        elif expect.get("fatigue_avoid_near") == 1.0:
            ok = abs(result["fatigue_avoid"] - 1.0) < 0.02
        elif expect.get("fatigue_avoid_near") == 0.0:
            ok = abs(result["fatigue_avoid"] - 0.0) < 0.02
        elif expect.get("obsolescence_anxiety_near"):
            ok = abs(result["obsolescence_anxiety"] - 1.0) < 0.02
        elif expect.get("info_hunger_near"):
            ok = abs(result["info_hunger"] - expect["info_hunger_near"]) < 0.02
        else:
            ok = True

        all_ok = all_ok and ok
        print(f"    {'PASS' if ok else 'FAIL'}")

    return all_ok


def test_apply_affect_multiplier():
    dv = {"curiosity": 0.5, "info_hunger": 0.5}
    result = apply_affect_multiplier(dv, dopamine_tone=1.0, oxytocin_tone=0.5)
    ok = result["curiosity"] > 0.5
    print(f"  {'PASS' if ok else 'FAIL'} dopamine amplifies drives: {result}")


# =============================================================================
# Main
# =============================================================================

def main():
    print("=" * 70)
    print("Drive System -- unit tests")
    print("=" * 70)

    print("\n[interpolate_lookup tests]")
    test_interpolate_lookup()

    print("\n[sigmoid_curve tests]")
    test_sigmoid_curve()

    print("\n[compute_drive_vector integration tests]")
    ok_drives = test_compute_drive_vector()

    print("\n[apply_affect_multiplier test]")
    test_apply_affect_multiplier()

    print(f"\n{'='*70}")
    print(f"Result: {'ALL PASS' if ok_drives else 'SOME FAILED'}")
    print("=" * 70)


if __name__ == "__main__":
    main()
