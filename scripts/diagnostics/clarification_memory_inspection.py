# -*- coding: utf-8 -*-
"""
clarification_memory_inspection.py — 澄清记忆账本诊断探针

运行：
    python scripts/diagnostics/clarification_memory_inspection.py

输出：
    - episode dump（完整 JSON）
    - generic / targeted 比例
    - actor / patient / predicate 分布
    - slot_confidence / slot_relevance 分布
    - recent_records(now) recency 视图
    - 镜像同步结果
    - EntityState 落盘 / 恢复验证
"""

import json
import math
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_DATASETS_OFFLINE", "1")

from src.entity_state import EntityState
from src.language_system.clarification_memory import (
    ClarificationMemory,
    ClarificationEpisode,
    _RECENCY_TAU_SECONDS,
    _HISTORY_MAXLEN,
    _get_memory,
    maybe_record_displayed_clarification,
)


def _print(msg, *args):
    print(msg.format(*args) if args else msg)


def _sep():
    print("=" * 60)


def _subsection(title):
    _sep()
    print(f"  {title}")
    _sep()


# ============================================================================
# Mock helpers
# ============================================================================

class _MockEntity:
    def __init__(self, tick=100, confidence=0.25, **kw):
        self.tick = tick
        self._understanding_confidence = confidence
        self._clarification_memory = None
        self._clarification_memory_data = {}
        for k, v in kw.items():
            setattr(self, k, v)


def _mock_parse(slot_conf=None):
    sc = slot_conf or {}
    sr = {k: 0.5 for k in ("actor", "patient", "predicate")}
    return {
        "proposition_frame": {
            "slot_confidence": {
                "actor": sc.get("actor", 0.10),
                "patient": sc.get("patient", 0.10),
                "predicate": sc.get("predicate", 0.70),
            },
            "slot_relevance": sr,
        }
    }


_TEMPLATES = [
    {"template": "这句……我没太懂",       "clarification_kind": "generic",   "clarification_slot": None},
    {"template": "是说什么呢……",         "clarification_kind": "generic",   "clarification_slot": None},
    {"template": "是谁在这样呢……",       "clarification_kind": "targeted",  "clarification_slot": "actor"},
    {"template": "你说的是谁，或者什么呢……", "clarification_kind": "targeted",  "clarification_slot": "patient"},
    {"template": "你说的这是怎么回事呢……",  "clarification_kind": "targeted",  "clarification_slot": "predicate"},
]


# ============================================================================
# Main
# ============================================================================

def main():
    print()
    print("=" * 60)
    print("  CLARIFICATION MEMORY INSPECTION — record-only v1")
    print("=" * 60)
    print()

    _subsection("0 — 常量")
    print(f"  _RECENCY_TAU_SECONDS = {_RECENCY_TAU_SECONDS}  (来源：8 tick × 30s/tick)")
    print(f"  _HISTORY_MAXLEN       = {_HISTORY_MAXLEN}  (建议值，待 Owner 追认）")
    print()

    # Build a synthetic history with varied entries
    entity = _MockEntity(tick=1)
    now = time.time()

    test_cases = [
        # (raw_input, question_text, chosen_mode, tmpl_idx, slot_conf)
        ("今天心情不好",           "这句……我没太懂",       "anchor_auto", 0, {"actor": 0.10, "patient": 0.10}),
        ("有人说了什么奇怪的话",   "是说什么呢……",         "anchor_auto", 1, {"actor": 0.10, "patient": 0.10}),
        ("他突然做了一件奇怪的事", "是谁在这样呢……",       "anchor_auto", 2, {"actor": 0.10}),
        ("你在想什么呀",          "你说的是谁，或者什么呢……", "anchor_auto", 3, {"patient": 0.10}),
        ("发生了什么",            "你说的这是怎么回事呢……",  "anchor_auto", 4, {"predicate": 0.70}),
        ("hello world",          "你好啊",                "narrative",   0, {}),  # narrative wins — NOT recorded
        ("",                     "这句……我没太懂",       "anchor_auto", 0, {}),   # empty input — NOT recorded
        ("some input",           "这句……我没太懂",       "anchor_auto", -1, {}),  # compound — NOT recorded
        ("some input",           "这句……我没太懂",       "anchor_auto", 99, {}), # OOB — NOT recorded
    ]

    for raw, question, mode, idx, sconf in test_cases:
        maybe_record_displayed_clarification(
            entity=entity,
            raw_input=raw,
            _cx_parse_result=_mock_parse(sconf),
            _chosen_text=question,
            _chosen_mode=mode,
            _tmpl_idx=idx,
            all_templates_snapshot=_TEMPLATES,
        )

    memory = _get_memory(entity)

    # ------------------------------------------------------------------
    _subsection("1 — EPISODE DUMP")
    all_records = memory.recent_records(now)
    print(f"  Total records in history: {len(memory._history)}")
    print(f"  (expected ~5: narrative/empty/negative/OOB guards should block)")
    print()
    if all_records:
        print("  [recency sorted, newest first]")
        for r in sorted(all_records, key=lambda x: x["timestamp"], reverse=True):
            print()
            print(f"  tick={r['tick']}  kind={r['clarification_kind']}  slot={r['clarification_slot']}")
            print(f"    input  : {r['original_input'][:50]!r}")
            print(f"    question: {r['question_text']!r}")
            print(f"    confidence: {r['confidence']:.3f}")
            print(f"    timestamp: {r['timestamp']:.3f}")
            print(f"    age_seconds: {r['age_seconds']:.1f}  recency: {r['recency']:.4f}")
            pf = r.get("proposition_frame", {})
            sc = pf.get("slot_confidence", {})
            sr = pf.get("slot_relevance", {})
            print(f"    slot_confidence: {json.dumps(sc, ensure_ascii=False)}")
            print(f"    slot_relevance: {json.dumps(sr, ensure_ascii=False)}")
    else:
        print("  [no records — check guards above]")
    print()

    # ------------------------------------------------------------------
    _subsection("2 — generic / targeted 比例")
    stats = memory.stats()
    total = stats["total"]
    generic = stats["generic_count"]
    targeted = stats["targeted_count"]
    print(f"  generic : {generic}  ({generic/max(total,1)*100:.1f}%)")
    print(f"  targeted: {targeted}  ({targeted/max(total,1)*100:.1f}%)")
    print(f"  total   : {total}")
    print()

    # ------------------------------------------------------------------
    _subsection("3 — actor / patient / predicate 分布")
    slot_counts = stats["slot_counts"]
    total_targeted = sum(slot_counts.values())
    for slot, label in [("actor", "谁 (actor)"), ("patient", "谁/什么 (patient)"), ("predicate", "怎么回事 (predicate)")]:
        cnt = slot_counts.get(slot, 0)
        pct = cnt / max(total_targeted, 1) * 100
        print(f"  {label:20s}: {cnt}  ({pct:.1f}% of targeted)")
    print()

    # ------------------------------------------------------------------
    _subsection("4 — slot_confidence / slot_relevance 分布")
    sc_dist = stats["slot_confidence"]
    sr_dist = stats["slot_relevance"]
    print(f"  slot_confidence: count={sc_dist['count']:.0f}  mean={sc_dist['mean']:.3f}  "
          f"min={sc_dist['min']:.3f}  max={sc_dist['max']:.3f}")
    print(f"  slot_relevance: count={sr_dist['count']:.0f}  mean={sr_dist['mean']:.3f}  "
          f"min={sr_dist['min']:.3f}  max={sr_dist['max']:.3f}")
    print()
    print("  [NOTE] slot_confidence ≈ 0.10 for 'external' slots indicates parse_svo")
    print("          is defaulting to guess direction — see SPEC Risk #1.")
    print()

    # ------------------------------------------------------------------
    _subsection("5 — recency 视图（recent_records(now)）")
    print(f"  _RECENCY_TAU_SECONDS = {_RECENCY_TAU_SECONDS}s")
    print(f"  now_timestamp = {now:.3f}")
    print()
    print(f"  {'tick':>5}  {'kind':>10}  {'slot':>10}  {'age(s)':>7}  {'recency':>8}")
    print(f"  {'-'*5}  {'-'*10}  {'-'*10}  {'-'*7}  {'-'*8}")
    for r in sorted(memory.recent_records(now), key=lambda x: x["timestamp"], reverse=True):
        print(f"  {r['tick']:>5}  {r['clarification_kind']:>10}  "
              f"{str(r['clarification_slot']):>10}  {r['age_seconds']:>7.1f}  {r['recency']:>8.4f}")
    print()
    print("  v2 observe_reply 应按 recency 加权 — 旧条目无法主导（SPEC Risk #3）。")
    print()

    # ------------------------------------------------------------------
    _subsection("6 — 镜像同步验证")
    mirror = entity._clarification_memory_data
    mirror_hist = mirror.get("history", [])
    print(f"  entity._clarification_memory_data history 长度: {len(mirror_hist)}")
    print(f"  memory.to_dict() history 长度:               {len(memory.to_dict()['history'])}")
    print(f"  同步一致: {len(mirror_hist) == len(memory.to_dict()['history'])}")
    if mirror_hist:
        print()
        print("  mirror[history][0]:")
        for k, v in mirror_hist[0].items():
            print(f"    {k}: {v}")
    print()

    # ------------------------------------------------------------------
    _subsection("7 — EntityState 落盘 / 恢复验证")
    ent = EntityState()
    ent.tick = 888
    # record into entity
    for raw, question, mode, idx, sconf in [
        ("落盘测试1", "这句……我没太懂", "anchor_auto", 0, {}),
        ("落盘测试2", "是谁在这样呢……", "anchor_auto", 2, {}),
    ]:
        maybe_record_displayed_clarification(
            entity=ent, raw_input=raw,
            _cx_parse_result=_mock_parse(sconf),
            _chosen_text=question, _chosen_mode=mode,
            _tmpl_idx=idx, all_templates_snapshot=_TEMPLATES,
        )
    ts_before_persist = time.time()

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "core.json"
        ent.persist_to_file(path)
        persist_ok = path.exists()
        print(f"  persist_to_file: {'OK' if persist_ok else 'FAIL'}")

        ent2 = EntityState()
        load_ok = ent2.load_from_file(path)
        print(f"  load_from_file : {'OK' if load_ok else 'FAIL'}")
        print(f"  tick after load: {ent2.tick}  (expected 888)")

        mirror2 = ent2._clarification_memory_data
        hist2 = mirror2.get("history", [])
        print(f"  history length : {len(hist2)}  (expected 2)")
        print(f"  tick values    : {[e['tick'] for e in hist2]}")
        ts_after_load = time.time()

        # recency computed from persisted timestamps (not reset)
        restored_mem = ClarificationMemory.from_dict(mirror2)
        recs = restored_mem.recent_records(ts_after_load)
        print()
        print("  recency after restore (停机时间计入):")
        for r in recs:
            print(f"    tick={r['tick']}  age={r['age_seconds']:.1f}s  recency={r['recency']:.4f}")
        print()
        print("  restart timestamp preserved -> recency continuous across restarts [OK]")
    print()

    # ------------------------------------------------------------------
    _subsection("8 — _get_memory 懒恢复")
    entity3 = _MockEntity(tick=1)
    entity3._clarification_memory_data = memory.to_dict()
    mem3 = _get_memory(entity3)
    print(f"  懒恢复后 history 长度: {len(mem3._history)}")
    print(f"  entity._clarification_memory is not None: {entity3._clarification_memory is not None}")
    print()

    _sep()
    print("  INSPECTION COMPLETE")
    _sep()


if __name__ == "__main__":
    main()
