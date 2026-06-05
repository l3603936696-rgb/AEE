"""
Step 8.4 诊断脚本：模拟 daemon tick 的 loneliness 更新路径
"""
import sys
sys.path.insert(0, ".")

from src.entity_state import get_entity_state
from src.parameter_system.access import create_snapshot
from src.pipeline_runner.helpers import SnapshotDictWrapper
from src.state_update.compute_connection import compute_loneliness_target_ex

entity = get_entity_state()
snapshot = create_snapshot()
_snapshot_dict = SnapshotDictWrapper(snapshot)

print(f"=== Entity loaded ===")
print(f"  tick={entity.tick}")
print(f"  loneliness_core={entity.loneliness_core}")
print(f"  loneliness_surface={entity.loneliness_surface}")
print(f"  loneliness={entity.loneliness}")

# 模拟 Step 8.3 somatic_tone_delta 计算
import time
somatic_tone_start = float(getattr(entity, "somatic_tone", 0.0))
somatic_tone_end = float(getattr(entity, "somatic_tone", 0.0))
somatic_tone_delta = somatic_tone_end - somatic_tone_start
print(f"\n=== somatic_tone_delta={somatic_tone_delta} (start={somatic_tone_start}) ===")

# 模拟 Step 8.4 条件
raw_input = None  # daemon tick
has_social_input = bool(raw_input and str(raw_input).strip())
_is_active = False
print(f"\n=== Step 8.4 inputs ===")
print(f"  has_social_input={has_social_input}")
print(f"  active_exploration={_is_active}")
print(f"  loneliness_core input={float(getattr(entity, 'loneliness_core', entity.loneliness * 0.7))}")
print(f"  loneliness_surface input={float(getattr(entity, 'loneliness_surface', entity.loneliness * 0.3))}")

# 调用 compute_loneliness_target_ex
try:
    core_t, surf_t, intermediates = compute_loneliness_target_ex(
        loneliness_core=float(getattr(entity, "loneliness_core", entity.loneliness * 0.7)),
        loneliness_surface=float(getattr(entity, "loneliness_surface", entity.loneliness * 0.3)),
        connection_depth_effective=0.5,
        silence_duration=0.0,
        social_input_present=has_social_input,
        active_exploration=_is_active,
        param_snapshot=_snapshot_dict,
    )
    print(f"\n=== compute_loneliness_target_ex SUCCEEDED ===")
    print(f"  core_target={core_t}")
    print(f"  surf_target={surf_t}")
    print(f"  intermediates={intermediates}")

    # 模拟 _trace("connection_depth", True, {..., "somatic_tone_delta": round(somatic_tone_delta, 4), ...})
    print(f"\n=== _trace check: somatic_tone_delta={round(somatic_tone_delta, 4)} ===")

    # 写入
    entity.loneliness_core = core_t
    entity.loneliness_surface = surf_t
    entity.loneliness = min(1.0, core_t + surf_t)
    entity._sync_loneliness()
    print(f"\n=== After write ===")
    print(f"  entity.loneliness_core={entity.loneliness_core}")
    print(f"  entity.loneliness_surface={entity.loneliness_surface}")
    print(f"  entity.loneliness={entity.loneliness}")

except Exception as e:
    import traceback
    print(f"\n=== compute_loneliness_target_ex FAILED: {e!r} ===")
    traceback.print_exc()

# 现在模拟 update_engine 的 loneliness_core 透传
print(f"\n=== Simulating update_engine transparency ===")
state_snap = entity.to_state_snapshot()
print(f"  state_snap['loneliness_core']={state_snap.get('loneliness_core')!r}")
print(f"  state_snap['loneliness_surface']={state_snap.get('loneliness_surface')!r}")
print(f"  state_snap['loneliness']={state_snap.get('loneliness')!r}")
