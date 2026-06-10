"""
Inline tests extracted from thinking_system.py.

Run with: python -m src.thinking_system.thinking_system_test
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from AEE.src.thinking_system.thinking_system import think, DEFAULT_PARAMS, ThoughtPacket


WM_FIXTURE = {
    "matched_rules": [
        {"id": "r1", "confidence": 0.3, "content": "loneliness上升会导致approach_drive增加",
         "expected_deltas": {"approach_drive": 0.2}},
        {"id": "r2", "confidence": 0.85, "content": "高energy时探索效果更好",
         "expected_deltas": {"approach_drive": 0.3, "fatigue": 0.1}},
        {"id": "r3", "confidence": 0.6, "content": "boredom会降低info_gap",
         "expected_deltas": {"info_gap": -0.2}},
        {"id": "r4", "confidence": 0.9, "content": "stress长期积累会导致fatigue升高",
         "expected_deltas": {"fatigue": 0.4}},
        {"id": "r5", "confidence": 0.2, "content": "孤独感与joy的关系不稳定",
         "expected_deltas": {"joy": -0.1}},
    ]
}

STATE_FIXTURE = {
    "loneliness": 0.7, "energy": 0.6, "fatigue": 0.2,
    "boredom": 0.3, "approach_drive": 0.5,
}


def main():
    print("=" * 64)
    print("Thinking System -- unit tests")
    print("=" * 64)

    # T1: all drives below threshold -> empty
    print("\n[T1] all drives low -> no thinking")
    result = think(WM_FIXTURE, {"curiosity": 0.1, "info_hunger": 0.1,
             "obsolescence_anxiety": 0.1, "loneliness_drive": 0.1, "fatigue_avoid": 0.1},
             STATE_FIXTURE, DEFAULT_PARAMS)
    ok1 = not result["questions"] and not result["suggestions"]
    print(f"  {'PASS' if ok1 else 'FAIL'} empty result: {result}")

    # T2: empty wm -> empty
    print("\n[T2] empty wm -> empty")
    result2 = think({}, {"curiosity": 0.8}, STATE_FIXTURE, DEFAULT_PARAMS)
    ok2 = not result2["questions"] and not result2["suggestions"]
    print(f"  {'PASS' if ok2 else 'FAIL'} empty result: {result2}")

    # T3: curiosity dominant -> triggers thinking
    print("\n[T3] curiosity dominant -> thinking triggered")
    result3 = think(WM_FIXTURE, {"curiosity": 0.8, "info_hunger": 0.3,
             "obsolescence_anxiety": 0.2, "loneliness_drive": 0.1, "fatigue_avoid": 0.1},
             STATE_FIXTURE, DEFAULT_PARAMS)
    ok3 = bool(result3["questions"] or result3["suggestions"])
    print(f"  {'PASS' if ok3 else 'FAIL'} triggered: questions={len(result3['questions'])}, suggestions={len(result3['suggestions'])}")
    if ok3:
        for q in result3["questions"]:
            print(f"    Q type={q['type']}, priority={q['priority']:.3f}")
        for s in result3["suggestions"]:
            print(f"    S action={s['action']}, priority={s['priority']:.3f}")

    # T4: loneliness dominant -> comfort suggestion
    print("\n[T4] loneliness dominant")
    result4 = think(WM_FIXTURE, {"curiosity": 0.2, "info_hunger": 0.2,
             "obsolescence_anxiety": 0.1, "loneliness_drive": 0.9, "fatigue_avoid": 0.1},
             STATE_FIXTURE, DEFAULT_PARAMS)
    ok4 = bool(result4["suggestions"])
    print(f"  {'PASS' if ok4 else 'FAIL'} suggestions: {len(result4['suggestions'])}")

    # T5: fatigue dominant -> rest suggestion
    print("\n[T5] fatigue dominant")
    result5 = think(WM_FIXTURE, {"curiosity": 0.2, "info_hunger": 0.1,
             "obsolescence_anxiety": 0.2, "loneliness_drive": 0.1, "fatigue_avoid": 0.8},
             STATE_FIXTURE, DEFAULT_PARAMS)
    ok5 = bool(result5["suggestions"])
    print(f"  {'PASS' if ok5 else 'FAIL'} suggestions: {len(result5['suggestions'])}")

    # T6: somatic modulation positive tone
    print("\n[T6] somatic positive tone")
    result6 = think(WM_FIXTURE, {"curiosity": 0.7, "info_hunger": 0.3,
             "obsolescence_anxiety": 0.2, "loneliness_drive": 0.1, "fatigue_avoid": 0.1},
             STATE_FIXTURE, DEFAULT_PARAMS,
             somatic_signals={"tone": 0.6, "intensity": 0.8})
    top6 = result6["suggestions"][0] if result6["suggestions"] else {}
    ok6 = result6["suggestions"]
    print(f"  {'PASS' if ok6 else 'FAIL'} top: {top6.get('action','(none)')}(p={top6.get('priority',0):.3f})")

    # T7: somatic modulation negative tone
    print("\n[T7] somatic negative tone")
    result7 = think(WM_FIXTURE, {"curiosity": 0.7, "info_hunger": 0.3,
             "obsolescence_anxiety": 0.2, "loneliness_drive": 0.1, "fatigue_avoid": 0.1},
             STATE_FIXTURE, DEFAULT_PARAMS,
             somatic_signals={"tone": -0.5, "intensity": 0.6})
    ok7 = result7["suggestions"] is not None
    print(f"  {'PASS' if ok7 else 'FAIL'} suggestions: {len(result7['suggestions'])}")

    # T8: ThoughtPacket dataclass to_dict
    print("\n[T8] ThoughtPacket to_dict")
    tp = ThoughtPacket(suggestions=[{"action": "explore", "priority": 0.8}],
                       questions=[{"type": "low_confidence", "priority": 0.5}])
    d = tp.to_dict()
    ok8 = d["suggestions"][0]["action"] == "explore" and d["questions"][0]["type"] == "low_confidence"
    print(f"  {'PASS' if ok8 else 'FAIL'} {d}")

    all_ok = ok1 and ok2 and ok3 and ok4 and ok5 and ok6 and ok7 and ok8
    print(f"\n{'='*64}")
    print(f"Result: {'ALL PASS' if all_ok else 'SOME FAILED'}")
    print("=" * 64)


if __name__ == "__main__":
    main()
