"""临时观测探针：读 entity_core.json 的闭环相关字段。无副作用。"""
import json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

path = sys.argv[1] if len(sys.argv) > 1 else r"E:\XIA\data\entity_core.json"
with open(path, encoding="utf-8") as f:
    d = json.load(f)

# 顶层定位（兼容可能的嵌套）
top = d
for k in ("state", "entity", "core"):
    if "info_gap" not in top and isinstance(d.get(k), dict):
        top = d[k]

def g(k):
    v = top.get(k)
    return round(v, 4) if isinstance(v, (int, float)) else v

print(f"tick={top.get('tick')}")
print(f"info_gap   = {g('info_gap')}")
print(f"unresolved = {g('unresolved')}")
print(f"loneliness = {g('loneliness')}")
print(f"energy     = {g('energy')}")

# 淬火记录
qd = top.get("_quenching_data") or d.get("_quenching_data") or {}
hist = qd.get("history") or qd.get("_history") or []
print(f"\n_quenching_data.history len = {len(hist)}")
recent = hist[-6:]
for r in recent:
    eff = r.get("quenching_efficiency")
    tpl = r.get("template_idx")
    expr = (r.get("expression") or "")[:18]
    tk = r.get("tick")
    print(f"  tick={tk} eff={eff} tpl={tpl} expr='{expr}'")

# 模板效率聚合（看哪个 template_idx 攒了正 efficiency）
from collections import defaultdict
sums = defaultdict(float); cnts = defaultdict(int)
for r in hist:
    i = r.get("template_idx", -1)
    sums[i] += float(r.get("quenching_efficiency") or 0.0); cnts[i] += 1
print("\n模板效率聚合 (template_idx: sum_eff/n):")
for i in sorted(sums):
    print(f"  tpl={i}: sum={round(sums[i],4)} n={cnts[i]} avg={round(sums[i]/max(1,cnts[i]),4)}")

# wm 规则置信度
rules = top.get("wm_rules") or d.get("wm_rules") or []
print(f"\nwm_rules n = {len(rules)}")
for r in rules:
    if isinstance(r, dict):
        trig = (r.get("predicts") or {}).get("trigger", "") if isinstance(r.get("predicts"), dict) else ""
        print(f"  conf={round(float(r.get('confidence',0)),4)} trig='{trig}' src_n={r.get('source_experience_count')}")
