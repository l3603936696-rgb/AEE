"""Trace why quenching records are empty."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from AEE.src.entity_state import get_entity_state, reset_entity_state
from AEE.src.pipeline_runner import run_pipeline
from AEE.src.world_model_update.core import run_update_cycle

reset_entity_state()
entity = get_entity_state()

# Build rules
for i in range(10):
    run_pipeline(raw_input=None, entity_state=entity, daemon_mode=True)

snaps = entity.snapshots
state_snap = entity.to_state_snapshot()
new_rules, stats = run_update_cycle(
    old_rules=[], snaps=snaps, dialogue_log=[],
    state_snapshot=state_snap, param_snapshot=None,
)
entity.wm_rules = [r.to_dict() if hasattr(r, "to_dict") else dict(r) for r in new_rules]
entity.snapshots = snaps[-5:]

# Monkey-patch expression_quenching to trace calls
import AEE.src.quenching_system as _qs
_orig_eq = _qs.expression_quenching
def _traced_eq(entity, expression=""):
    print(f"  [EQ] called with expr='{expression}' ur={entity.unresolved:.4f}")
    result = _orig_eq(entity, expression)
    print(f"  [EQ] result={result} ur_after={entity.unresolved:.4f}")
    return result
_qs.expression_quenching = _traced_eq

# Run 3 ticks with tracing
for i in range(3):
    print(f"\n--- Tick {entity.tick + 1} ---")
    print(f"  before: ur={entity.unresolved:.4f}")
    result = run_pipeline(raw_input=None, entity_state=entity, daemon_mode=True)
    print(f"  after:  ur={entity.unresolved:.4f}")
    print(f"  best_word: {getattr(entity, '_language_best_candidate', None)}")
    print(f"  best_expr: {getattr(entity, '_language_best_expression', '')}")
    qd = getattr(entity, "_quenching_data", {})
    records = qd.get("records", [])
    print(f"  quenching records: {len(records)}")
