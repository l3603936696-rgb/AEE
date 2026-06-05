"""临时观测：周期采样规则字段数 + 僵尸数 + 认知 gain。无副作用，只读。"""
import json, time, io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
PATH = r"E:\XIA\data\entity_core.json"

def sample():
    d = json.load(open(PATH, encoding="utf-8"))
    rules = d.get("wm_rules") or []
    fc, zombie, gt6 = [], 0, 0
    offfloor_action = 0
    for r in rules:
        if not isinstance(r, dict): continue
        dd = r.get("expected_deltas") or {}
        n = len(dd) if isinstance(dd, dict) else 0
        fc.append(n)
        c = float(r.get("confidence", 0)); st = r.get("status", "")
        if c <= 0.051 and st == "decayed": zombie += 1
        if n > 6: gt6 += 1
        pred = r.get("predicts") or {}
        trig = pred.get("trigger", "") if isinstance(pred, dict) else ""
        if trig.startswith("action") and c > 0.15: offfloor_action += 1
    fc.sort()
    med = fc[len(fc)//2] if fc else 0
    return dict(tick=d.get("tick"), n=len(fc), med=med, mx=(fc[-1] if fc else 0),
                mean=round(sum(fc)/max(1,len(fc)),1), gt6=gt6, zombie=zombie,
                offfloor_action=offfloor_action)

for i in range(14):  # ~14 × 180s ≈ 42 min
    try:
        s = sample()
        print(f"[{time.strftime('%H:%M:%S')}] tick={s['tick']} 规则={s['n']} "
              f"字段中位={s['med']} max={s['mx']} 均值={s['mean']} "
              f">6字段={s['gt6']} 僵尸={s['zombie']} 脱离地板的action规则={s['offfloor_action']}",
              flush=True)
    except Exception as e:
        print(f"[{time.strftime('%H:%M:%S')}] ERR {e!r}", flush=True)
    time.sleep(180)
print("=== watch done ===", flush=True)
