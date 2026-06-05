# -*- coding: utf-8 -*-
"""
clarification_learning_inspection.py — 澄清归属学习诊断探针

运行：
    python scripts/diagnostics/clarification_learning_inspection.py

输出（SPEC §4 inspection）：
    - episode dump（完整 JSON）
    - generic / targeted 归属质量分布
    - actor / patient / predicate 混淆矩阵（expected vs bound）
    - 无关换话题的误归属总质量
    - 新名字 / 短碎片回答的保留率
    - 弱回答后 remaining mass 是否保留
    - 重启恢复 + 重复事件幂等性验证
    - synthetic 与真实在线数据分开统计
"""

import hashlib
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
from src.language_system.clarification_memory import ClarificationMemory, ClarificationEpisode
from src.language_system.clarification_learning import (
    SlotEvidenceStore, observe_reply, episode_id, episode_id_from_dict,
    _get_evidence_store,
    _ATTRIB_TAU, _EVIDENCE_MAXLEN, _PROCESSED_EVENT_MAXLEN,
    _NO_MATCH_PRIOR, _ADJACENCY_TAU,
)


def _sep():
    print("=" * 60)


def _subsection(title):
    _sep()
    print(f"  {title}")
    _sep()


class _MockEntity:
    def __init__(self, tick=1, confidence=0.3, **kw):
        self.tick = tick
        self._understanding_confidence = confidence
        self._clarification_memory = None
        self._clarification_memory_data = {}
        self._clarification_evidence_store = None
        self._clarification_hints_data = {}
        for k, v in kw.items():
            setattr(self, k, v)


def _ep(kind, slot, original_input, ts, tick, qtext="这句我没太懂", confidence=0.3):
    return ClarificationEpisode(
        original_input=original_input,
        proposition_frame={"slot_confidence": {"actor": 0.5}, "slot_relevance": {"actor": 0.5}},
        clarification_kind=kind,
        clarification_slot=slot,
        question_text=qtext,
        confidence=confidence,
        tick=tick,
        timestamp=ts,
    )


def _seed_memory(entity, episodes):
    """替换 v1 镜像时同步清空运行时缓存，避免 synthetic 场景串场。"""
    entity._clarification_memory_data = ClarificationMemory(history=episodes).to_dict()
    entity._clarification_memory = None


def main():
    print()
    _sep()
    print("  CLARIFICATION LEARNING INSPECTION — observe-reply v2")
    _sep()
    print()

    _subsection("0 — 常量")
    print(f"  _ATTRIB_TAU                = {_ATTRIB_TAU}s")
    print(f"  _ADJACENCY_TAU             = {_ADJACENCY_TAU}")
    print(f"  _NO_MATCH_PRIOR            = {_NO_MATCH_PRIOR}")
    print(f"  _EVIDENCE_MAXLEN          = {_EVIDENCE_MAXLEN}")
    print(f"  _PROCESSED_EVENT_MAXLEN    = {_PROCESSED_EVENT_MAXLEN}")
    print()

    entity = _MockEntity(tick=1)
    now = time.time()

    # Synthetic scenarios
    print("## Synthetic Scenarios ##\n")

    # S1: 正常 targeted 归属
    _seed_memory(entity, [
        _ep("targeted", "actor",   "小王昨天去北京出差", ts=now - 5, tick=2, qtext="是谁在这样呢……"),
        _ep("targeted", "patient", "小王做了什么",       ts=now - 10, tick=1, qtext="你说的是谁，或者什么呢……"),
    ])

    # Reply matching actor
    r1 = observe_reply(entity, "小王啊，我朋友", now, "ipc_chat", "ev_s1_actor")
    print("S1 — 回复'小王啊，我朋友'匹配 actor-targeted:")
    print(f"  candidates: {len(r1.get('candidates', []))}")
    if r1.get('candidates'):
        c = max(r1["candidates"], key=lambda item: item["attributed_mass"])
        print(f"  top slot={c['slot']} mass={c['attributed_mass']:.4f} "
              f"relevance={c['semantic_relevance']:.3f} recency={c['recency']:.3f} adj={c['adjacency']:.3f}")
    print(f"  no_match_mass={r1.get('no_match_mass', 0):.4f}")
    assert abs(r1["total_mass_assigned"] + r1["no_match_mass"] - 1.0) < 1e-9
    assert len(entity._clarification_evidence_store._evidence) > 0
    print()

    # S2: 换话题 — no_match 主导
    r2 = observe_reply(entity, "今天天气真不错", now + 1, "ipc_chat", "ev_s2_topic")
    print("S2 — 换话题（天气）:")
    print(f"  no_match_mass={r2.get('no_match_mass', 0):.4f}")
    mis_mass = sum(c['attributed_mass'] for c in r2.get('candidates', []))
    print(f"  misattribution total mass={mis_mass:.4f}")
    print()

    # S3: 新名字（低熟悉度）不被压低
    r3 = observe_reply(entity, "小明做了那件事", now + 2, "ipc_chat", "ev_s3_new_name")
    print("S3 — 新名字'小明'（低熟悉度，不在 cue_input 中）:")
    if r3.get('candidates'):
        c = r3['candidates'][0]
        print(f"  mass={c['attributed_mass']:.4f} relevance={c['semantic_relevance']:.3f}")
        print(f"  [P1-c] 低熟悉度不被压低归属 mass={c['attributed_mass']:.4f}")
    print()

    # S4: generic 最新时不被旧 targeted 抢走（R2-1）
    _seed_memory(entity, [
        _ep("targeted", "actor", "旧问题targeted", ts=now - 200, tick=1, qtext="是谁在这样呢……"),
        _ep("generic",  None,    "新问题generic",  ts=now - 1,  tick=2, qtext="这句……我没太懂"),
    ])
    generic_before = len(entity._clarification_evidence_store._generic_obs)
    r4 = observe_reply(entity, "新问题的答案来了", now + 3, "ipc_chat", "ev_s4_generic")
    store4 = entity._clarification_evidence_store
    print("S4 — generic 最新，归属给它，不被旧 targeted 抢走:")
    print(f"  generic_observations count={len(store4._generic_obs)}")
    print(f"  SlotEvidence count={len(store4._evidence)}")
    if store4._generic_obs:
        g = store4._generic_obs[-1]
        print(f"  generic mass={g.attributed_mass:.4f}")
    assert len(store4._generic_obs) > generic_before
    print()

    # S5: 幂等
    evidence_before = len(entity._clarification_evidence_store._evidence)
    generic_before = len(entity._clarification_evidence_store._generic_obs)
    r5a = observe_reply(entity, "重复回答", now + 4, "ipc_chat", "ev_s5_dup")
    evidence_after_first = len(entity._clarification_evidence_store._evidence)
    generic_after_first = len(entity._clarification_evidence_store._generic_obs)
    r5b = observe_reply(entity, "这个不应出现", now + 5, "ipc_chat", "ev_s5_dup")
    print("S5 — 幂等（同 event_id）:")
    print(f"  first call skipped={r5a.get('skipped')} event={r5a.get('event_id')}")
    print(f"  second call skipped={r5b.get('skipped')} reason={r5b.get('reason')}")
    store5 = entity._clarification_evidence_store
    print(f"  evidence appended first={evidence_after_first - evidence_before}")
    assert len(store5._evidence) == evidence_after_first
    assert len(store5._generic_obs) == generic_after_first
    assert evidence_after_first + generic_after_first > evidence_before + generic_before
    print()

    # S6: external source
    r6 = observe_reply(entity, "reach发来的回复", now + 6, "external", "ev_s6_external")
    print("S6 — external source:")
    print(f"  skipped={r6.get('skipped')} source={r6.get('source')}")
    print()

    # S7: sibling 忽略
    r7 = observe_reply(entity, "糯糯说的话", now + 7, "sibling", "ev_s7_sibling")
    print("S7 — sibling 忽略:")
    print(f"  skipped={r7.get('skipped')} reason={r7.get('reason')}")
    print()

    _subsection("1 — evidence store 统计")
    store = entity._clarification_evidence_store
    stats = store.stats()
    for k, v in stats.items():
        if isinstance(v, dict):
            print(f"  {k}: {json.dumps(v, ensure_ascii=False)}")
        else:
            print(f"  {k}: {v}")
    print()

    _subsection("2 — aggregate 视图（effective_strength = mass x recency）")
    agg = store.aggregate(now + 10)
    print(f"  total items: {len(agg)}")
    print(f"  {'slot':>10}  {'eid[:12]':>12}  {'eff_str':>8}  {'mass':>6}  {'rec':>5}  {'rel':>5}")
    print(f"  {'-'*10}  {'-'*12}  {'-'*8}  {'-'*6}  {'-'*5}  {'-'*5}")
    for item in sorted(agg, key=lambda x: x["effective_strength"], reverse=True):
        eid_short = item["episode_id"][:12]
        print(f"  {item['slot']:>10}  {eid_short:>12}  "
              f"{item['effective_strength']:>8.4f}  {item['attributed_mass']:>6.4f}  "
              f"{item['recency']:>5.3f}  {item['semantic_relevance']:>5.3f}")
    print()

    _subsection("3 — generic observations")
    print(f"  total: {len(store._generic_obs)}")
    for obs in store._generic_obs:
        print(f"    eid={obs.episode_id[:12]} mass={obs.attributed_mass:.4f} "
              f"no_match={obs.no_match_mass:.4f} source={obs.source}")
    print()

    _subsection("4 — answered_mass 状态")
    for eid, mass in store._answered_mass.items():
        print(f"  {eid[:20]:>20}  remaining={1-mass:.4f}  mass={mass:.4f}")
    print()

    _subsection("5 — processed_event_ids 限容")
    print(f"  len={len(store._processed)}  maxlen={_PROCESSED_EVENT_MAXLEN}")
    print(f"  first={store._processed[0] if store._processed else 'N/A'}")
    print(f"  last={store._processed[-1] if store._processed else 'N/A'}")
    print()

    _subsection("6 — EntityState persist / load roundtrip")
    ent = EntityState()
    ent.tick = 999
    # seed with synthetic episodes and observe
    _seed_memory(ent, [
        _ep("targeted", "patient", "persist test", ts=time.time() - 5, tick=1),
    ])
    observe_reply(ent, "persist reply", time.time(), "ipc_chat", "ev_persist")
    hints_before = ent._clarification_hints_data

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "core.json"
        ent.persist_to_file(path)
        ent2 = EntityState()
        ok = ent2.load_from_file(path)
        print(f"  persist/load: {'OK' if ok else 'FAIL'}")
        print(f"  tick after load: {ent2.tick} (expected 999)")
        hints2 = ent2._clarification_hints_data
        print(f"  evidence count after load: {len(hints2.get('evidence', []))}")
        print(f"  answered_mass keys: {len(hints2.get('answered_mass', {}))}")
        print(f"  processed count: {len(hints2.get('processed_event_ids', []))}")
        store2 = _get_evidence_store(ent2)   # 真实 EntityState 无该属性，须经懒恢复 helper
        agg2 = store2.aggregate(time.time())
        print(f"  aggregate after restore: {len(agg2)} items")
        print()

    _subsection("7 — remaining mass 保留验证（弱回答后）")
    ent3 = _MockEntity(tick=1)
    _seed_memory(ent3, [
        _ep("targeted", "actor", "测试问题", ts=time.time() - 5, tick=2),
    ])
    # weak irrelevant reply
    r_weak = observe_reply(ent3, "啊啊啊不相关", time.time(), "ipc_chat", "ev_weak")
    store3 = ent3._clarification_evidence_store
    mass_after_weak = list(store3._answered_mass.values())[0]
    print(f"  after weak reply: mass={mass_after_weak:.4f}  remaining={1-mass_after_weak:.4f}")
    print(f"  [P1-a] remaining > 0: {1-mass_after_weak > 0}")
    print()

    _subsection("8 — 混淆矩阵（expected -> asked/bound）")
    store_all = entity._clarification_evidence_store
    confusion = {}
    expected_by_event = {"ev_s1_actor": "actor", "ev_s3_new_name": "actor"}
    for ev in store_all._evidence:
        expected = expected_by_event.get(ev.reply_event_id, "unlabeled")
        asked_bound = ev.slot
        key = (expected, asked_bound)
        confusion[key] = confusion.get(key, 0.0) + ev.attributed_mass
    print(f"  {'expected':>12}  {'asked/bound':>12}  {'mass':>8}")
    print(f"  {'-'*12}  {'-'*12}  {'-'*8}")
    for (expected, asked_bound), mass in confusion.items():
        print(f"  {expected:>12}  {asked_bound:>12}  {mass:>8.4f}")
    if not confusion:
        print("  (no targeted evidence yet)")
    print()

    _subsection("9 — _batch_similarity 验证")
    from src.language_system.clarification_learning import _batch_similarity, _char_overlap
    reply = "小王去北京出差了"
    cues = ["小王去北京", "今天天气不错", "小王出差", "小王"]
    sims = _batch_similarity(reply, cues)
    print(f"  reply: {reply}")
    print(f"  cue                          sim")
    print(f"  {'-'*40}  {'-'*5}")
    for cue, s in zip(cues, sims):
        print(f"  {cue:40}  {s:.4f}")
    print()

    _sep()
    print("  INSPECTION COMPLETE")
    _sep()


if __name__ == "__main__":
    main()
