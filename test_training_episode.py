"""
验证训练 episode 注入 — 2026-05-10
用法: cd E:\XIA && python test_training_episode.py
"""
import sys, os
sys.path.insert(0, '.')
os.chdir('E:\\XIA' if os.path.exists('E:\\XIA') else '.')

from src.entity_state import EntityState
from src.language_training import run_language_training_tick

OK = 0
FAIL = 0

print("=" * 60)
print("测试 1: 训练 tick 产生 episode 写入 episodes.db")
print("=" * 60)

entity = EntityState()
entity._freeze_state = True

# 设定一个"剧痛"状态，预期选"痛"
state = {
    "somatic_tone": -0.80,
    "avoid_drive": 0.70,
    "fear": 0.65,
    "stress": 0.80,
    "fatigue": 0.40,
    "energy": 0.30,
    "loneliness": 0.50,
    "boredom": 0.30,
    "unresolved": 0.20,
    "danger_level": 0.30,
    "info_gap": 0.30,
    "approach_drive": 0.20,
    "pain": 0.60,
}

snapshot = entity.to_state_snapshot()
result = run_language_training_tick(entity, snapshot, override_state=state)

print(f"  选词: '{result.get('best')}'")
print(f"  得分: {result.get('best_score', 0):.3f}")
print(f"  候选数: {result.get('cand_count', 0)}")

if result.get('best'):
    OK += 1
    print(f"  PASS: 成功选出词 '{result['best']}'")
else:
    FAIL += 1
    print(f"  FAIL: 未选出词")

# 验证 episode 是否写入数据库
print(f"\n{'=' * 60}")
print("测试 2: 验证 episode 已写入 episodes.db")
print("=" * 60)

from src.memory_hub.episodes_db import get_episode_by_id, init_db

init_db()
ep = get_episode_by_id(entity.tick - 1)  # tick 已递增，所以 -1

if ep:
    print(f"  找到 episode: iteration_id={ep.iteration_id}")
    print(f"  output_text: '{ep.output_text}'")
    print(f"  tags: {ep.tags}")
    print(f"  importance: {ep.importance:.3f}")
    if ep.output_text == result.get('best'):
        OK += 1
        print(f"  PASS: episode 词与训练选词一致")
    else:
        FAIL += 1
        print(f"  FAIL: episode 词 '{ep.output_text}' ≠ 训练选词 '{result.get('best')}'")
else:
    FAIL += 1
    print(f"  FAIL: 未找到 episode (iteration_id={entity.tick - 1})")

# 验证 state_snapshot 内容
print(f"\n{'=' * 60}")
print("测试 3: episode 包含完整虚拟状态")
print("=" * 60)

if ep and ep.state_snapshot:
    snap = ep.state_snapshot
    if isinstance(snap, str):
        import json
        snap = json.loads(snap)
    keys_ok = all(k in snap for k in ['somatic_tone', 'avoid_drive', 'fear', 'stress', 'fatigue'])
    if keys_ok:
        OK += 1
        print(f"  PASS: state_snapshot 包含核心维度")
        print(f"    somatic_tone={snap.get('somatic_tone', '?')}")
        print(f"    avoid_drive={snap.get('avoid_drive', '?')}")
        print(f"    fear={snap.get('fear', '?')}")
    else:
        FAIL += 1
        print(f"  FAIL: state_snapshot 缺少核心维度")
else:
    FAIL += 1
    print(f"  FAIL: episode 无 state_snapshot")

print(f"\n{'=' * 60}")
print(f"结果: {OK} 通过, {FAIL} 失败")
if FAIL == 0:
    print("全部验证通过!")
else:
    print("有测试失败，需要修复。")
print("=" * 60)
