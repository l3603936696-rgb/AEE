"""Quick: just run 10 ticks and check records + efficiency."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.entity_state import get_entity_state, reset_entity_state
from src.pipeline_runner import run_pipeline

reset_entity_state()
entity = get_entity_state()

for i in range(10):
    run_pipeline(raw_input=None, entity_state=entity, daemon_mode=True)

qd = getattr(entity, "_quenching_data", {})
records = qd.get("records", [])
print(f"After 10 ticks: {len(records)} records")
for r in records[-5:]:
    expr = r.get("expression", "?")
    eff = r.get("quenching_efficiency", r.get("efficiency", -1))
    before = r.get("delta_unresolved_before", -1)
    after = r.get("delta_unresolved_after", -1)
    print(f"  '{expr}' eff={eff:.4f} before={before:.4f} after={after:.4f}")
