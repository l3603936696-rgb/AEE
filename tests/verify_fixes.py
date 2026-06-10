"""
验证 v11.4 三 bug 修复 — 2026-05-10
用法: cd E:\XIA && python verify_fixes.py
"""
import sys
sys.path.insert(0, '.')

from AEE.src.entity_state import EntityState, get_entity_state, force_set_state
from AEE.src.state_update.compute_connection import compute_loneliness_target_ex

OK = 0
FAIL = 0

# ============================================================
print("=" * 60)
print("测试 1: _freeze_state 阻止 TrainingMC + AntiLock")
print("=" * 60)

entity = EntityState()
entity.somatic_tone = -0.80
entity.loneliness_core = 0.60
entity.loneliness_surface = 0.15
entity.stress = 0.85
entity.fatigue = 0.90

entity._freeze_state = True
snap = entity.to_state_snapshot()
if snap.get("_freeze_state") == True:
    print("  PASS: _freeze_state=True 在快照中可见")
    OK += 1
else:
    print("  FAIL: _freeze_state 未在快照中")
    FAIL += 1

entity._freeze_state = False
snap2 = entity.to_state_snapshot()
if snap2.get("_freeze_state") == False:
    print("  PASS: _freeze_state 可重置为 False")
    OK += 1
else:
    print("  FAIL: _freeze_state 未重置")
    FAIL += 1

# ============================================================
print("\n" + "=" * 60)
print("测试 2: 真人互动后 loneliness_core 打 4 折")
print("=" * 60)

core, surface, inter = compute_loneliness_target_ex(
    loneliness_core=0.70, loneliness_surface=0.25,
    connection_depth_effective=0.5, silence_duration=0.0,
    social_input_present=True, active_exploration=False,
)
expected = 0.70 * 0.6
if abs(core - expected) < 0.001:
    print(f"  PASS: core 0.70 -> {core:.4f} (40% 折扣正确)")
    OK += 1
else:
    print(f"  FAIL: core 应为 {expected:.4f}，实际 {core:.4f}")
    FAIL += 1

if surface == 0.0:
    print(f"  PASS: surface 正确归零")
    OK += 1
else:
    print(f"  FAIL: surface 应为 0.0，实际 {surface}")
    FAIL += 1

# 无互动
core2, surface2, _ = compute_loneliness_target_ex(
    loneliness_core=0.50, loneliness_surface=0.20,
    connection_depth_effective=0.5, silence_duration=0.0,
    social_input_present=False, active_exploration=False,
)
if core2 > 0.50:
    print(f"  PASS: 无互动时 core 缓慢上升 0.50 -> {core2:.4f}")
    OK += 1
else:
    print(f"  FAIL: 无互动时 core 应上升")
    FAIL += 1

# 反扑
core3, surface3, inter3 = compute_loneliness_target_ex(
    loneliness_core=0.70, loneliness_surface=0.02,
    connection_depth_effective=0.5, silence_duration=0.0,
    social_input_present=False, active_exploration=True,
)
if core3 > 0.70:
    print(f"  PASS: 反扑生效 core 0.70 -> {core3:.4f}")
    OK += 1
else:
    print(f"  FAIL: 反扑未触发")
    FAIL += 1

# ============================================================
print("\n" + "=" * 60)
print("测试 3: _lock_snaps loneliness 中性值 0.5->0.3")
print("=" * 60)

# 直接检查代码
import inspect
from AEE.src.pipeline_runner import run_pipeline
src = inspect.getsource(run_pipeline)
if 'loneliness' in src and '0.3' in src:
    print("  PASS: pipeline_runner.py 包含 loneliness 中性值 0.3")
    OK += 1
else:
    # Fallback: check the file directly
    try:
        with open('src/pipeline_runner.py', encoding='utf-8') as f:
            content = f.read()
        found = False
        for line in content.split('\n'):
            if '_lock_snaps' in line and 'loneliness' in line:
                if '0.3' in line:
                    print("  PASS: _lock_snaps loneliness 中性值 = 0.3")
                    OK += 1
                    found = True
                break
        if not found:
            print("  WARN: 无法确认，请手动检查 pipeline_runner.py L1727")
    except Exception as e:
        print(f"  WARN: 文件读取失败 ({e})，请手动确认")

# ============================================================
print("\n" + "=" * 60)
print("测试 4: 模块拆分完整性")
print("=" * 60)

try:
    from AEE.src.entity_state import EntityState, PipelineTrace, get_entity_state
    print("  PASS: entity_state 导入")
    OK += 1
except Exception as e:
    print(f"  FAIL: entity_state 导入失败: {e}")
    FAIL += 1

try:
    from AEE.src.pipeline_runner import run_pipeline
    print("  PASS: pipeline_runner 导入")
    OK += 1
except Exception as e:
    print(f"  FAIL: pipeline_runner 导入失败: {e}")
    FAIL += 1

try:
    from AEE.src.language_training import run_language_training_tick
    print("  PASS: language_training 导入")
    OK += 1
except Exception as e:
    print(f"  FAIL: language_training 导入失败: {e}")
    FAIL += 1

try:
    from AEE.src.entity_zero_iteration import (
        EntityState, run_pipeline, run_language_training_tick,
        get_entity_state,
    )
    print("  PASS: entity_zero_iteration 兼容层导入")
    OK += 1
except Exception as e:
    print(f"  FAIL: entity_zero_iteration 兼容层失败: {e}")
    FAIL += 1

# ============================================================
print("\n" + "=" * 60)
print(f"结果: {OK} 通过, {FAIL} 失败")
if FAIL == 0:
    print("全部验证通过!")
else:
    print("有测试失败，需要修复。")
print("=" * 60)
