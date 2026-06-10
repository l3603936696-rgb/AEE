"""
Inline tests extracted from compute_connection.py.

Run with: python -m src.state_update.compute_connection_test
"""

import sys
from pathlib import Path
from collections import deque

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from AEE.src.state_update.compute_connection import (
    compute_connection_depth,
    compute_loneliness_target,
)
from AEE.src.state_update.compute_connection_helpers import (
    compute_connection_depth_ex,
    compute_loneliness_target_ex,
)


def make_params() -> dict:
    return {
        "connection.w_prediction": 1.0,
        "connection.w_somatic":    1.0,
        "connection.w_tension":   1.0,
        "connection.loneliness_recovery_rate":      0.35,
        "connection.loneliness_rejection_multiplier": 1.80,
        "connection.loneliness_connection_threshold": 0.10,
        "connection.release_lag":                     0.70,
        "connection.positive_bias_strength": 0.05,
        "connection.negative_bias_strength": 0.02,
        "connection.positive_threshold":   0.10,
        "connection.negative_threshold":    0.10,
        "connection.coherence_high_threshold": 0.70,
        "connection.coherence_low_threshold":  0.30,
        "connection.coherence_amplify":      1.30,
        "connection.coherence_attenuate":     0.50,
        "connection.negative_damping_floor": 0.70,
        "connection.damping_scale":          0.30,
    }


def main() -> None:
    print("=" * 64)
    print("compute_connection -- unit tests")
    print("=" * 64)

    params = make_params()

    # T1: base connection_depth (no prediction error, no somatic change, no tension)
    r = deque([{"somatic_tone": 0.1}, {"somatic_tone": 0.1}])
    cd1, sig1 = compute_connection_depth(
        prediction_error=0.0,
        somatic_tone_delta=0.0,
        tension_level=0.0,
        memory_context=[],
        recent_deltas=r,
        loneliness=0.3,
        param_snapshot=params,
    )
    ok1 = cd1 > 0.5
    print(f"  {'PASS' if ok1 else 'FAIL'} T1 base connection_depth: {cd1:.4f} (>0.5)")

    # T2: negative connection_depth (high prediction error + negative somatic change)
    cd2, sig2 = compute_connection_depth(
        prediction_error=1.0,
        somatic_tone_delta=-0.3,
        tension_level=0.8,
        memory_context=[],
        recent_deltas=deque([{"somatic_tone": -0.1}]),
        loneliness=0.3,
        param_snapshot=params,
    )
    ok2 = cd2 < 0.0
    print(f"  {'PASS' if ok2 else 'FAIL'} T2 negative connection_depth: {cd2:.4f} (<0)")

    # T3: coherence amplify (high coherence)
    cd3, _ = compute_connection_depth(
        prediction_error=0.0,
        somatic_tone_delta=0.3,
        tension_level=0.0,
        memory_context=[],
        recent_deltas=deque([{"somatic_tone": 0.1}, {"somatic_tone": 0.2}, {"somatic_tone": 0.1}]),
        loneliness=0.3,
        param_snapshot=params,
    )
    cd3_no_coh, _ = compute_connection_depth(
        prediction_error=0.0,
        somatic_tone_delta=0.3,
        tension_level=0.0,
        memory_context=[],
        recent_deltas=deque([{"somatic_tone": 0.0}, {"somatic_tone": 0.0}]),
        loneliness=0.3,
        param_snapshot=params,
    )
    ok3 = cd3 > cd3_no_coh
    print(f"  {'PASS' if ok3 else 'FAIL'} T3 coherence amplify: {cd3:.4f} > {cd3_no_coh:.4f}")

    # T4: negative damping (connection_depth<0 + high loneliness -> strong damping)
    cd4, _ = compute_connection_depth(
        prediction_error=1.0,
        somatic_tone_delta=-0.3,
        tension_level=0.8,
        memory_context=[],
        recent_deltas=deque([{"somatic_tone": -0.1}]),
        loneliness=0.8,
        param_snapshot=params,
    )
    cd4_low_lon, _ = compute_connection_depth(
        prediction_error=1.0,
        somatic_tone_delta=-0.3,
        tension_level=0.8,
        memory_context=[],
        recent_deltas=deque([{"somatic_tone": -0.1}]),
        loneliness=0.1,
        param_snapshot=params,
    )
    ok4 = abs(cd4) < abs(cd4_low_lon)
    print(f"  {'PASS' if ok4 else 'FAIL'} T4 negative damping: |{cd4:.4f}| < |{cd4_low_lon:.4f}|")

    # T5: experience_bias positive offset
    pos_mem = [{"loneliness_change": -0.2, "signature": {"prediction": 0.8, "somatic": 0.5, "tension": 0.8}}]
    cd5_pos, _ = compute_connection_depth(
        prediction_error=0.2,
        somatic_tone_delta=0.2,
        tension_level=0.2,
        memory_context=pos_mem,
        recent_deltas=deque([]),
        loneliness=0.3,
        param_snapshot=params,
    )
    cd5_no_mem, _ = compute_connection_depth(
        prediction_error=0.2,
        somatic_tone_delta=0.2,
        tension_level=0.2,
        memory_context=[],
        recent_deltas=deque([]),
        loneliness=0.3,
        param_snapshot=params,
    )
    ok5 = cd5_pos > cd5_no_mem
    print(f"  {'PASS' if ok5 else 'FAIL'} T5 positive experience_bias: {cd5_pos:.4f} > {cd5_no_mem:.4f}")

    # T6: real social input -> loneliness target = 0
    t1 = compute_loneliness_target(0.5, 0.6, 3600.0, True, params)
    ok6 = t1 == 0.0
    print(f"  {'PASS' if ok6 else 'FAIL'} T6 social -> target=0: {t1:.4f} == 0.0")

    # T7: no social input -> loneliness accumulates
    t2 = compute_loneliness_target(0.3, -0.5, 86400.0, False, params)
    ok7 = t2 > 0.3
    print(f"  {'PASS' if ok7 else 'FAIL'} T7 no social -> accumulates: {t2:.4f} > 0.3")

    # T8: social input -> target = 0 (jump, not smooth decay)
    t3_no_social = compute_loneliness_target(0.4, -0.5, 86400.0, False, params)
    t3_with_social = compute_loneliness_target(0.4, 0.3, 86400.0, True, params)
    ok8 = t3_with_social == 0.0 and t3_no_social > 0.4
    print(f"  {'PASS' if ok8 else 'FAIL'} T8 social->0, no social->accumulate: {t3_with_social:.4f} vs {t3_no_social:.4f}")

    # T9: compute_connection_depth_ex returns intermediates
    cd_ex, sig_ex, ints_ex = compute_connection_depth_ex(
        prediction_error=0.0,
        somatic_tone_delta=0.3,
        tension_level=0.2,
        memory_context=[],
        recent_deltas=deque([{"somatic_tone": 0.1}]),
        loneliness=0.3,
        param_snapshot=params,
    )
    ok9 = "base_connection_depth" in ints_ex and "experience_bias" in ints_ex
    print(f"  {'PASS' if ok9 else 'FAIL'} T9 compute_connection_depth_ex has intermediates")

    # T10: compute_loneliness_target_ex dual-channel
    core_t, surf_t, ints_ex2 = compute_loneliness_target_ex(
        loneliness_core=0.6,
        loneliness_surface=0.4,
        connection_depth_effective=0.3,
        silence_duration=3600.0,
        social_input_present=False,
        active_exploration=True,
        param_snapshot=params,
    )
    ok10 = ints_ex2["mode"] == "dual_channel_v11.4"
    print(f"  {'PASS' if ok10 else 'FAIL'} T10 loneliness_target_ex mode: {ints_ex2['mode']}")

    print(f"\n结果: {'全部通过' if all([ok1,ok2,ok3,ok4,ok5,ok6,ok7,ok8,ok9,ok10]) else '部分失败'}")
    print("=" * 64)


if __name__ == "__main__":
    main()
