"""
Clarification Evidence — observe-reply v2 的存储层

承载澄清归属的证据账本（从 clarification_learning 拆出，守 ≤400 行/文件）：
    SlotEvidence          — 单条 targeted 槽位归属证据（frozen，追加不改）
    GenericObservation    — generic 澄清归属记录（frozen，追加）
    SlotEvidenceStore     — 容器：evidence + answered_mass + generic_obs + processed_event_ids

归属/竞争逻辑、observe_reply 入口在 clarification_learning.py。
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, asdict, fields
from typing import Any, Dict, List, Optional, Set

# ============================================================================
# 存储层常量
# ============================================================================

# evidence 容量（deque maxlen，待 Owner 追认后调）
_EVIDENCE_MAXLEN: int = 200
# 已处理事件 ID 队列上限（Codex R2-idem）
_PROCESSED_EVENT_MAXLEN: int = 500
# recency 时间常数（来源：沿用 v1 8 tick × 30s/tick = 240s）；aggregate recency 用它
_ATTRIB_TAU: float = 240.0


# ============================================================================
# SlotEvidence — 单条槽位证据（frozen，不可变）
# ============================================================================

@dataclass(frozen=True)
class SlotEvidence:
    """一条回答对某条 targeted 澄清的槽位归属证据（frozen，追加后不改）。"""
    episode_id: str           # ClarificationEpisode 身份
    slot: str                # "actor" | "patient" | "predicate"
    cue_input: str           # 她问出这条澄清时的 original_input
    answer_text: str         # 用户的回答文本
    attributed_mass: float    # [0,1] 连续归属质量
    no_match_mass: float     # [0,1] 当次 no_match 软弃权质量
    semantic_relevance: float   # [0,1] 原始语义相似度（审计，未锐化）
    recency: float           # [0,1] 候选时 recency
    adjacency: float         # [0,1] 候选时 adjacency
    answer_familiarity: float   # [0,1] 回答与澄清上下文熟悉度（审计）
    source: str              # "ipc_chat" | "external"
    reply_event_id: str      # 幂等依据
    tick: int                # 归属结算时的 tick
    timestamp: float         # 归属结算时的 wall-clock time
    scorer_version: str = "unknown"   # 打分器版本（_REL_POWER/_NO_MATCH_PRIOR 等，供 v3 分桶）

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> SlotEvidence:
        valid = {f.name for f in fields(SlotEvidence)}
        return SlotEvidence(**{k: v for k, v in d.items() if k in valid})


# ============================================================================
# GenericObservation — generic 澄清归属记录（frozen，追加）
# ============================================================================

@dataclass(frozen=True)
class GenericObservation:
    """generic 澄清的归属记录（generic 不生成 SlotEvidence，仅统计）。"""
    episode_id: str
    attributed_mass: float
    no_match_mass: float
    source: str
    reply_event_id: str
    tick: int
    timestamp: float
    scorer_version: str = "unknown"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> GenericObservation:
        valid = {f.name for f in fields(GenericObservation)}
        return GenericObservation(**{k: v for k, v in d.items() if k in valid})


# ============================================================================
# SlotEvidenceStore — 证据容器
# ============================================================================

class SlotEvidenceStore:
    """
    槽位证据容器。运行时瞬态，通过 _clarification_hints_data 持久化。

    持久结构：
        evidence: [SlotEvidence.to_dict()]
        answered_mass: {eid: float}
        generic_observations: [GenericObservation.to_dict()]
        processed_event_ids: [str]  (有序 deque)
    """

    __slots__ = ("_evidence", "_answered_mass", "_generic_obs", "_processed")

    def __init__(
        self,
        evidence: Optional[List[SlotEvidence]] = None,
        answered_mass: Optional[Dict[str, float]] = None,
        generic_observations: Optional[List[GenericObservation]] = None,
        processed_event_ids: Optional[List[str]] = None,
    ) -> None:
        self._evidence = deque(evidence or [], maxlen=_EVIDENCE_MAXLEN)
        self._answered_mass: Dict[str, float] = dict(answered_mass or {})
        self._generic_obs = deque(generic_observations or [], maxlen=_EVIDENCE_MAXLEN)
        self._processed: deque = deque(processed_event_ids or [], maxlen=_PROCESSED_EVENT_MAXLEN)

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------

    def append_evidence(self, ev: SlotEvidence) -> None:
        """追加一条 evidence。幂等由 observe_reply 入口 + mark_processed 统一负责，
        此处不再 mark——否则一轮多候选只会落第一条（P1 bug：mass 更新但证据丢失）。"""
        self._evidence.append(ev)

    def append_generic(self, obs: GenericObservation) -> None:
        """追加一条 generic_observation（不在此 mark_processed，理由同 append_evidence）。"""
        self._generic_obs.append(obs)

    def mark_processed(self, event_id: str) -> None:
        """整轮候选全部落盘后调一次：把 reply_event_id 标为已处理（幂等去重）。"""
        if event_id not in self._processed:
            self._processed.append(event_id)

    def update_mass(self, eid: str, new_attributed: float) -> None:
        """
        追加归属质量：answered_mass[eid] = 1 - (1-old) × (1-new_attributed)。
        answered_mass 始终 ∈ [0,1]。
        """
        old = self._answered_mass.get(eid, 0.0)
        self._answered_mass[eid] = 1.0 - (1.0 - old) * (1.0 - new_attributed)

    def prune_mass(self, valid_eids: Set[str]) -> None:
        """
        清理 answered_mass：只保留 valid_eids 中的 episode_id（Codex R2-idem）。
        写回前调用，保证重启后不误归属已驱逐的 episode。
        """
        self._answered_mass = {k: v for k, v in self._answered_mass.items() if k in valid_eids}

    # ------------------------------------------------------------------
    # 查询（只读）
    # ------------------------------------------------------------------

    def aggregate(self, now_ts: float) -> List[Dict[str, Any]]:
        """
        按 effective_strength = attributed_mass × recency 排序的只读视图（Codex R2-scope）。
        仅 targeted 澄清参与 aggregate；generic_observations 不在此视图内。
        仅输出，不修改原始证据。
        """
        items: List[Dict[str, Any]] = []
        for ev in self._evidence:
            age = max(0.0, now_ts - ev.timestamp)
            recency = math.exp(-age / _ATTRIB_TAU)
            eff = ev.attributed_mass * recency
            d = ev.to_dict()
            d["effective_strength"] = eff
            d["age_seconds"] = age
            items.append(d)
        return sorted(items, key=lambda x: x["effective_strength"], reverse=True)

    def stats(self) -> Dict[str, Any]:
        """返回统计摘要（供 inspection）。"""
        total = len(self._evidence)
        mass_vals = [ev.attributed_mass for ev in self._evidence]
        rec_vals = [ev.recency for ev in self._evidence]
        rel_vals = [ev.semantic_relevance for ev in self._evidence]
        no_vals = [ev.no_match_mass for ev in self._evidence]
        fam_vals = [ev.answer_familiarity for ev in self._evidence]
        slot_dist: Dict[str, int] = {}
        for ev in self._evidence:
            slot_dist[ev.slot] = slot_dist.get(ev.slot, 0) + 1
        return {
            "total_evidence": total,
            "total_generic_obs": len(self._generic_obs),
            "mass_mean": sum(mass_vals) / max(len(mass_vals), 1),
            "mass_min": min(mass_vals, default=0.0),
            "mass_max": max(mass_vals, default=0.0),
            "recency_mean": sum(rec_vals) / max(len(rec_vals), 1),
            "relevance_mean": sum(rel_vals) / max(len(rel_vals), 1),
            "no_match_mean": sum(no_vals) / max(len(no_vals), 1),
            "familiarity_mean": sum(fam_vals) / max(len(fam_vals), 1),
            "slot_distribution": dict(slot_dist),
        }

    # ------------------------------------------------------------------
    # 序列化
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "evidence": [ev.to_dict() for ev in self._evidence],
            "answered_mass": dict(self._answered_mass),
            "generic_observations": [obs.to_dict() for obs in self._generic_obs],
            "processed_event_ids": list(self._processed),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SlotEvidenceStore:
        if not isinstance(data, dict):
            return cls()
        evidence = [SlotEvidence.from_dict(e) for e in data.get("evidence", [])]
        answered_mass = dict(data.get("answered_mass", {}))
        generic_obs = [GenericObservation.from_dict(o) for o in data.get("generic_observations", [])]
        processed_ids = list(data.get("processed_event_ids", []))
        return cls(evidence, answered_mass, generic_obs, processed_ids)
