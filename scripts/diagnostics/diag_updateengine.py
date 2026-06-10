"""
模拟 update_engine 对 loneliness_core 的透传
"""
import sys
sys.path.insert(0, ".")

from AEE.src.entity_state import get_entity_state
from AEE.src.parameter_system.access import create_snapshot
from AEE.src.pipeline_runner.helpers import SnapshotDictWrapper
from AEE.src.state_update.compute_connection import compute_loneliness_target_ex
from AEE.src.state_update.update_engine import update_state

entity = get_entity_state()
snapshot = create_snapshot()
_snapshot_dict = SnapshotDictWrapper(snapshot)

# 先执行 Step 8.4 设置 loneliness_core
core_t, surf_t, _ = compute_loneliness_target_ex(
    loneliness_core=0.0,
    loneliness_surface=0.0,
    connection_depth_effective=0.5,
    silence_duration=0.0,
    social_input_present=False,
    active_exploration=False,
    param_snapshot=_snapshot_dict,
)
entity.loneliness_core = core_t   # 0.003
entity.loneliness_surface = surf_t # 0.012
entity.loneliness = min(1.0, core_t + surf_t)
entity._sync_loneliness()
loneliness_target = min(1.0, core_t + surf_t)

print(f"After Step 8.4 write:")
print(f"  entity.loneliness_core = {entity.loneliness_core}")
print(f"  entity.loneliness_surface = {entity.loneliness_surface}")
print(f"  entity.loneliness = {entity.loneliness}")

# 模拟 Step 11: 构建 state_for_update
state_for_update = dict(entity.to_state_snapshot())
state_for_update["_last_prediction_error"] = getattr(entity, "_last_prediction_error", 0.0)
state_for_update["pending_surprises"] = list(getattr(entity, "pending_surprises", []))

if loneliness_target is not None:
    state_for_update["_loneliness_target_override"] = loneliness_target

print(f"\nstate_for_update keys relevant to loneliness:")
print(f"  loneliness_core = {state_for_update.get('loneliness_core')!r}")
print(f"  loneliness_surface = {state_for_update.get('loneliness_surface')!r}")
print(f"  loneliness = {state_for_update.get('loneliness')!r}")
print(f"  _loneliness_target_override = {state_for_update.get('_loneliness_target_override')!r}")

# 运行 update_state
import time
idle_seconds = 30.0  # daemon tick
decision = {"action_type": "comfort"}

try:
    new_state = update_state(
        current_state=state_for_update,
        decision=decision,
        idle_seconds=idle_seconds,
        param_snapshot=_snapshot_dict,
        time_injected_fields=entity._time_injected_fields,
        wm_rules=entity.wm_rules,
        pending_surprises_episodes=[],
    )
    print(f"\nnew_state relevant loneliness:")
    print(f"  loneliness_core = {new_state.get('loneliness_core')!r}")
    print(f"  loneliness_surface = {new_state.get('loneliness_surface')!r}")
    print(f"  loneliness = {new_state.get('loneliness')!r}")

    # Step 11 writeback
    entity.loneliness_core = max(0.0, min(1.0, new_state.get("loneliness_core", entity.loneliness_core)))
    entity.loneliness_surface = max(0.0, min(1.0, new_state.get("loneliness_surface", entity.loneliness_surface)))
    entity.loneliness = max(0.0, min(1.0, new_state.get("loneliness", entity.loneliness)))
    entity._sync_loneliness()

    print(f"\nAfter Step 11 writeback:")
    print(f"  entity.loneliness_core = {entity.loneliness_core}")
    print(f"  entity.loneliness_surface = {entity.loneliness_surface}")
    print(f"  entity.loneliness = {entity.loneliness}")

except Exception as e:
    import traceback
    print(f"\nupdate_state FAILED: {e!r}")
    traceback.print_exc()
