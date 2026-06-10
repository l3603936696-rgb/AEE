"""Quick check: language system state after 1 tick."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from AEE.src.entity_state import get_entity_state, reset_entity_state
from AEE.src.pipeline_runner import run_pipeline

reset_entity_state()
entity = get_entity_state()

result = run_pipeline(raw_input=None, entity_state=entity, daemon_mode=True)

print("=== After 1 tick ===")
ulv = list(getattr(entity, "_unlocked_vocabulary", []))
print(f"unlocked vocab: {len(ulv)}")
print(f"unlocked: {ulv}")
print(f"CxG instances: {len(getattr(entity, '_cxg_instances', []))}")
print(f"best_score: {getattr(entity, '_language_best_score', 0):.4f}")
best_expr = getattr(entity, "_language_best_expression", "")
print(f"best_expr: {best_expr}")
print(f"quenching_eff: {getattr(entity, 'quenching_eff_rolling', 0):.4f}")
resp = result.get("response", {})
print(f"response: {resp.get('text', '')}")
print(f"confidence: {resp.get('confidence', 0)}")

# Run 10 more ticks
for i in range(9):
    run_pipeline(raw_input=None, entity_state=entity, daemon_mode=True)

print("\n=== After 10 ticks ===")
ulv = list(getattr(entity, "_unlocked_vocabulary", []))
print(f"unlocked vocab: {len(ulv)}")
print(f"unlocked: {ulv}")
print(f"CxG instances: {len(getattr(entity, '_cxg_instances', []))}")
print(f"best_score: {getattr(entity, '_language_best_score', 0):.4f}")
best_expr = getattr(entity, "_language_best_expression", "")
print(f"best_expr: {best_expr}")
print(f"quenching_eff: {getattr(entity, 'quenching_eff_rolling', 0):.4f}")

# Check what words she's saying
print(f"\nrecent expressions:")
qd = getattr(entity, "_quenching_data", {})
records = qd.get("records", [])
print(f"  quenching records: {len(records)}")
for r in records[-5:]:
    print(f"  {r.get('expression', '?')} eff={r.get('efficiency', 0):.3f}")
