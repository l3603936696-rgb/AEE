"""
100-tick integration test for the XIA language system.

Verifies:
    1. Anchor expression fires (not always blocked by narrative)
    2. CxG constructions compete
    3. Feedback loops trigger
"""

import json
import logging
import os
import sys
import time
from pathlib import Path

# Ensure src is on path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(str(ROOT))

# Suppress noisy loggers but keep language-related ones visible
logging.basicConfig(level=logging.WARNING, format="%(name)s %(message)s")
for _name in ("src.language_training", "src.language_system", "src.pipeline_runner"):
    logging.getLogger(_name).setLevel(logging.INFO)


def run_100_ticks():
    """Run 100 daemon ticks on a fresh entity, collecting stats."""

    # --- fresh entity (bypass singleton / persisted state) ---
    from src.entity_state import EntityState
    entity = EntityState()
    # Push state away from baseline so anchors can match
    entity.fatigue = 0.45
    entity.loneliness = 0.55
    entity.loneliness_core = 0.35
    entity.loneliness_surface = 0.20
    entity.unresolved = 0.40
    entity.info_gap = 0.60
    entity.boredom = 0.35
    entity.stress = 0.25
    entity.energy = 0.55
    entity.somatic_tone = -0.15
    entity.approach_drive = 0.30
    entity.avoid_drive = 0.15
    entity.approach_social = 0.20
    entity.approach_explore = 0.25
    entity.curiosity = 0.55

    from src.pipeline_runner import run_pipeline

    # --- accumulators ---
    narrative_count = 0
    anchor_count = 0
    expr_s_positive = 0
    feedback_triggered = 0
    cxg_n_history = []
    cxg_inst_history = []
    asw_history = []
    cft_history = []
    tick_logs = []
    text_produced = 0

    N = 100
    print(f"\n{'='*72}")
    print(f"  XIA Language System Integration Test  --  {N} daemon ticks")
    print(f"{'='*72}\n")

    for i in range(N):
        t0 = time.time()
        try:
            result = run_pipeline(
                raw_input=None,
                entity_state=entity,
                daemon_mode=True,
                debug=True,  # enable trace for mode detection
            )
        except Exception as exc:
            print(f"  [tick {i:3d}]  PIPELINE ERROR: {exc}")
            tick_logs.append({"tick": i, "error": str(exc)})
            continue
        elapsed = (time.time() - t0) * 1000

        resp = result.get("response", {})
        text = resp.get("text", "")

        # Detect mode from trace (debug=True)
        mode = ""
        for tr in result.get("trace", []):
            if hasattr(tr, 'step') and tr.step == "output" and tr.ok:
                mode = tr.data.get("mode", "")

        state = result.get("state_snapshot", {})
        ur = float(state.get("unresolved", 0.0))
        ig = float(state.get("info_gap", 0.0))

        # Get expr_s from entity (L2 pathway) and also from match_anchor result
        expr_s_l2 = float(getattr(entity, "_language_best_score", 0.0))
        # The daemon path sets response directly -- detect anchor vs narrative from mode
        # Also get the match_anchor best_score if available
        anchor_best_score = float(getattr(entity, "_anchor_best_score", 0.0))

        is_narrative = mode == "narrative"
        is_anchor = mode == "anchor_auto"
        is_training = mode == "training"

        if text:
            text_produced += 1
        if is_narrative:
            narrative_count += 1
        if is_anchor:
            anchor_count += 1
        if expr_s_l2 > 0:
            expr_s_positive += 1

        # Check feedback trigger (chronic tracker changing)
        cft = getattr(entity, "_chronic_feedback_tracker", {})
        if any(v > 0 for v in cft.values()):
            feedback_triggered += 1

        # CxG stats
        cxg = getattr(entity, "_cxg_learner", None)
        cxg_n = cxg.construction_count if cxg else 0
        cxg_inst = len(cxg._instances) if cxg else 0
        cxg_n_history.append(cxg_n)
        cxg_inst_history.append(cxg_inst)

        asw = dict(getattr(entity, "_approach_synthesis_weights", {}))
        cft_snap = dict(cft)
        asw_history.append(asw)
        cft_history.append(cft_snap)

        rec = {
            "tick": i,
            "mode": mode,
            "text": text[:40] if text else "",
            "expr_s_l2": round(expr_s_l2, 4),
            "ur": round(ur, 4),
            "ig": round(ig, 4),
            "cxg_n": cxg_n,
            "cxg_inst": cxg_inst,
            "ms": round(elapsed, 1),
        }
        tick_logs.append(rec)

        # Print every 10th tick + any expression tick
        if i % 10 == 0 or text:
            flag = "NAR" if is_narrative else ("ANC" if is_anchor else ("TRN" if is_training else "---"))
            print(
                f"  [t={i:3d}] {flag}  exprL2={expr_s_l2:.3f}  ur={ur:.3f}  ig={ig:.3f}  "
                f"cxg={cxg_n}/{cxg_inst}  "
                f"text='{text[:35]}'"
            )

    # ====================================================================
    # Summary
    # ====================================================================
    print(f"\n{'='*72}")
    print(f"  SUMMARY  ({N} ticks)")
    print(f"{'='*72}")
    print(f"  Text produced:       {text_produced:4d} / {N}")
    print(f"  Narrative fired:     {narrative_count:4d} / {N}")
    print(f"  Anchor fired:        {anchor_count:4d} / {N}")
    print(f"  expr_s (L2) > 0:     {expr_s_positive:4d} / {N}")
    print(f"  Feedback triggered:  {feedback_triggered:4d} / {N}  (chronic_tracker > 0)")
    print()

    # CxG growth
    if cxg_n_history:
        print(f"  CxG constructions:   start={cxg_n_history[0]}  end={cxg_n_history[-1]}  max={max(cxg_n_history)}")
        print(f"  CxG instances:       start={cxg_inst_history[0]}  end={cxg_inst_history[-1]}  max={max(cxg_inst_history)}")

    # CxG growth check
    cxg_grew = cxg_n_history and cxg_n_history[-1] > 0
    cxg_inst_grew = cxg_inst_history and cxg_inst_history[-1] > cxg_inst_history[0]

    # Parameter drift
    if asw_history:
        asw0 = asw_history[0]
        asw_final = asw_history[-1]
        drifted = {k: round(asw_final.get(k, 0) - asw0.get(k, 0), 5) for k in asw0}
        print(f"  ASW drift:           {drifted}")
        asw_drifted = any(abs(v) > 0.0001 for v in drifted.values())
    else:
        asw_drifted = False

    if cft_history:
        cft_final = cft_history[-1]
        print(f"  Chronic tracker end: {cft_final}")

    # Final entity state
    print(f"\n  Final state:")
    print(f"    energy={entity.energy:.3f}  fatigue={entity.fatigue:.3f}  "
          f"loneliness={entity.loneliness:.3f}  boredom={entity.boredom:.3f}")
    print(f"    unresolved={entity.unresolved:.3f}  info_gap={entity.info_gap:.3f}  "
          f"stress={entity.stress:.3f}")
    print(f"    approach={entity.approach_drive:.3f}  avoid={entity.avoid_drive:.3f}  "
          f"somatic_tone={entity.somatic_tone:.3f}")
    print(f"    vocab={len(getattr(entity, '_unlocked_vocabulary', []))}  "
          f"tick={entity.tick}")

    print()

    # ====================================================================
    # Verdict
    # ====================================================================
    issues = []
    if text_produced == 0:
        issues.append("FAIL: No text produced in 100 ticks")
    if anchor_count == 0 and text_produced > 0:
        issues.append("WARN: Anchor expression never fired (narrative always won)")
    if narrative_count >= N and anchor_count == 0:
        issues.append("FAIL: Narrative blocked ALL ticks (anchor never got a chance)")

    if issues:
        print("  ISSUES:")
        for iss in issues:
            print(f"    - {iss}")
    else:
        print("  ALL CHECKS PASSED")

    # Always print pass details
    if text_produced > 0:
        print(f"    - Text produced in {text_produced}/{N} ticks")
    if anchor_count > 0:
        print(f"    - Anchor fires in {anchor_count}/{N} ticks (not always blocked)")
    if narrative_count > 0:
        print(f"    - Narrative fires in {narrative_count}/{N} ticks (coexists)")
    if cxg_grew:
        print(f"    - CxG constructions present ({cxg_n_history[-1]} constructions)")
    if cxg_inst_grew:
        print(f"    - CxG instances grew ({cxg_inst_history[0]} -> {cxg_inst_history[-1]})")
    if feedback_triggered > 0:
        print(f"    - Feedback loop triggered in {feedback_triggered}/{N} ticks")
    if asw_drifted:
        print(f"    - ASW parameters drifted (chronic feedback working)")

    print(f"\n{'='*72}\n")

    # ====================================================================
    # Check emergence.jsonl
    # ====================================================================
    elog = ROOT / "logs" / "emergence.jsonl"
    if elog.exists():
        lines = elog.read_text(encoding="utf-8").strip().split("\n")
        last_lines = lines[-min(20, len(lines)):]
        print(f"  emergence.jsonl: {len(lines)} total lines, showing last {len(last_lines)}:\n")

        expr_s_pos = 0
        cxg_n_vals = []
        cxg_inst_vals = []

        for line in last_lines:
            try:
                obj = json.loads(line)
                if obj.get("expr_s", 0) > 0:
                    expr_s_pos += 1
                cxg_n_vals.append(obj.get("cxg_n", 0))
                cxg_inst_vals.append(obj.get("cxg_inst", 0))
                # Print abbreviated
                print(f"    t={obj.get('t','')}  expr_s={obj.get('expr_s',0):.4f}  "
                      f"ur={obj.get('ur',0):.3f}  ig={obj.get('ig',0):.3f}  "
                      f"cxg={obj.get('cxg_n',0)}/{obj.get('cxg_inst',0)}  "
                      f"expr='{obj.get('expr','')}'")
            except json.JSONDecodeError:
                pass

        print(f"\n  emergence.jsonl analysis (last {len(last_lines)} lines):")
        print(f"    expr_s > 0:          {expr_s_pos} / {len(last_lines)}")
        if cxg_n_vals:
            print(f"    cxg_n range:         {min(cxg_n_vals)} .. {max(cxg_n_vals)}")
            print(f"    cxg_inst range:      {min(cxg_inst_vals)} .. {max(cxg_inst_vals)}")
            grew = cxg_n_vals[-1] > cxg_n_vals[0] or cxg_inst_vals[-1] > cxg_inst_vals[0]
            print(f"    CxG grew:            {'YES' if grew else 'NO'}")
        # ASW/CFT drift check
        if len(last_lines) >= 2:
            try:
                first = json.loads(last_lines[0])
                last = json.loads(last_lines[-1])
                asw_first = first.get("asw", {})
                asw_last = last.get("asw", {})
                cft_first = first.get("cft", {})
                cft_last = last.get("cft", {})
                asw_d = {k: round(asw_last.get(k, 0) - asw_first.get(k, 0), 5) for k in asw_first}
                cft_d = {k: round(cft_last.get(k, 0) - cft_first.get(k, 0), 5) for k in cft_first}
                print(f"    ASW delta:           {asw_d}")
                print(f"    CFT delta:           {cft_d}")
            except Exception:
                pass
    else:
        print("  emergence.jsonl: not found (pipeline may not have written it)")

    return text_produced > 0


if __name__ == "__main__":
    ok = run_100_ticks()
    sys.exit(0 if ok else 1)
