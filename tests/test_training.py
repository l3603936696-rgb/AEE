"""测试 BGE 语义分析器 + 候选生成器 - 模拟一轮语言训练闭环"""
import sys, os
sys.path.insert(0, "E:\\XIA\\AEE")
os.environ["HF_HOME"] = "E:\\huggingface_cache"
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

# 模拟一个驱动力场状态
drive_state = {
    "avoid_drive": 0.65,
    "approach_drive": 0.30,
    "loneliness": 0.82,
    "energy": 0.35,
    "somatic_tone": -0.40,
    "unresolved": 0.55,
    "boredom": 0.45,
}

candidates = [
    "嗯……",
    "有点累了，但也不想一个人呆着",
    "算了。",
    "能陪我一会吗",
    "不知道说什么",
    "空荡荡的",
]

print("=== BGE SemanticAnalyzerV2 ===")
from AEE.src.language_system.bge_analyzer import SemanticAnalyzerV2
analyzer = SemanticAnalyzerV2()
scores = analyzer.analyze(drive_state, candidates)
for cand, score in sorted(zip(candidates, scores), key=lambda x: x[1], reverse=True):
    bar = "#" * int(score * 20)
    print(f"  [{score:.3f}] {bar:20s} {cand}")

print("\n=== Quenching Tracker ===")
from AEE.src.language_system.quenching import QuenchingTracker
qt = QuenchingTracker(history_maxlen=500)
eff = qt.record(drive_state, candidates[0], 0.55, 0.20)
print(f"  Quenching efficiency: {eff:.3f}")
print(f"  SNR: {qt.get_snr():.3f}")

print("\n=== Strategy Map ===")
from AEE.src.language_system.strategy_map import StrategyMap
sm = StrategyMap()
sm.record_path(drive_state, drive_state, candidates[0], eff, "test_tick")
best = sm.get(drive_state)
print(f"  Best path: {best.expression if best else 'none'}")

print("\n=== OK - Training loop verified ===")
