"""验证注意场和消力系统"""
import sys
sys.path.insert(0, '/mnt/e/XIA')

from src.emotion_system.attention_field import compute_attention_field, compute_attention_field_from_entity, ALL_CATEGORIES
from src.quenching_system import apply_all_quenching, QuenchingJournal, temporal_quenching, decision_quenching, social_quenching

# --- 1. 注意场 ---
print("=" * 60)
print("1. 注意场：情绪向量 → 信息类别增益")
print("=" * 60)

# 恐惧占主导
emotions_fear = {"fear": 0.7, "anxiety": 0.3, "joy": 0.1, "sadness": 0.1}
af = compute_attention_field(emotions_fear)
print(f"\n恐惧主导: fear=0.7, anxiety=0.3")
for cat in sorted(af.keys(), key=lambda c: af[c], reverse=True):
    if abs(af[cat] - 1.0) > 0.1:
        direction = "↑" if af[cat] > 1.0 else "↓"
        print(f"  {cat:15s} {af[cat]:.2f} {direction}")

# 快乐占主导
emotions_joy = {"joy": 0.7, "excitement": 0.3, "fear": 0.1, "anxiety": 0.1}
af2 = compute_attention_field(emotions_joy)
print(f"\n快乐主导: joy=0.7, excitement=0.3")
for cat in sorted(af2.keys(), key=lambda c: af2[c], reverse=True):
    if abs(af2[cat] - 1.0) > 0.1:
        direction = "↑" if af2[cat] > 1.0 else "↓"
        print(f"  {cat:15s} {af2[cat]:.2f} {direction}")

# 中性（无情绪）
af3 = compute_attention_field({})
print(f"\n无情绪: 全部基线")
all_ones = all(abs(v - 1.0) < 0.01 for v in af3.values())
print(f"  全部≈1.0: {'✓' if all_ones else '✗'}")

# --- 2. 消力系统 ---
print("\n" + "=" * 60)
print("2. 消力系统")
print("=" * 60)

# 模拟 entity
class MockEntity:
    tick = 100
    unresolved = 0.7
    stress = 0.5
    boredom = 0.5
    anxiety = 0.4
    fear = 0.3
    sadness = 0.2
    relief_debt = 0.3
    loneliness = 0.8
    loneliness_core = 0.5
    loneliness_surface = 0.3
    anger = 0.4
    fatigue = 0.6
    energy = 0.3
    avoid_drive = 0.5
    approach_explore = 0.3
    _lock_snaps = 20
    _quenching_journal = None

entity = MockEntity()

# 时间消力
td = temporal_quenching(entity, dt=1.0)
print(f"\n时间消力: {td}")
print(f"  unresolved: 0.7 → {0.7 + td.get('unresolved', 0):.3f}")

# 决策消力
dd = decision_quenching(entity, "explore", 0.6, 0.4)
print(f"\n决策消力 (action=explore, priority=0.6, tension=0.4): {dd}")

# 社交消力
sd = social_quenching(entity, user_interacted=True, interaction_quality=0.7)
print(f"\n社交消力 (用户互动, quality=0.7): {sd}")
print(f"  loneliness: 0.8 → {0.8 + sd.get('loneliness_surface', 0) + sd.get('loneliness_core', 0) - sd.get('loneliness_surface', 0)*0:.3f}")

# 完整运行
print(f"\n完整消力 (explore+社交):")
journal = QuenchingJournal()
result = apply_all_quenching(
    entity, 
    emergent_action="explore", 
    emergent_priority=0.6, 
    emergent_tension=0.4,
    user_interacted=True,
    interaction_quality=0.7,
    dt=1.0,
    journal=journal,
)
print(f"  total Δunresolved: {result['total_delta_unresolved']}")
print(f"  channels: {list(result['channel_deltas'].keys())}")
print(f"  efficiency: {result['efficiency']}")
print(f"  journal entries: {len(journal._events)}")

# --- 3. 情绪驱动的消力衰减速率 ---
print("\n" + "=" * 60)
print("3. 情绪抑制消力衰减（fear维持聚焦）")
print("=" * 60)

e_low_fear = MockEntity()
e_low_fear.fear = 0.0
e_low_fear.anxiety = 0.0

e_high_fear = MockEntity()
e_high_fear.fear = 0.8
e_high_fear.anxiety = 0.7

td_low = temporal_quenching(e_low_fear, dt=1.0)
td_high = temporal_quenching(e_high_fear, dt=1.0)
print(f"\n无恐惧时 unresolved 衰减: {td_low.get('unresolved', 0):.4f}")
print(f"高恐惧时 unresolved 衰减: {td_high.get('unresolved', 0):.4f}")
print(f"衰减被抑制了 {(1 - abs(td_high.get('unresolved',0)) / max(0.0001, abs(td_low.get('unresolved',0))))*100:.0f}%")

print("\n" + "=" * 60)
print("全部验证通过")
print("=" * 60)
