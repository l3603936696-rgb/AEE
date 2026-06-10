# -*- coding: utf-8 -*-
"""
验证输入驱动软混合对 thought_packet 的影响。

对比每句测试输入：
  - 原始 drive_vector -> think() -> suggestions/questions
  - blended_drive     -> think() -> suggestions/questions

运行：
    python tests/test_input_drive_think.py
"""
import copy, io, os, sys, json, math
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_DATASETS_OFFLINE", "1")

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# ---- 导入相关模块（必须在 env 设置后、用到前）----
from AEE.src.pipeline_runner.stages.s02b_input_drive_map import map_input_to_drive
from AEE.src.thinking_system.thinking_system import think as thinking_think
from AEE.src.world_model_reader.world_model_reader import query_world_model

# ---- 加载 entity 状态 ----
CORE_PATH = ROOT / "data" / "entity_core.json"
with open(CORE_PATH, encoding="utf-8") as f:
    core = json.load(f)

spm_data = core.get("_state_pattern_data", {})

# 从 entity_core 读取真实驱动力值（与 drive_system.py 输出维度对应）
RAW_DRIVE = {
    "curiosity":        core.get("curiosity", 0.5),
    "fatigue_avoid":    core.get("fatigue", 0.3),
    "loneliness_drive": core.get("loneliness", 0.3),
    "approach_drive":   core.get("approach_drive", 0.5),
    "avoid_drive":      core.get("avoid_drive", 0.3),
    "energy":           core.get("energy", 0.5),
    "boredom":          core.get("boredom", 0.2),
    "unresolved":       core.get("unresolved", 0.2),
    "explore":          core.get("curiosity", 0.5) * 0.8,
    "info_gap":         core.get("info_gap", 0.3),
    "stress":           core.get("stress", 0.1),
    "somatic_tone":     core.get("somatic_tone", 0.0),
}

# 真实 state_snapshot
STATE_SNAP = {k: core.get(k, 0.0) for k in [
    "energy", "fatigue", "loneliness", "curiosity", "boredom",
    "unresolved", "info_gap", "approach_drive", "avoid_drive",
    "somatic_tone", "stress", "pain", "joy", "anxiety",
]}

# 真实 wm_context（含 matched_rules 字段——think() 需要这个格式）
_wm_snapshot = {"rules": core.get("wm_rules", [])}
WM_CONTEXT = query_world_model([], copy.deepcopy(_wm_snapshot))

# ---- 常量（和 s03_think.py 保持一致）----
INPUT_DRIVE_BLEND_SCALE = 0.3
INPUT_DRIVE_BLEND_MAX   = 0.25

THINKING_PARAMS = {
    "thinking_activation_threshold": 0.3,
    "max_thinking_steps": 3,
    "thinking_timeout_ms": 3000,
    "thinking_time_budget_ms": 1000,
    "max_suggestions": 3,
    "very_low_confidence_threshold": 0.4,
}

TEST_INPUTS = [
    "帮我查资料",
    "你还在吗",
    "不知道怎么办",
    "我今天有点累",
    "薛定谔的猫",
]

SEP = "-" * 60

def fmt_sugg(packet):
    suggs = packet.get("suggestions", [])
    qs    = packet.get("questions", [])
    lines = []
    for s in suggs[:3]:
        if isinstance(s, dict):
            action = s.get("action", "?")
            reason = str(s.get("reason", ""))[:40]
            pri    = round(s.get("priority", 0.0), 2)
            lines.append(f"  建议[{action}] {reason} (p={pri})")
        else:
            lines.append(f"  建议: {str(s)[:50]}")
    for q in qs[:2]:
        if isinstance(q, dict):
            qtype = q.get("type", "?")
            dims  = ",".join(str(d)[:10] for d in q.get("dims", [])[:3])
            conf  = round(q.get("confidence", 0.0), 2)
            lines.append(f"  问题[{qtype}] dims=[{dims}] conf={conf}")
        else:
            lines.append(f"  问题: {str(q)[:50]}")
    return "\n".join(lines) if lines else "  (无)"

print(f"\n{SEP}")
print("输入驱动软混合 -> thought_packet 对比测试")
print(SEP)
print(f"wm matched_rules: {len(WM_CONTEXT.get('matched_rules', []))}")
print(f"基础 drive: curiosity={RAW_DRIVE['curiosity']:.2f}  "
      f"fatigue_avoid={RAW_DRIVE['fatigue_avoid']:.2f}  "
      f"loneliness_drive={RAW_DRIVE['loneliness_drive']:.2f}")
print(SEP)

for text in TEST_INPUTS:
    print(f"\n>> 输入: [{text}]")

    # s02b 映射
    map_result = map_input_to_drive(
        input_text=text,
        spm_data=spm_data,
        current_drive_state=RAW_DRIVE,
    )
    input_drive = map_result.get("drive_vector", {}) or {}
    best_sim    = float(map_result.get("best_similarity", 0.0))
    resonances  = map_result.get("all_resonances", {}) or {}
    top_res     = max(resonances.values(), default=0.0)
    input_conf  = max(best_sim, top_res)
    blend       = min(input_conf * INPUT_DRIVE_BLEND_SCALE, INPUT_DRIVE_BLEND_MAX)

    print(f"  layers={map_result.get('layers_used',[])}  "
          f"best={map_result.get('best_symbol','—')}  "
          f"conf={input_conf:.3f}  blend={blend:.3f}")

    # 混合向量
    dims = set(RAW_DRIVE) | set(input_drive)
    blended = {
        dim: RAW_DRIVE.get(dim, 0.0) * (1.0 - blend) + input_drive.get(dim, 0.0) * blend
        for dim in dims
    } or dict(RAW_DRIVE)

    # 打印混合后关键维度差异（只显示差值 > 0.02 的）
    diffs = {d: round(blended[d] - RAW_DRIVE.get(d, 0.0), 3)
             for d in blended if abs(blended[d] - RAW_DRIVE.get(d, 0.0)) > 0.02}
    if diffs:
        print(f"  drive delta: {diffs}")

    # 原始 think
    try:
        pkt_orig = thinking_think(WM_CONTEXT, RAW_DRIVE, STATE_SNAP, THINKING_PARAMS)
    except Exception as e:
        pkt_orig = {"suggestions": [], "questions": [], "_err": str(e)}

    # 混合 think
    try:
        pkt_blend = thinking_think(WM_CONTEXT, blended, STATE_SNAP, THINKING_PARAMS)
    except Exception as e:
        pkt_blend = {"suggestions": [], "questions": [], "_err": str(e)}

    if pkt_orig.get("_err"):
        print(f"  [原始] 错误: {pkt_orig['_err']}")
    else:
        print("  [原始 drive]")
        print(fmt_sugg(pkt_orig))

    if pkt_blend.get("_err"):
        print(f"  [混合] 错误: {pkt_blend['_err']}")
    else:
        print("  [混合 drive]")
        print(fmt_sugg(pkt_blend))

print(f"\n{SEP}")
