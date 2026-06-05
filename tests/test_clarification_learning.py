# -*- coding: utf-8 -*-
"""
验证澄清归属学习（clarification_learning.py）observe-reply v2 —— 身份 / 相似度 / 归属基础

（容器/持久化/序列化在 test_clarification_attribution.py，拆分守 ≤400 行）
覆盖：episode_id 稳定抗碰撞、char_overlap、_batch_similarity 回退、familiarity 仅审计(P1-c)、
归属 mass/no_match(P1-a/P1-b)、targeted 高相关、新词不压低(P1-c)、generic 竞争(R2-1)、adjacency。
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))          # 供 import _clarif_helpers
sys.path.insert(0, str(Path(__file__).parent.parent))

from _clarif_helpers import _MockEntity, _ep, _seed_memory  # noqa: E402

from src.language_system.clarification_learning import (   # noqa: E402
    observe_reply, episode_id, episode_id_from_dict,
    _batch_similarity, _compute_familiarity, _char_overlap,
)


# ============================================================================
# 1 — episode_id 稳定且抗碰撞
# ============================================================================

def test_episode_id_deterministic():
    ts = 1000.0
    ep1 = _ep("targeted", "actor", "hello world", ts=ts, tick=5)
    ep2 = _ep("targeted", "actor", "hello world", ts=ts, tick=5)
    ep3 = _ep("targeted", "actor", "hello world different", ts=ts, tick=5)
    assert episode_id(ep1) == episode_id(ep2)
    assert episode_id(ep1) != episode_id(ep3)


def test_episode_id_from_dict():
    ts = 1000.0
    ep = _ep("targeted", "patient", "some text", ts=ts, tick=10)
    rec = ep.to_dict()
    rec["_eid"] = episode_id(ep)
    eid_back = episode_id_from_dict(rec)
    assert eid_back == episode_id(ep)


def test_episode_id_sub_ms_no_collision():
    # 完整 timestamp（去 round(...,3)）：相差 <1ms 也不碰撞（GPT P2）。
    ep1 = _ep("targeted", "actor", "同样的话", ts=1000.0000001, tick=5)
    ep2 = _ep("targeted", "actor", "同样的话", ts=1000.0000002, tick=5)
    assert episode_id(ep1) != episode_id(ep2)


# ============================================================================
# 2 — char_overlap 回退
# ============================================================================

def test_char_overlap_basic():
    assert _char_overlap("你好世界", "你好") > 0
    assert _char_overlap("你好世界", "再见") < _char_overlap("你好世界", "你好")
    assert _char_overlap("", "你好") == 0.0
    assert _char_overlap("你好", "") == 0.0


# ============================================================================
# 3 — _batch_similarity 回退（模型不可用时）
# ============================================================================

def test_batch_similarity_fallback():
    reply = "小王昨天去北京出差了"
    cues = ["小王去北京", "今天天气不错", "小王出差"]
    sims = _batch_similarity(reply, cues)
    assert len(sims) == 3
    assert sims[0] > sims[1]
    assert sims[2] > sims[1]


# ============================================================================
# 4 — familiarity 仅审计（P1-c）
# ============================================================================

def test_familiarity_audit():
    fam_new = _compute_familiarity("小王昨天去北京", "今天天气不错", "你说的是什么")
    fam_repeat = _compute_familiarity("小王昨天去北京", "小王昨天去北京", "你说的是什么")
    assert fam_new < 0.5
    assert fam_repeat > 0.5


# ============================================================================
# 5 — P1-a：无关回答只消耗极少 answered_mass
# ============================================================================

def test_irrelevant_consumes_minimal_mass():
    entity = _MockEntity(tick=1)
    ts = 1000.0
    _seed_memory(entity, [_ep("targeted", "actor", "机械设计原理很重要", ts=ts - 10, tick=2)])

    observe_reply(entity, "今天天气真不错", now_ts=ts, source="ipc_chat", reply_event_id="ev1")
    store = entity._clarification_evidence_store
    eid = list(store._answered_mass.keys())[0]
    mass1 = store._answered_mass[eid]

    observe_reply(entity, "晚饭吃什么好", now_ts=ts + 1, source="ipc_chat", reply_event_id="ev2")
    mass2 = store._answered_mass[eid]

    assert mass1 > 0.0
    assert mass2 > mass1
    assert mass2 < 0.8   # P1-a：两次无关 mass 不烧满，真回答仍有机会


# ============================================================================
# 6 — P1-b：完全无关 → no_match_mass 占主导
# ============================================================================

def test_no_match_dominates_irrelevant():
    entity = _MockEntity(tick=1)
    ts = 1000.0
    _seed_memory(entity, [_ep("targeted", "actor", "你好", ts=ts - 10, tick=2)])

    result = observe_reply(entity, "今天天气真不错啊啊啊", now_ts=ts,
                           source="ipc_chat", reply_event_id="ev_nm")
    assert result["no_match_mass"] > 0.8
    assert result["total_mass_assigned"] < 0.2


# ============================================================================
# 7 — targeted 归属：similar content → high mass
# ============================================================================

def test_targeted_high_relevance():
    entity = _MockEntity(tick=1)
    ts = 1000.0
    _seed_memory(entity, [_ep("targeted", "patient", "小王去北京出差", ts=ts - 5, tick=2)])

    result = observe_reply(entity, "小王", now_ts=ts, source="ipc_chat", reply_event_id="ev_rel")
    assert result["no_match"] is False
    attrs = [c["attributed_mass"] for c in result["candidates"]]
    assert max(attrs) > 0.5


# ============================================================================
# 8 — P1-c：低熟悉度新词不被压低（familiarity 不进乘数）
# ============================================================================

def test_novel_word_not_penalized():
    entity = _MockEntity(tick=1)
    ts = 1000.0
    _seed_memory(entity, [_ep("targeted", "actor", "有人做了一件事", ts=ts - 5, tick=2)])

    result = observe_reply(entity, "小王做的那件事", now_ts=ts,
                           source="ipc_chat", reply_event_id="ev_nov")
    attrs = [c["attributed_mass"] for c in result["candidates"]]
    assert max(attrs) > 0.3


# ============================================================================
# 9 — R2-1：generic 最新时归属给它，不被旧 targeted 抢走
# ============================================================================

def test_generic_not_stolen_by_old_targeted():
    entity = _MockEntity(tick=1)
    ts = 1000.0
    _seed_memory(entity, [
        _ep("targeted", "actor", "旧问题", ts=ts - 200, tick=5),
        _ep("generic", None, "新问题通用", ts=ts - 1, tick=6),
    ])

    observe_reply(entity, "新问题的答案", now_ts=ts, source="ipc_chat", reply_event_id="ev_gen")
    store = entity._clarification_evidence_store
    assert len(store._generic_obs) >= 1
    assert store._generic_obs[-1].attributed_mass > 0.0
    assert len(store._answered_mass) >= 1


# ============================================================================
# 10 — R2-adjacency：倒序序号驱动 adjacency
# ============================================================================

def test_adjacency_decay():
    entity = _MockEntity(tick=1)
    ts = 1000.0
    _seed_memory(entity, [
        _ep("targeted", "actor", "最近的事", ts=ts - 2, tick=3),
        _ep("targeted", "actor", "较新的事", ts=ts - 100, tick=2),
        _ep("targeted", "actor", "最旧的事", ts=ts - 200, tick=1),
    ])

    result = observe_reply(entity, "测试", now_ts=ts, source="ipc_chat", reply_event_id="ev_adj")
    adj = [c["adjacency"] for c in result["candidates"]]
    assert adj[0] >= adj[1] >= adj[2]


# ============================================================================
# 11 — P1-a：一条回复对所有 targeted 候选都落证据（旧 bug 只落第一个）
# ============================================================================

def test_p1a_all_candidates_get_evidence():
    entity = _MockEntity(tick=1)
    ts = 1000.0
    _seed_memory(entity, [
        _ep("targeted", "actor", "光合作用把二氧化碳变成糖", ts=ts - 3, tick=3),
        _ep("targeted", "patient", "线粒体是细胞的能量工厂", ts=ts - 5, tick=2),
    ])
    observe_reply(entity, "是植物的叶绿体", now_ts=ts, source="ipc_chat", reply_event_id="ev_p1a")
    store = entity._clarification_evidence_store
    # 两个 targeted 候选都应有证据（旧 bug：mark_processed 在 append 内 → 只落第一条）
    assert len(store._evidence) == 2
