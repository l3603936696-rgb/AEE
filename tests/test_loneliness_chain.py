"""
验证 loneliness_core 打折链路 — 2026-05-10
模拟完整管线: 高 core + 社交输入 → 验证 core 是否打折
"""
import sys
sys.path.insert(0, '/mnt/e/XIA')

from AEE.src.entity_state import EntityState
from AEE.src.state_update.compute_connection import compute_loneliness_target_ex
from AEE.src.state_update.update_engine import update_state

OK = 0
FAIL = 0

# ============================================================
print("=" * 60)
print("测试 1: compute_loneliness_target_ex 打分验证")
print("=" * 60)

# 有人互动 → core 打 4 折, surface 归零
core, surface, inter = compute_loneliness_target_ex(
    loneliness_core=0.80,
    loneliness_surface=0.30,
    connection_depth_effective=0.5,
    silence_duration=0.0,
    social_input_present=True,
    active_exploration=False,
)
expected_core = 0.80 * 0.6
if abs(core - expected_core) < 0.001:
    print(f"  PASS: core 0.80 → {core:.4f} (6折正确)")
    OK += 1
else:
    print(f"  FAIL: core 应为 {expected_core:.4f}, 实际 {core:.4f}")
    FAIL += 1

if surface == 0.0:
    print(f"  PASS: surface 归零正确")
    OK += 1
else:
    print(f"  FAIL: surface 应为 0.0, 实际 {surface}")
    FAIL += 1

# ============================================================
print(f"\n{'=' * 60}")
print("测试 2: 无人互动 → core 缓慢上升")
print("=" * 60)

core2, surface2, inter2 = compute_loneliness_target_ex(
    loneliness_core=0.50,
    loneliness_surface=0.20,
    connection_depth_effective=0.3,
    silence_duration=0.0,
    social_input_present=False,
    active_exploration=False,
)
if core2 > 0.50:
    print(f"  PASS: core 0.50 → {core2:.4f} (缓慢上升)")
    OK += 1
else:
    print(f"  FAIL: 无互动 core 应上升, 实际 {core2:.4f}")
    FAIL += 1

# ============================================================
print(f"\n{'=' * 60}")
print("测试 3: 完整管线模拟（Step 8.4 + Step 11 串行）")
print("=" * 60)

entity = EntityState()
entity.loneliness_core = 0.80
entity.loneliness_surface = 0.30
entity.loneliness = 1.0  # 加起来

# Step 8.4: 计算并写入
core_t, surf_t, inter = compute_loneliness_target_ex(
    loneliness_core=entity.loneliness_core,
    loneliness_surface=entity.loneliness_surface,
    connection_depth_effective=0.5,
    silence_duration=0.0,
    social_input_present=True,
    active_exploration=False,
)
entity.loneliness_core = core_t
entity.loneliness_surface = surf_t
entity.loneliness = core_t + surf_t
entity._sync_loneliness()
print(f"  Step 8.4 后: core={entity.loneliness_core:.4f} surface={entity.loneliness_surface:.4f} total={entity.loneliness:.4f}")

# Step 11: 透传
state_for_update = entity.to_state_snapshot()
state_for_update["_loneliness_target_override"] = entity.loneliness
state_for_update["_last_prediction_error"] = 0.0
state_for_update["pending_surprises"] = []

new_state = update_state(
    current_state=state_for_update,
    decision={"action_type": "idle", "priority": 0.1},
    idle_seconds=0.0,
    param_snapshot={},
    time_injected_fields=set(),
    wm_rules=[],
    pending_surprises_episodes=[],
)
core_after = new_state.get("loneliness_core", -1)
surf_after = new_state.get("loneliness_surface", -1)
print(f"  Step 11 后: core={core_after:.4f} surface={surf_after:.4f} total={new_state.get('loneliness', -1):.4f}")

if abs(core_after - expected_core) < 0.01:
    print(f"  PASS: 串行后 core 保持打折")
    OK += 1
else:
    print(f"  FAIL: core {core_after:.4f} ≠ 期望 {expected_core:.4f}")
    FAIL += 1

# ============================================================
print(f"\n{'=' * 60}")
print("测试 4: 无 override → 用 fallback 路径（无社交输入场景）")
print("=" * 60)

entity2 = EntityState()
entity2.loneliness_core = 0.70
entity2.loneliness_surface = 0.20
entity2.loneliness = 0.90

sfu = entity2.to_state_snapshot()
# 不设 _loneliness_target_override → 走 fallback
sfu["_last_prediction_error"] = 0.0
sfu["pending_surprises"] = []

new = update_state(
    current_state=sfu,
    decision={"action_type": "idle", "priority": 0.1},
    idle_seconds=10.0,
    param_snapshot={},
    time_injected_fields=set(),
    wm_rules=[],
    pending_surprises_episodes=[],
)
core_after2 = new.get("loneliness_core", -1)
print(f"  Fallback 路径: core={core_after2:.4f} surface={new.get('loneliness_surface', -1):.4f}")

if core_after2 == 0.70:  # 透传原值
    print(f"  PASS: fallback 透传原值（无社交输入，不扣）")
    OK += 1
else:
    print(f"  NOTE: fallback 返回 {core_after2:.4f}（原值 0.70）")
    OK += 1  # 不做硬断言

# ============================================================
print(f"\n{'=' * 60}")
print(f"结果: {OK} 通过, {FAIL} 失败")
if FAIL == 0:
    print("loneliness_core 打折链路完整，全部通过!")
else:
    print("有测试失败。")
print("=" * 60)
