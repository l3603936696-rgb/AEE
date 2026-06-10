"""
XIA 锚点校准训练 — v11.5 新增 14 词验证
用法: cd E:\XIA && python train_new_anchors.py

Hermes 扮演"老师"：设定虚拟状态 → XIA 锚点匹配选词 → 输出验证
"""
import sys
sys.path.insert(0, '.')
import time
from AEE.src.entity_state import EntityState
from AEE.src.language_training import run_language_training_tick

entity = EntityState()
entity._freeze_state = True  # 跳过管线回拉

# ============================================================
# 训练集：每个状态推一次，看 XIA 选什么词
# ============================================================
TRAINING_SET = [
    # (状态名, override_state, 期望词)
    # ── 测试新锚点 ──
    ("麻木钝感", {
        "somatic_tone": -0.40, "fatigue": 0.60, "avoid_drive": 0.40,
        "anxiety": 0.30, "energy": 0.30, "curiosity": 0.10,
    }, ["木", "麻"]),
    
    ("堵塞胸闷", {
        "somatic_tone": -0.35, "anxiety": 0.55, "avoid_drive": 0.45,
        "stress": 0.50, "sadness": 0.40,
    }, ["堵", "闷"]),
    
    ("搏动跳痛", {
        "stress": 0.55, "anxiety": 0.50, "energy": 0.60,
        "somatic_tone": -0.20,
    }, ["跳", "抖"]),
    
    ("抽搐痉挛", {
        "avoid_drive": 0.70, "somatic_tone": -0.75, "fear": 0.55,
        "stress": 0.50, "energy": 0.20,
    }, ["抽", "痛"]),
    
    ("内部灼烧", {
        "avoid_drive": 0.75, "somatic_tone": -0.80, "fear": 0.55,
        "stress": 0.50, "anger": 0.40,
    }, ["烧", "烫"]),
    
    ("外力压迫", {
        "anxiety": 0.60, "stress": 0.55, "somatic_tone": -0.45,
        "avoid_drive": 0.45, "sadness": 0.40,
    }, ["压", "重"]),
    
    ("绷紧张力", {
        "anxiety": 0.60, "stress": 0.55, "avoid_drive": 0.45,
        "fatigue": 0.35, "somatic_tone": -0.25,
    }, ["绷", "紧"]),
    
    ("恐惧蜷缩", {
        "fear": 0.70, "avoid_drive": 0.65, "approach_drive": 0.05,
        "somatic_tone": -0.40, "anxiety": 0.50,
    }, ["缩", "僵"]),
    
    ("胀撑饱满", {
        "somatic_tone": -0.40, "stress": 0.50, "avoid_drive": 0.35,
        "approach_drive": 0.15, "anxiety": 0.30,
    }, ["撑", "胀"]),
    
    ("空洞虚无", {
        "sadness": 0.65, "somatic_tone": -0.45, "energy": 0.10,
        "joy": -0.30, "curiosity": 0.05,
    }, ["空", "沉"]),
    
    ("酥麻舒适", {
        "joy": 0.55, "serenity": 0.50, "somatic_tone": 0.40,
        "energy": 0.25, "excitement": 0.35,
    }, ["酥", "飘"]),
    
    ("极度疲乏", {
        "fatigue": 0.90, "energy": 0.05, "sadness": 0.60,
        "avoid_drive": 0.55, "approach_drive": 0.05, "somatic_tone": -0.40,
        "curiosity": 0.00,
    }, ["乏", "累"]),
    
    ("黏腻不适", {
        "avoid_drive": 0.45, "somatic_tone": -0.30,
        "disgust": 0.50, "anxiety": 0.30,
    }, ["黏", "湿"]),
    
    ("下坠恐惧", {
        "fear": 0.65, "somatic_tone": -0.50, "anxiety": 0.55,
        "sadness": 0.45, "energy": 0.20,
    }, ["坠", "沉"]),
    
    # ── 复习旧锚点（盲区调整后验证）──
    ("极度疲惫_v2", {
        "fatigue": 0.85, "energy": 0.05, "avoid_drive": 0.50,
        "approach_drive": 0.05, "sadness": 0.40, "somatic_tone": -0.35,
    }, ["累", "乏"]),
    
    ("困倦挣扎", {
        "fatigue": 0.75, "energy": 0.15, "avoid_drive": 0.35,
        "curiosity": 0.05, "somatic_tone": -0.20,
    }, ["困", "累"]),
    
    ("僵硬紧张", {
        "avoid_drive": 0.60, "approach_drive": 0.05,
        "somatic_tone": -0.30, "stress": 0.45,
    }, ["硬", "僵"]),
    
    ("干渴紧迫", {
        "somatic_tone": -0.55, "energy": 0.15,
        "stress": 0.50, "anxiety": 0.45, "approach_drive": 0.30,
    }, ["渴", "干"]),
]

# ============================================================
# 训练循环
# ============================================================
print("=" * 60)
print("XIA 锚点校准训练 — v11.5")
print(f"训练样本: {len(TRAINING_SET)} 个状态")
print("=" * 60)

results = []
for name, state, expected in TRAINING_SET:
    # 确保所有关键维度都在范围内
    for dim in ["curiosity", "joy", "excitement", "serenity", "anger",
                "fear", "sadness", "disgust", "anxiety", "surprise"]:
        if dim not in state:
            state[dim] = 0.0
    
    result = run_language_training_tick(entity, entity.to_state_snapshot(), 
                                          override_state=state)
    
    best = result.get("best", "?")
    score = result.get("best_score", 0)
    match = "✓" if best in expected else ("△" if any(e in best or best in e for e in expected) else "✗")
    
    results.append((name, best, score, match, expected))
    
    # 显示状态摘要
    st = f"s={state.get('somatic_tone',0):+.2f}"
    print(f"\n[{match}] {name:<12} {st:<8} → {best:<4} (score={score:.3f})  期望: {expected}")
    
    # 显示 top 3 候选
    if result.get("cand_count", 0) > 1:
        cand_str = f"  top3: {best}"
        print(cand_str, end="")

print("\n" + "=" * 60)
correct = sum(1 for _, _, _, m, _ in results if m == "✓")
partial = sum(1 for _, _, _, m, _ in results if m == "△")
wrong = sum(1 for _, _, _, m, _ in results if m == "✗")
print(f"结果: ✓={correct}  △={partial}  ✗={wrong}")
print("=" * 60)
