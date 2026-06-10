"""
Clarification Learning — observe-reply v2

承接 clarification_memory v1 record-only。v2 新增"她问出的澄清被回答时"：
    1. 归属：按 remaining × recency × relevance × adjacency 连续分配 attributed_mass
    2. 弃权候选：no_match_mass 吸收完全无关回答（_NO_MATCH_PRIOR 软竞争）
    3. 证据账本：SlotEvidence（targeted）+ GenericObservation（generic），见 clarification_evidence
    4. 幂等：同一 reply_event_id 不重复结算

v2 observation-only：不把证据喂回 proposition_frame，不改驱动力/WM/unresolved。

存储层（SlotEvidence / GenericObservation / SlotEvidenceStore）在 clarification_evidence.py，
此处 re-export 以保持对外 import 路径不变。"什么算澄清"的知识在 uncertainty_expression.clarification_meta()。
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Dict, List

# 存储层（拆分自本模块，守 ≤400 行）；re-export 保持 `from clarification_learning import ...` 不变。
from .clarification_evidence import (
    SlotEvidence,
    GenericObservation,
    SlotEvidenceStore,
    _EVIDENCE_MAXLEN,
    _PROCESSED_EVENT_MAXLEN,
    _ATTRIB_TAU,
)

# ============================================================================
# 归属层常量
# ============================================================================

# 归属候选上限（Codex P2-d：防止对 200 条 history 逐条 BGE）
_ATTRIB_CANDIDATE_MAXLEN: int = 20
# adjacency 时间常数（Codex R2-adjacency：candidate_distance 倒序序号）
_ADJACENCY_TAU: float = 3.0
# 语义相关度锐化幂次：BGE 对无关中文句也给 0.3-0.5 高基线（实测"你好"vs"今天天气"=0.47），
# 直接用会把无关误判成匹配。幂次压低中段、拉开"真相关(≥0.59)"与"基线噪声(≤0.47)"。
# 实测探针校准：P=4 → 0.47→0.05、0.59→0.12、0.73→0.29。偏大值先跑再调，待 Owner 追认。
_REL_POWER: float = 4.0
# no_match 弃权先验（Codex P1-b）：与锐化后相关度同量级，使无关回答（锐化≈0.05）落到 no_match、
# 真相关（≥0.12）胜出。实测校准 prior∈(0.20,0.29) 同时满足"你好"判无关 + 真相关拿 mass。
_NO_MATCH_PRIOR: float = 0.24
# 打分器版本：随证据落盘，供 v3 分桶（保守种子值，非 v3 参数）。改 _REL_POWER/_NO_MATCH_PRIOR 时同步改。
_SCORER_VERSION: str = "v2.1-relpow4-prior24"


# ============================================================================
# 相似度（复用 expression_feedback 模式：BGE 优先，回退 char overlap）
# ============================================================================

def _similarity(a: str, b: str) -> float:
    """单对相似度。优先 BGE，回退汉字 Jaccard。"""
    if not a or not b:
        return 0.0
    try:
        from .bge_analyzer import _get_bge_model
        import numpy as np
        model = _get_bge_model()
        embs = model.encode([a, b], normalize_embeddings=True)
        return max(0.0, float(np.dot(embs[0], embs[1])))
    except Exception:
        return _char_overlap(a, b)


def _char_overlap(a: str, b: str) -> float:
    """汉字 Jaccard 相似度。"""
    if not a or not b:
        return 0.0
    sa, sb = set(a), set(b)
    return len(sa & sb) / max(1, len(sa | sb))


def _batch_similarity(reply: str, cue_inputs: List[str]) -> List[float]:
    """
    批量相似度：一次编码 [reply, *cues]，逐对余弦。
    模型不可用时逐项回退 _char_overlap，不新增模型实例。
    返回与 cue_inputs 等长的相似度列表。
    """
    if not reply or not cue_inputs:
        return [0.0] * len(cue_inputs)

    texts = [reply] + list(cue_inputs)
    try:
        from .bge_analyzer import _get_bge_model
        import numpy as np
        model = _get_bge_model()
        embs = model.encode(texts, normalize_embeddings=True)
        reply_emb = embs[0]
        return [max(0.0, float(np.dot(reply_emb, e))) for e in embs[1:]]
    except Exception:
        return [_char_overlap(reply, cue) for cue in cue_inputs]


def _compute_familiarity(reply: str, original_input: str, question_text: str) -> float:
    """
    回答与澄清上下文的熟悉度（审计字段，Codex P1-c：不进核心归属乘数）。
    reply 是否已在 original_input 或 question 里出现过（用户重复自己说的内容）。
    max char-overlap between reply and [original_input, question_text]。
    """
    return max(_char_overlap(reply, original_input), _char_overlap(reply, question_text))


# ============================================================================
# episode_id — 稳定身份（Salted SHA-256）
# ============================================================================

def episode_id(ep) -> str:
    """
    稳定 identity = SHA-256(canonical JSON of ts+tick+input+question+kind+slot)。
    Salt 防止 length-extension 攻击。
    """
    canon = json.dumps([
        repr(float(ep.timestamp)),
        int(ep.tick),
        str(ep.original_input),
        str(ep.question_text),
        str(ep.clarification_kind),
        str(ep.clarification_slot or "none"),
    ], sort_keys=True, ensure_ascii=False)
    salt = b"clarification_episode_v1"
    return hashlib.sha256(salt + canon.encode("utf-8")).hexdigest()


def episode_id_from_dict(rec: Dict[str, Any]) -> str:
    """从 recent_records dict 反推 episode_id（recent_records 返回的 dict 无 episode_id 字段）。"""
    canon = json.dumps([
        repr(float(rec["timestamp"])),
        int(rec["tick"]),
        str(rec.get("original_input", "")),
        str(rec.get("question_text", "")),
        str(rec.get("clarification_kind", "")),
        str(rec.get("clarification_slot") or "none"),
    ], sort_keys=True, ensure_ascii=False)
    salt = b"clarification_episode_v1"
    return hashlib.sha256(salt + canon.encode("utf-8")).hexdigest()


# ============================================================================
# 懒恢复 helper（供 daemon/tick_engine 调用）
# ============================================================================

def _get_evidence_store(entity) -> SlotEvidenceStore:
    """
    返回 entity 的 SlotEvidenceStore 运行时实例。
    运行时对象存在 → 直接返回；否则从 entity._clarification_hints_data 懒恢复（空 dict 也安全）。
    """
    existing = getattr(entity, "_clarification_evidence_store", None)
    if existing is not None:
        return existing
    store = SlotEvidenceStore.from_dict(getattr(entity, "_clarification_hints_data", {}) or {})
    entity._clarification_evidence_store = store
    return store


def _sync_mirror(entity, store, memory) -> None:
    """结算后同步：store.to_dict() → entity._clarification_hints_data（answered_mass 已 prune）。"""
    entity._clarification_hints_data = store.to_dict()


# ============================================================================
# observe_reply — 唯一公共入口
# ============================================================================

def observe_reply(
    entity,
    reply_text: str,
    now_ts: float,
    source: str,
    reply_event_id: str,
) -> Dict[str, Any]:
    """
    结算一条用户回复对她之前澄清的归属。

    Observation-only v2：
        - source 仅 ipc_chat / external 可结算，sibling 忽略
        - 幂等：同一 reply_event_id 不重复结算
        - 不碰驱动力 / WM / unresolved / proposition_frame
        - 返回结算摘要供 trace / inspection

    候选选取：v1 recent_records 中仍有 remaining mass 的 targeted + generic（generic 也竞争，
    Codex R2-1），按 timestamp 倒序取最近 _ATTRIB_CANDIDATE_MAXLEN，批量 BGE。
    原始分 = remaining × recency × relevance^_REL_POWER × adjacency，与 no_match 软弃权归一化。
    targeted 生成 SlotEvidence；generic 只更新 answered_mass + 记 GenericObservation。
    """
    # Guard 1: source 过滤（Codex P2-b / R2-external）
    if source not in ("ipc_chat", "external"):
        return {"skipped": True, "reason": "sibling_ignored", "event_id": reply_event_id}

    # Guard 2: reply_text 非空
    if not reply_text or not reply_text.strip():
        return {"skipped": True, "reason": "empty_reply", "event_id": reply_event_id}

    store = _get_evidence_store(entity)

    # Guard 3: 幂等（Codex R2-idem）
    if reply_event_id in store._processed:
        return {"skipped": True, "reason": "duplicate_event", "event_id": reply_event_id}

    # Guard 4: 需要 v1 clarification memory
    from .clarification_memory import _get_memory
    memory = _get_memory(entity)

    # 候选 = 按 timestamp 倒序取最近 _ATTRIB_CANDIDATE_MAXLEN（仅限容，不按 remaining 过滤——
    # 已答尽的 episode remaining=0 → raw=0 自然不得 mass，但保留它使 adjacency 序号稳定，
    # 不随 answered_mass 状态跳变，GPT P2）。
    records = memory.recent_records(now_ts)
    candidates: List[Dict[str, Any]] = []
    for rec in sorted(records, key=lambda x: x["timestamp"], reverse=True):
        if len(candidates) >= _ATTRIB_CANDIDATE_MAXLEN:
            break
        rec["_eid"] = rec.get("_eid") or episode_id_from_dict(rec)
        candidates.append(rec)

    # Guard 5: 无候选则记录 no_match 并返回
    if not candidates:
        no_match_mass = 1.0
        generic_obs = GenericObservation(
            episode_id="none", attributed_mass=0.0, no_match_mass=no_match_mass,
            source=source, reply_event_id=reply_event_id,
            tick=int(getattr(entity, "tick", 0)), timestamp=now_ts,
        )
        store.append_generic(generic_obs)
        store.mark_processed(reply_event_id)
        _sync_mirror(entity, store, memory)
        return {"skipped": False, "event_id": reply_event_id, "no_match": True,
                "candidates": [], "no_match_mass": no_match_mass,
                "generic_obs": generic_obs.to_dict()}

    # 批量计算语义相似度（一次编码 reply + cues，Codex R2-batch）
    cue_inputs = [rec["original_input"] for rec in candidates]
    sims = _batch_similarity(reply_text, cue_inputs)

    # 各候选原始分（relevance 锐化压低 BGE 中文基线）
    raw_scores: List[float] = []
    for i, rec in enumerate(candidates):
        eid = rec["_eid"]
        age = max(0.0, now_ts - rec["timestamp"])
        recency = math.exp(-age / _ATTRIB_TAU)
        adjacency = math.exp(-i / _ADJACENCY_TAU)   # 倒序序号 newest=0（Codex R2-adjacency）
        rel_raw = sims[i]
        relevance = rel_raw ** _REL_POWER
        remaining = 1.0 - store._answered_mass.get(eid, 0.0)
        raw = remaining * recency * relevance * adjacency
        rec["_raw_score"] = raw
        rec["_semantic_relevance"] = rel_raw   # 审计存原始 BGE（未锐化）
        rec["_recency"] = recency
        rec["_adjacency"] = adjacency
        rec["_remaining"] = remaining
        raw_scores.append(raw)

    # 归一化（含 no_match 软弃权，Codex P1-b）
    total_raw = sum(raw_scores) + _NO_MATCH_PRIOR
    no_match_mass = _NO_MATCH_PRIOR / total_raw
    attribution_results: List[Dict[str, Any]] = []
    for i, rec in enumerate(candidates):
        am = raw_scores[i] / total_raw
        rec["_attributed_mass"] = am
        rec["_no_match_mass"] = no_match_mass
        attribution_results.append({
            "episode_id": rec["_eid"], "slot": rec.get("clarification_slot"),
            "kind": rec.get("clarification_kind"), "attributed_mass": am,
            "no_match_mass": no_match_mass, "semantic_relevance": rec["_semantic_relevance"],
            "recency": rec["_recency"], "adjacency": rec["_adjacency"],
            "remaining_before": rec["_remaining"], "cue_input": rec["original_input"],
        })

    # 结算：更新 mass + 追加 evidence / generic_observation
    tick = int(getattr(entity, "tick", 0))
    for rec in candidates:
        eid = rec["_eid"]
        am = rec["_attributed_mass"]
        nmm = rec["_no_match_mass"]
        store.update_mass(eid, am)
        fam = _compute_familiarity(reply_text, rec["original_input"], rec.get("question_text", ""))
        if rec.get("clarification_kind") == "targeted" and rec.get("clarification_slot"):
            store.append_evidence(SlotEvidence(
                episode_id=eid, slot=str(rec["clarification_slot"]), cue_input=rec["original_input"],
                answer_text=reply_text, attributed_mass=am, no_match_mass=nmm,
                semantic_relevance=rec["_semantic_relevance"], recency=rec["_recency"],
                adjacency=rec["_adjacency"], answer_familiarity=fam, source=source,
                reply_event_id=reply_event_id, tick=tick, timestamp=now_ts,
                scorer_version=_SCORER_VERSION,
            ))
        else:
            store.append_generic(GenericObservation(
                episode_id=eid, attributed_mass=am, no_match_mass=nmm, source=source,
                reply_event_id=reply_event_id, tick=tick, timestamp=now_ts,
                scorer_version=_SCORER_VERSION,
            ))

    # 整轮候选全部落盘后，标记本 reply_event_id 已处理（一次，P1-a：不在 append 里 mark）
    store.mark_processed(reply_event_id)
    # answered_mass 只保留当前 v1 history **全部** episode（P1-b：不是仅本轮候选——
    # 否则超出 _ATTRIB_CANDIDATE_MAXLEN 的有效旧澄清进度会被误删、重获满额机会）。
    store.prune_mass({episode_id_from_dict(rec) for rec in records})
    _sync_mirror(entity, store, memory)

    return {
        "skipped": False, "event_id": reply_event_id, "source": source,
        "reply_text": reply_text[:30], "no_match": False,
        "candidates": attribution_results,
        "total_mass_assigned": sum(r["attributed_mass"] for r in attribution_results),
        "no_match_mass": no_match_mass,
    }
