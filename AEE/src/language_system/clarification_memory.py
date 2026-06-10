"""
Clarification Memory — 澄清问题记录账本（record-only v1）

仅记录"她真正问出了澄清问题"这件事，不消费、不补槽、不修改驱动力。

"什么算澄清"的知识收敛在 uncertainty_expression.clarification_meta()，
clarification_memory 只负责记录和查询。

v1 约束：
    - 仅 history deque，无独立 pending deque
    - recency 用 timestamp 主基准（停机时间计入），tick 仅审计
    - 运行时对象 / JSON 镜像分离，懒恢复
    - record 后立即同步镜像
"""

from __future__ import annotations

import math
import time
from collections import deque
from copy import deepcopy
from dataclasses import dataclass, asdict, fields
from typing import Any, Deque, Dict, List, Optional

# ============================================================================
# 常量
# ============================================================================

# 历史容量上限（来源：Codex 建议偏大以保留统计样本，待 Owner 追认后调）
_HISTORY_MAXLEN: int = 200

# recency 时间常数（来源：8 tick × 30s/tick，Codex #1 确认）
_RECENCY_TAU_SECONDS: float = 240.0


# ============================================================================
# ClarificationEpisode — 单条澄清记忆
# ============================================================================

@dataclass(frozen=True)
class ClarificationEpisode:
    """一条澄清问题的完整记录。"""
    original_input: str          # 用户原始输入
    proposition_frame: Dict[str, Any]  # 记录时的命题骨架快照
    clarification_kind: str      # "generic" | "targeted"
    clarification_slot: Optional[str]  # None | "actor" | "patient" | "predicate"
    question_text: str           # 她真说出口的那句
    confidence: float            # 记录时的 _understanding_confidence
    tick: int                    # 审计 / 测试用
    timestamp: float             # time.time()，recency 主基准

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> ClarificationEpisode:
        valid_fields = {f.name for f in fields(ClarificationEpisode)}
        return ClarificationEpisode(
            **{k: v for k, v in d.items() if k in valid_fields}
        )


# ============================================================================
# ClarificationMemory — 容器
# ============================================================================

class ClarificationMemory:
    """澄清记忆容器。record-only v1 不维护 pending，仅 history。"""

    __slots__ = ("_history",)

    def __init__(self, history: Optional[List[ClarificationEpisode]] = None) -> None:
        history = history or []
        self._history: Deque[ClarificationEpisode] = deque(history, maxlen=_HISTORY_MAXLEN)

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------

    def record(self, episode: ClarificationEpisode) -> None:
        """追加一条记录到 history。超容量时 deque 自动驱逐最旧条目。"""
        self._history.append(episode)

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def recent_records(self, now_timestamp: float) -> List[Dict[str, Any]]:
        """
        按 recency 派生的只读视图，不修改 history。

        recency = exp(-age / _RECENCY_TAU_SECONDS)
        age     = max(0.0, now_timestamp - episode.timestamp)
        """
        result: List[Dict[str, Any]] = []
        for ep in self._history:
            age = max(0.0, now_timestamp - ep.timestamp)
            recency = math.exp(-age / _RECENCY_TAU_SECONDS)
            d = ep.to_dict()
            d["recency"] = recency
            d["age_seconds"] = age
            result.append(d)
        return result

    def stats(self) -> Dict[str, Any]:
        """
        返回统计摘要：
        - generic / targeted 计数
        - actor / patient / predicate 分布（targeted 部分）
        - slot_confidence / slot_relevance 分布（从 proposition_frame）
        """
        generic_count = 0
        targeted_count = 0
        slot_counts = {"actor": 0, "patient": 0, "predicate": 0}
        all_slot_conf = []
        all_slot_rel = []

        for ep in self._history:
            if ep.clarification_kind == "generic":
                generic_count += 1
            else:
                targeted_count += 1
                slot = ep.clarification_slot
                if slot in slot_counts:
                    slot_counts[slot] += 1

                pf = ep.proposition_frame or {}
                sc = pf.get("slot_confidence", {}).get(slot)
                sr = pf.get("slot_relevance", {}).get(slot)
                if sc is not None:
                    all_slot_conf.append(float(sc))
                if sr is not None:
                    all_slot_rel.append(float(sr))

        def _dist(values: List[float]) -> Dict[str, float]:
            if not values:
                return {"count": 0.0, "mean": 0.0, "min": 0.0, "max": 0.0}
            return {
                "count": float(len(values)),
                "mean": sum(values) / len(values),
                "min": min(values),
                "max": max(values),
            }

        return {
            "generic_count": generic_count,
            "targeted_count": targeted_count,
            "total": generic_count + targeted_count,
            "slot_counts": dict(slot_counts),
            "slot_confidence": _dist(all_slot_conf),
            "slot_relevance": _dist(all_slot_rel),
        }

    # ------------------------------------------------------------------
    # 序列化
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """history 序列化（JSON 镜像）。"""
        return {
            "history": [ep.to_dict() for ep in self._history],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ClarificationMemory:
        """从 JSON 镜像重建。空 dict 安全返回空容器。"""
        raw_history = data.get("history", []) if isinstance(data, dict) else []
        episodes = [ClarificationEpisode.from_dict(e) for e in raw_history]
        return cls(history=episodes)


# ============================================================================
# 懒恢复 helper（供 s06c 调用）
# ============================================================================

def _get_memory(entity) -> ClarificationMemory:
    """
    返回 entity 的 ClarificationMemory 运行时实例。

    - 运行时对象存在 → 直接返回
    - 否则从 entity._clarification_memory_data 懒恢复并挂上
    - entity._clarification_memory_data 为空 dict 时返回空容器（安全）
    """
    existing = getattr(entity, "_clarification_memory", None)
    if existing is not None:
        return existing

    memory = ClarificationMemory.from_dict(
        getattr(entity, "_clarification_memory_data", {}) or {}
    )
    entity._clarification_memory = memory
    return memory


# ============================================================================
# maybe_record_displayed_clarification — 唯一出口
# ============================================================================

def maybe_record_displayed_clarification(
    entity,
    raw_input: str,
    _cx_parse_result: Dict,
    _chosen_text: str,
    _chosen_mode: str,
    _tmpl_idx: int,
    all_templates_snapshot: List[Dict],
) -> None:
    """
    封装全部 guard + 记录逻辑。s06c 只调此函数一次。

    Guard（数据有效性，非行为门控）：
        1. raw_input 非空
        2. _chosen_mode == "anchor_auto"
        3. _tmpl_idx >= 0
        4. 0 <= _tmpl_idx < len(all_templates_snapshot)
        5. clarification_meta(template) 非 None
        6. question_text 非空（_chosen_text 非空）

    命中时：
        - 构造 ClarificationEpisode
        - record
        - 同步 entity._clarification_memory_data
    """
    # Guard 1: raw_input 非空
    if not raw_input or not raw_input.strip():
        return

    # Guard 2: 必须 anchor_auto（澄清才在锚点路径）
    if _chosen_mode != "anchor_auto":
        return

    # Guard 3: compound 负索引不记录
    if _tmpl_idx < 0:
        return

    # Guard 4: 边界
    if _tmpl_idx >= len(all_templates_snapshot):
        return

    template = all_templates_snapshot[_tmpl_idx]

    # Guard 5: 必须真是澄清模板
    from .uncertainty_expression import clarification_meta

    meta = clarification_meta(template)
    if meta is None:
        return

    # Guard 6: question_text 非空
    if not _chosen_text or not _chosen_text.strip():
        return

    # 取 proposition_frame 快照（可能为空 dict）
    proposition_frame = (
        (_cx_parse_result.get("proposition_frame") or {})
        if isinstance(_cx_parse_result, dict) else {}
    )

    confidence = float(getattr(entity, "_understanding_confidence", 0.5))
    tick = int(getattr(entity, "tick", 0))
    now_ts = time.time()

    episode = ClarificationEpisode(
        original_input=raw_input,
        proposition_frame=deepcopy(proposition_frame),
        clarification_kind=meta["kind"],
        clarification_slot=meta["slot"],
        question_text=_chosen_text,
        confidence=confidence,
        tick=tick,
        timestamp=now_ts,
    )

    memory = _get_memory(entity)
    memory.record(episode)
    entity._clarification_memory_data = memory.to_dict()
