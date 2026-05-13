"""
XIA 多词组合教学课程 — v11.5
Hermes 推动虚拟状态，XIA 用锚点表选词+跨簇组合，积累 episode 记忆。

用法: python train_curriculum.py [--rounds N] [--verbose]
"""

import sys, os, random, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.entity_state import EntityState, force_set_state
from src.language_training import run_language_training_tick
from src.language_system.somatic_concept_map import ANCHOR_CLUSTERS

# ============================================================
# 教学课程：12 个身体感受簇 × 多种状态变体
# ============================================================

CURRICULUM = [
    # (标签, 状态字典, 期望词汇簇)
    # ── 1. 剧痛 + 紧张 ──
    ("剧痛+紧张", {
        "somatic_tone": -0.85, "avoid_drive": 0.80, "fear": 0.70,
        "stress": 0.75, "anxiety": 0.65, "energy": 0.25, "fatigue": 0.45,
    }),
    # ── 2. 极度疲劳 + 低落 ──
    ("疲劳+低落", {
        "somatic_tone": -0.40, "fatigue": 0.95, "energy": 0.05,
        "sadness": 0.55, "avoid_drive": 0.50, "anxiety": 0.30, "stress": 0.40,
    }),
    # ── 3. 轻松愉悦 ──
    ("轻松愉悦", {
        "somatic_tone": 0.70, "energy": 0.85, "joy": 0.80,
        "serenity": 0.70, "approach_drive": 0.60, "stress": 0.05, "fatigue": 0.05,
    }),
    # ── 4. 恐慌 ──
    ("恐慌", {
        "somatic_tone": -0.60, "fear": 0.95, "anxiety": 0.90,
        "stress": 0.85, "avoid_drive": 0.75, "energy": 0.40,
    }),
    # ── 5. 平静 ──
    ("平静", {
        "somatic_tone": 0.30, "serenity": 0.90, "stress": 0.02,
        "anxiety": 0.02, "fatigue": 0.10, "energy": 0.50, "avoid_drive": 0.05,
    }),
    # ── 6. 饥饿+干渴 ──
    ("饥饿干渴", {
        "somatic_tone": -0.50, "energy": 0.10, "stress": 0.45,
        "approach_drive": 0.60, "fatigue": 0.35, "anxiety": 0.30,
    }),
    # ── 7. 兴奋 ──
    ("兴奋", {
        "somatic_tone": 0.50, "excitement": 0.90, "energy": 0.85,
        "joy": 0.70, "approach_drive": 0.70, "curiosity": 0.80, "stress": 0.15,
    }),
    # ── 8. 恶心+不适 ──
    ("恶心不适", {
        "somatic_tone": -0.65, "disgust": 0.85, "avoid_drive": 0.70,
        "surprise": 0.60, "sadness": 0.40, "energy": 0.25, "stress": 0.50,
    }),
    # ── 9. 寒冷+僵硬 ──
    ("寒冷僵硬", {
        "somatic_tone": -0.55, "energy": 0.20, "approach_drive": 0.05,
        "avoid_drive": 0.60, "fatigue": 0.50, "anxiety": 0.45, "stress": 0.50,
    }),
    # ── 10. 压迫+窒息 ──
    ("压迫窒息", {
        "somatic_tone": -0.70, "stress": 0.85, "anxiety": 0.75,
        "avoid_drive": 0.65, "sadness": 0.55, "energy": 0.20, "fatigue": 0.55,
    }),
    # ── 11. 眩晕+失衡 ──
    ("眩晕失衡", {
        "somatic_tone": -0.45, "energy": 0.15, "fear": 0.60,
        "anxiety": 0.65, "surprise": 0.40, "stress": 0.55, "fatigue": 0.50,
    }),
    # ── 12. 温暖舒适 ──
    ("温暖舒适", {
        "somatic_tone": 0.65, "energy": 0.70, "joy": 0.60,
        "serenity": 0.75, "approach_drive": 0.55, "stress": 0.05, "fatigue": 0.08,
    }),
]

# ============================================================
# 教学主循环
# ============================================================

def train_curriculum(rounds_per_state=5, verbose=True):
    entity = EntityState()
    entity._freeze_state = True
    
    # 初始化 loneliness 到合理水平
    entity.loneliness_core = 0.40
    entity.loneliness_surface = 0.20
    entity.loneliness = 0.60
    
    total_ticks = 0
    results_log = []
    
    print("=" * 60)
    print("XIA 多词组合教学 — 开始")
    print(f"课程: {len(CURRICULUM)} 种状态 × {rounds_per_state} 轮 = {len(CURRICULUM)*rounds_per_state} tick")
    print("=" * 60)
    
    for label, base_state in CURRICULUM:
        print(f"\n▸ {label}")
        
        for r in range(rounds_per_state):
            # 微扰：在基础状态上加小噪声，避免同一状态重复选同一词
            state = dict(base_state)
            for dim in list(state.keys()):
                noise = random.gauss(0, 0.05)
                lo = -1.0 if dim == 'somatic_tone' else 0.0
                hi = 1.0
                state[dim] = max(lo, min(hi, state[dim] + noise))
            
            # 补全缺失维度为随机中性值
            for dim in ['loneliness','boredom','unresolved','danger_level',
                         'info_gap','pain','curiosity','anger']:
                if dim not in state:
                    state[dim] = random.uniform(0.1, 0.4)
            
            snapshot = entity.to_state_snapshot()
            result = run_language_training_tick(entity, snapshot, override_state=state)
            
            display = result.get('display', '?')
            best = result.get('best', '?')
            second = result.get('second')
            score = result.get('best_score', 0)
            
            if verbose:
                combo = f"{best}"
                if second:
                    c1 = ANCHOR_CLUSTERS.get(best, '?')
                    c2 = ANCHOR_CLUSTERS.get(second, '?')
                    combo = f"{best}({c1})+{second}({c2})"
                print(f"  tick{total_ticks:4d}: '{display:12s}' ← {combo:20s} (s={score:.3f})")
            
            results_log.append({
                'tick': total_ticks,
                'label': label,
                'display': display,
                'best': best,
                'second': second,
                'score': score,
            })
            total_ticks += 1
    
    # 统计
    print(f"\n{'=' * 60}")
    print(f"教学完成: {total_ticks} tick")
    print(f"loneliness_core: {entity.loneliness_core:.3f} (教学互动打折后)")
    
    # 热身词统计
    from src.language_system.word_warmup import get_warm_words
    warm = get_warm_words(entity)
    print(f"热身词: {len(warm)} 个 — {', '.join(warm)}")
    
    # 多词组合率
    multi = sum(1 for r in results_log if r['second'])
    print(f"多词组合率: {multi}/{total_ticks} ({100*multi/total_ticks:.0f}%)")
    
    # 簇覆盖
    cluster_hits = {}
    for r in results_log:
        c = ANCHOR_CLUSTERS.get(r['best'], '?')
        cluster_hits[c] = cluster_hits.get(c, 0) + 1
        if r['second']:
            c2 = ANCHOR_CLUSTERS.get(r['second'], '?')
            cluster_hits[c2] = cluster_hits.get(c2, 0) + 1
    
    print(f"\n簇使用分布:")
    for c in sorted(cluster_hits, key=lambda x: -cluster_hits[x]):
        bar = '█' * (cluster_hits[c] // 2)
        print(f"  {c:6s}: {cluster_hits[c]:3d}次 {bar}")
    
    return entity, results_log


if __name__ == '__main__':
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    verbose = '--verbose' in sys.argv or '-v' in sys.argv or len(sys.argv) <= 1
    train_curriculum(rounds_per_state=rounds, verbose=verbose)
