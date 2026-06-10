"""Trace quenching efficiency across ticks after rules exist."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from AEE.src.entity_state import get_entity_state, reset_entity_state
from AEE.src.pipeline_runner import run_pipeline
from AEE.src.world_model_update.core import run_update_cycle

reset_entity_state()
entity = get_entity_state()

# Phase 1: Build up rules (10 ticks)
for i in range(10):
    run_pipeline(raw_input=None, entity_state=entity, daemon_mode=True)

# WM induction
snaps = entity.snapshots
state_snap = entity.to_state_snapshot()
new_rules, stats = run_update_cycle(
    old_rules=[], snaps=snaps, dialogue_log=[],
    state_snapshot=state_snap, param_snapshot=None,
)
entity.wm_rules = [
    r.to_dict() if hasattr(r, "to_dict") else dict(r) for r in new_rules
]
entity.snapshots = snaps[-5:]
print(f"Rules: {len(entity.wm_rules)}")

# Phase 2: Run 15 more ticks, trace quenching per tick
for i in range(15):
    ur_before = entity.unresolved
    ig_before = entity.info_gap
    result = run_pipeline(raw_input=None, entity_state=entity, daemon_mode=True)
    ur_after = entity.unresolved
    ig_after = entity.info_gap

    expr = getattr(entity, "_language_best_expression", "")
    score = getattr(entity, "_language_best_score", 0)
    eff = getattr(entity, "quenching_eff_rolling", 0)

    # Get latest quenching record
    qd = getattr(entity, "_quenching_data", {})
    records = qd.get("records", [])
    last_eff = records[-1].get("efficiency", -1) if records else -1

    print(
        f"tick {entity.tick:3d} | "
        f"ur={ur_before:.4f}->{ur_after:.4f} | "
        f"ig={ig_before:.4f}->{ig_after:.4f} | "
        f"expr='{expr}' score={score:.3f} | "
        f"last_record_eff={last_eff:.4f} | "
        f"rolling_eff={eff:.4f}"
    )
