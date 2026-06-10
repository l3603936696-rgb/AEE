import json

with open('e:\\XIA\\data\\entity_core.json', encoding='utf-8') as f:
    d = json.load(f)

lines = []

lines.append('=== 基础状态 ===')
lines.append(f"tick={d.get('tick', '?')}")
lines.append(f"energy={d.get('energy', 0):.3f}  loneliness={d.get('loneliness', 0):.3f}")
lines.append(f"joy={d.get('joy', 0):.3f}  fatigue={d.get('fatigue', 0):.3f}")
lines.append(f"boredom={d.get('boredom', 0):.3f}  info_gap={d.get('info_gap', 0):.3f}")
lines.append('')

uv = d.get('_unlocked_vocabulary', [])
lines.append(f'=== 解锁词汇: {len(uv)} 个 ===')
if uv:
    sample = ', '.join(str(v) for v in uv[:20])
    lines.append(f'  {sample}')
    if len(uv) > 20:
        lines.append(f'  ... 还有 {len(uv)-20} 个')
lines.append('')

wet = d.get('_word_exposure_tracker', {})
if isinstance(wet, dict) and wet:
    hot = [(k, v) for k, v in wet.items() if isinstance(v, dict) and v.get('hit_count', 0) >= 2]
    hot.sort(key=lambda x: x[1].get('hit_count', 0), reverse=True)
    lines.append(f'=== 热词追踪: {len(wet)} 个词, 热词(hit>=2): {len(hot)} 个 ===')
    for k, v in hot[:15]:
        lines.append(f"  {k}: hits={v.get('hit_count',0)} warm={v.get('warm', False)} variant={v.get('variant_count',0)}")
lines.append('')

qd = d.get('_quenching_data', {})
if isinstance(qd, dict) and qd:
    lines.append(f'=== Quenching: {len(qd)} 条 ===')
    for k, v in list(qd.items())[:10]:
        if isinstance(v, dict):
            eff = v.get('efficiency', '?')
            lines.append(f"  [{k}] eff={eff}")
lines.append('')

wm = d.get('wm_rules', [])
lines.append(f'=== WM 规则: {len(wm)} 条 ===')
for r in wm[:5]:
    lines.append(f"  {str(r)[:100]}")
lines.append('')

br = d.get('behavior_rules', [])
lines.append(f'=== 行为规则: {len(br)} 条 ===')

cel = d.get('_concept_exposure_log', {})
lines.append(f'=== 概念曝光: {len(cel)} 个 ===')

sm = d.get('_strategy_map_data', {})
lines.append(f'=== 策略图: {len(sm)} 条 ===')

# Sentence templates
from pathlib import Path
sent_file = Path('e:\\XIA\\data\\sentence_templates.json')
if sent_file.exists():
    with open(sent_file, encoding='utf-8') as f:
        st = json.load(f)
    lines.append(f'=== 句法模板: {len(st)} 条 ===')
    for t in st[:5]:
        lines.append(f"  {str(t)[:100]}")

with open('e:\\XIA\\diag_output.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))
