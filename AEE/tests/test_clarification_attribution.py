# -*- coding: utf-8 -*-
"""
验证澄清归属学习 v2 —— 幂等 / source / 容器 / 持久化 / observation-only / mass 清理

（身份/相似度/归属基础在 test_clarification_learning.py，拆分守 ≤400 行）
覆盖：幂等、sibling 忽略、empty 忽略、external SHA-256、aggregate 只读(R2-scope)、
mass 清理(P2-idem，含超候选上限不误删 P1-b)、不可变追加、持久化 roundtrip、
EntityState 落盘、observation-only、_PROCESSED_EVENT_MAXLEN、序列化。
"""

import hashlib
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))          # 供 import _clarif_helpers
sys.path.insert(0, str(Path(__file__).parent.parent))

from _clarif_helpers import _MockEntity, _ep, _seed_memory  # noqa: E402

from AEE.src.language_system.clarification_learning import (   # noqa: E402
    SlotEvidence, GenericObservation, SlotEvidenceStore,
    observe_reply, episode_id, _get_evidence_store,
    _ATTRIB_CANDIDATE_MAXLEN, _PROCESSED_EVENT_MAXLEN,
)
from AEE.src.language_system.clarification_memory import _get_memory  # noqa: E402


# ============================================================================
# 12 — 幂等：同 event_id 不重复
# ============================================================================

def test_idempotency():
    entity = _MockEntity(tick=1)
    ts = 1000.0
    _seed_memory(entity, [_ep("targeted", "actor", "问题", ts=ts - 5, tick=2)])

    observe_reply(entity, "回答", now_ts=ts, source="ipc_chat", reply_event_id="ev_same")
    result2 = observe_reply(entity, "回答2", now_ts=ts + 1, source="ipc_chat",
                            reply_event_id="ev_same")  # same id

    store = entity._clarification_evidence_store
    assert result2["skipped"] is True
    assert result2["reason"] == "duplicate_event"
    assert len(store._evidence) == 1


# ============================================================================
# 13 — sibling source 忽略
# ============================================================================

def test_sibling_ignored():
    entity = _MockEntity(tick=1)
    ts = 1000.0
    _seed_memory(entity, [_ep("targeted", "actor", "问题", ts=ts - 5, tick=2)])

    result = observe_reply(entity, "回答", now_ts=ts, source="sibling", reply_event_id="ev_sib")
    assert result["skipped"] is True
    assert result["reason"] == "sibling_ignored"
    store = _get_evidence_store(entity)   # 懒取空容器验证真实结果
    assert len(store._evidence) == 0


# ============================================================================
# 14 — empty reply 忽略
# ============================================================================

def test_empty_reply_ignored():
    entity = _MockEntity(tick=1)
    ts = 1000.0
    _seed_memory(entity, [_ep("targeted", "actor", "问题", ts=ts - 5, tick=2)])

    result = observe_reply(entity, "", now_ts=ts, source="ipc_chat", reply_event_id="ev_empty")
    assert result["skipped"] is True
    assert result["reason"] == "empty_reply"


# ============================================================================
# 15 — external 使用 SHA-256 event_id
# ============================================================================

def test_external_sha256_event_id():
    entity = _MockEntity(tick=1)
    ts = 1000.0
    _seed_memory(entity, [_ep("targeted", "actor", "问题", ts=ts - 5, tick=2)])

    reply = "外部回答"
    expected_id = hashlib.sha256(("external" + str(ts) + reply).encode("utf-8")).hexdigest()
    result = observe_reply(entity, reply, now_ts=ts, source="external", reply_event_id=expected_id)
    assert result["skipped"] is False
    assert result["source"] == "external"


# ============================================================================
# 16 — R2-scope：aggregate 只读
# ============================================================================

def test_aggregate_readonly():
    entity = _MockEntity(tick=1)
    ts = 1000.0
    _seed_memory(entity, [
        _ep("targeted", "actor", "问题1", ts=ts - 5, tick=2),
        _ep("targeted", "patient", "问题2", ts=ts - 10, tick=1),
    ])

    observe_reply(entity, "回答1", now_ts=ts, source="ipc_chat", reply_event_id="ev_agg1")
    observe_reply(entity, "回答2", now_ts=ts + 1, source="ipc_chat", reply_event_id="ev_agg2")

    store = entity._clarification_evidence_store
    agg = store.aggregate(ts + 2)
    # P1-a：每条回复对 2 个 targeted 候选各落一条证据 → 2 回复 × 2 候选 = 4
    assert len(agg) == 4
    for item in agg:
        assert "effective_strength" in item
        assert "age_seconds" in item
        assert 0.0 <= item["effective_strength"] <= 1.0


# ============================================================================
# 17 — mass 清理（P2-idem）：已驱逐 episode 不残留 mass
# ============================================================================

def test_mass_prune_on_history_eviction():
    entity = _MockEntity(tick=1)
    ts = 1000.0
    eps = [_ep("targeted", "actor", f"问题{i}", ts=ts - i * 5, tick=i) for i in range(1, 4)]
    _seed_memory(entity, eps)

    observe_reply(entity, "问题1的答案", now_ts=ts, source="ipc_chat", reply_event_id="ev_prune")
    mem = _get_memory(entity)
    mem._history.pop()  # 驱逐最旧
    entity._clarification_memory_data = mem.to_dict()

    store = entity._clarification_evidence_store
    valid_ids = {episode_id(e) for e in mem._history}
    store.prune_mass(valid_ids)
    for k in list(store._answered_mass.keys()):
        assert k in valid_ids


# ============================================================================
# 18 — P1-b：prune 保留当前 v1 history 全部（超候选上限的旧澄清进度不被误删）
# ============================================================================

def test_p1b_prune_keeps_beyond_cap_history():
    entity = _MockEntity(tick=1)
    ts = 1000.0
    n = _ATTRIB_CANDIDATE_MAXLEN + 5
    eps = [_ep("targeted", "actor", f"问题{i}", ts=ts - i, tick=i) for i in range(1, n + 1)]
    _seed_memory(entity, eps)

    store = _get_evidence_store(entity)
    oldest = eps[-1]               # ts 最小 → 倒序排最后 → 超出候选上限
    oldest_eid = episode_id(oldest)
    store._answered_mass[oldest_eid] = 0.5
    entity._clarification_hints_data = store.to_dict()

    observe_reply(entity, "某个回答", now_ts=ts + 1, source="ipc_chat", reply_event_id="ev_p1b")

    # oldest 仍在 v1 history → prune 后其 answered_mass 不应被删（修前 prune 仅本轮候选 → 误删）
    assert oldest_eid in entity._clarification_evidence_store._answered_mass


# ============================================================================
# 19 — evidence 不可变追加
# ============================================================================

def test_evidence_immutable_append():
    entity = _MockEntity(tick=1)
    ts = 1000.0
    _seed_memory(entity, [_ep("targeted", "actor", "问题", ts=ts - 5, tick=2)])

    observe_reply(entity, "回答", now_ts=ts, source="ipc_chat", reply_event_id="ev_imm")
    store = entity._clarification_evidence_store
    assert len(store._evidence) == 1
    assert store._evidence[0].attributed_mass >= 0.0


# ============================================================================
# 20 — to_dict / from_dict roundtrip
# ============================================================================

def test_store_persist_roundtrip():
    entity = _MockEntity(tick=1)
    ts = 1000.0
    _seed_memory(entity, [_ep("targeted", "actor", "问题", ts=ts - 5, tick=2)])
    observe_reply(entity, "回答", now_ts=ts, source="ipc_chat", reply_event_id="ev_rt")

    store = entity._clarification_evidence_store
    restored = SlotEvidenceStore.from_dict(store.to_dict())
    assert len(restored._evidence) == len(store._evidence)
    assert len(restored._generic_obs) == len(store._generic_obs)
    assert restored._answered_mass == store._answered_mass
    assert list(restored._processed) == list(store._processed)


# ============================================================================
# 21 — EntityState persist/load roundtrip（含 hints_data）
# ============================================================================

def test_entity_state_persist_hints():
    from AEE.src.entity_state import EntityState

    ent = EntityState()
    ent.tick = 77
    ts = time.time()
    _seed_memory(ent, [_ep("targeted", "actor", "问题", ts=ts - 5, tick=2)])
    observe_reply(ent, "回答", now_ts=ts, source="ipc_chat", reply_event_id="ev_ent")

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "core.json"
        ent.persist_to_file(path)
        ent2 = EntityState()
        assert ent2.load_from_file(path)
        assert ent2.tick == 77
        hints = ent2._clarification_hints_data
        assert "evidence" in hints and "answered_mass" in hints and "processed_event_ids" in hints


# ============================================================================
# 22 — observe_reply 无副作用（observation-only）
# ============================================================================

def test_observation_only_no_side_effects():
    entity = _MockEntity(tick=1, loneliness=0.5, unresolved=0.3, info_gap=0.2)
    ts = 1000.0
    _seed_memory(entity, [_ep("targeted", "actor", "问题", ts=ts - 5, tick=2)])
    pre = (entity.loneliness, entity.unresolved, entity.info_gap)

    observe_reply(entity, "回答", now_ts=ts, source="ipc_chat", reply_event_id="ev_obs")
    assert (entity.loneliness, entity.unresolved, entity.info_gap) == pre


# ============================================================================
# 23 — _PROCESSED_EVENT_MAXLEN 限容
# ============================================================================

def test_processed_event_maxlen():
    entity = _MockEntity(tick=1)
    ts = 1000.0
    _seed_memory(entity, [_ep("targeted", "actor", "问题", ts=ts - 5, tick=2)])

    for i in range(_PROCESSED_EVENT_MAXLEN + 50):
        try:
            observe_reply(entity, f"回答{i}", now_ts=ts + i, source="ipc_chat",
                          reply_event_id=f"ev_many_{i}")
        except Exception:
            pass

    store = entity._clarification_evidence_store
    assert len(store._processed) <= _PROCESSED_EVENT_MAXLEN


# ============================================================================
# 24 — SlotEvidence / GenericObservation to_dict / from_dict（含 scorer_version 默认）
# ============================================================================

def test_slot_evidence_serialization():
    ev = SlotEvidence(
        episode_id="test_eid", slot="actor", cue_input="input", answer_text="answer",
        attributed_mass=0.7, no_match_mass=0.1, semantic_relevance=0.8, recency=0.9,
        adjacency=0.95, answer_familiarity=0.3, source="ipc_chat", reply_event_id="ev1",
        tick=1, timestamp=1000.0,
    )
    ev2 = SlotEvidence.from_dict(ev.to_dict())
    assert ev2.episode_id == ev.episode_id
    assert ev2.attributed_mass == ev.attributed_mass
    # 旧记录（无 scorer_version）反序列化仍安全（默认值）
    legacy = {k: v for k, v in ev.to_dict().items() if k != "scorer_version"}
    assert SlotEvidence.from_dict(legacy).scorer_version == "unknown"


def test_generic_observation_serialization():
    obs = GenericObservation(
        episode_id="test_eid", attributed_mass=0.5, no_match_mass=0.2,
        source="external", reply_event_id="ev2", tick=1, timestamp=1000.0,
    )
    obs2 = GenericObservation.from_dict(obs.to_dict())
    assert obs2.episode_id == obs.episode_id
    assert obs2.attributed_mass == obs.attributed_mass
