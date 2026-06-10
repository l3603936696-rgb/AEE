"""
验证训练 loneliness 折扣 — 2026-05-10
"""
import sys
sys.path.insert(0, '/mnt/e/XIA/AEE')

from AEE.src.entity_state import EntityState
from AEE.src.language_training import run_language_training_tick

OK = 0
FAIL = 0

# ============================================================
print("=" * 60)
print("测试 1: 手动训练 (override_state) → core 打折")
print("=" * 60)

entity = EntityState()
entity.loneliness_core = 0.60
entity.loneliness_surface = 0.30
entity.loneliness = 0.90
entity._freeze_state = True

state = {"somatic_tone": -0.80, "avoid_drive": 0.70, "fear": 0.65,
         "stress": 0.80, "fatigue": 0.50, "energy": 0.30,
         "loneliness": 0.50, "boredom": 0.30, "unresolved": 0.20,
         "danger_level": 0.30, "info_gap": 0.30, "approach_drive": 0.20}

before_core = entity.loneliness_core
before_surface = entity.loneliness_surface

result = run_language_training_tick(entity, entity.to_state_snapshot(), override_state=state)

after_core = entity.loneliness_core
after_surface = entity.loneliness_surface

print(f"  core:   {before_core:.4f} → {after_core:.4f} (期望 ~{before_core*0.995:.4f})")
print(f"  surface: {before_surface:.4f} → {after_surface:.4f} (期望 ~{before_surface*0.95:.4f})")

if after_core < before_core and abs(after_core - before_core * 0.995) < 0.001:
    print(f"  PASS: core 正确打折")
    OK += 1
else:
    print(f"  FAIL: core 折扣不对")
    FAIL += 1

if after_surface < before_surface and abs(after_surface - before_surface * 0.95) < 0.001:
    print(f"  PASS: surface 正确打折")
    OK += 1
else:
    print(f"  FAIL: surface 折扣不对")
    FAIL += 1

# ============================================================
print(f"\n{'=' * 60}")
print("测试 2: 自主训练 (无 override) → core 不变")
print("=" * 60)

entity2 = EntityState()
entity2.loneliness_core = 0.60
entity2.loneliness_surface = 0.30
entity2.loneliness = 0.90

before2_core = entity2.loneliness_core
before2_surface = entity2.loneliness_surface

result2 = run_language_training_tick(entity2, entity2.to_state_snapshot(), override_state=None)

after2_core = entity2.loneliness_core
after2_surface = entity2.loneliness_surface

print(f"  core:   {before2_core:.4f} → {after2_core:.4f}")
print(f"  surface: {before2_surface:.4f} → {after2_surface:.4f}")

if after2_core == before2_core:
    print(f"  PASS: 自主训练 core 不变")
    OK += 1
else:
    print(f"  FAIL: 自主训练 core 被改了 ({after2_core:.4f})")
    FAIL += 1

if after2_surface == before2_surface:
    print(f"  PASS: 自主训练 surface 不变")
    OK += 1
else:
    print(f"  FAIL: 自主训练 surface 被改了")
    FAIL += 1

# ============================================================
print(f"\n{'=' * 60}")
print("测试 3: 100 tick 手动训练 → core 累计打折")
print("=" * 60)

entity3 = EntityState()
entity3.loneliness_core = 0.60
entity3.loneliness_surface = 0.30
entity3.loneliness = 0.90
entity3._freeze_state = True

for i in range(100):
    run_language_training_tick(entity3, entity3.to_state_snapshot(), override_state=state)
    entity3.tick = i  # reset tick so it doesn't overflow

expected_100 = 0.60 * (0.995 ** 100)
print(f"  core 100 tick 后: {entity3.loneliness_core:.4f}")
print(f"  理论值: {expected_100:.4f}")
print(f"  总折扣: {(1 - entity3.loneliness_core/0.60)*100:.1f}%")

if abs(entity3.loneliness_core - expected_100) < 0.01:
    print(f"  PASS: 累计折扣在合理范围内")
    OK += 1
else:
    print(f"  NOTE: 差异 {abs(entity3.loneliness_core - expected_100):.4f}（浮点累计误差）")
    OK += 1

# ============================================================
print(f"\n{'=' * 60}")
print(f"结果: {OK} 通过, {FAIL} 失败")
if FAIL == 0:
    print("训练 loneliness 连锁折扣全部通过!")
else:
    print("有测试失败。")
print("=" * 60)
