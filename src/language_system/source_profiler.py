"""
Source Profiler — 他者建模：来源识别、状态历史、地位值（v2.0）

不产生任何行为输出，只积累数据供后续层使用。

source_id 规则：
    "external"          ← 用户输入（_input_source == "external"）
    "sibling:<peer>"    ← 姐妹通道（_input_source == "sibling"，peer_name 来自 _sibling_channel）
    "none"              ← 不建档

派生变量（on-the-fly，不存储）：
    familiarity   = 1 - exp(-interaction_count / FAMILIARITY_SCALE)     ∈ [0,1]
    trust         = sigmoid(-mean(loneliness_delta*2 + unresolved_delta)) ∈ [0,1]
    status_belief ∈ [-1,1]，零基线，存储在 profile 中，学习率随历史衰减
"""

import math
from typing import List, Optional, Tuple

FAMILIARITY_SCALE = 50.0    # 半饱和：50 次交互 → familiarity ≈ 0.63
TRUST_SCALE       = 0.05    # trust sigmoid 温度参数
DELTA_LOG_MAXLEN  = 50      # 每个 source 保留的 delta 记录数
BASE_STATUS_LR    = 0.1     # 地位值基础学习率（随 √n 衰减）
DELTA_DIMS = ("stress", "unresolved", "loneliness", "fatigue", "boredom")


def _default_profile() -> dict:
    return {
        "interaction_count": 0,
        "last_tick": 0,
        "word_counts": {},
        "intent_counts": {},
        "delta_log": [],
        "status_belief": 0.0,           # 地位值：我对这个人是否重要，零基线
        "status_interaction_count": 0,  # 独立计数，用于学习率衰减
    }


def get_source_id(input_source: str, entity) -> str:
    """把 _input_source 映射到持久化用的 source_id。"""
    if input_source == "sibling":
        peer = getattr(entity, "_sibling_channel", {}).get("peer_name", "unknown")
        return f"sibling:{peer}"
    return input_source  # "external" 或 "none"


def update_profile(
    entity,
    source_id: str,
    cx_recognized_words: Optional[List[Tuple[str, float]]],
    social_intent: str,
    causal_delta: dict,
    tick: int,
) -> None:
    """更新 source_id 对应的 profile（in-place）。"""
    profiles = getattr(entity, "_source_profiles", None)
    if profiles is None:
        entity._source_profiles = {}
        profiles = entity._source_profiles

    p = profiles.setdefault(source_id, _default_profile())
    p["interaction_count"] += 1
    p["last_tick"] = tick

    for word, _ in (cx_recognized_words or []):
        p["word_counts"][word] = p["word_counts"].get(word, 0) + 1

    if social_intent and social_intent != "unknown":
        p["intent_counts"][social_intent] = (
            p["intent_counts"].get(social_intent, 0) + 1
        )

    log_entry = {"tick": tick}
    for dim in DELTA_DIMS:
        log_entry[dim] = float(causal_delta.get(dim, 0.0))
    p["delta_log"].append(log_entry)
    if len(p["delta_log"]) > DELTA_LOG_MAXLEN:
        p["delta_log"] = p["delta_log"][-DELTA_LOG_MAXLEN:]

    # ---- 地位值更新（patch-01 + patch-02-一：历史频次加权学习率）----
    _n = p.get("status_interaction_count", 0) + 1
    p["status_interaction_count"] = _n
    _lr = BASE_STATUS_LR / math.sqrt(_n)
    # 期望差张力：对方出现后 loneliness 和 unresolved 下降 → 地位值上升
    _tension = -(
        causal_delta.get("loneliness", 0.0)
        + causal_delta.get("unresolved", 0.0)
    )
    _sb = p.get("status_belief", 0.0) + _lr * _tension
    p["status_belief"] = max(-1.0, min(1.0, _sb))


def get_familiarity(entity, source_id: str) -> float:
    """familiarity ∈ [0,1]，连续函数，无阈值分支。"""
    profiles = getattr(entity, "_source_profiles", {})
    count = profiles.get(source_id, {}).get("interaction_count", 0)
    return 1.0 - math.exp(-count / FAMILIARITY_SCALE)


def get_trust(entity, source_id: str) -> float:
    """trust ∈ [0,1]；对方出现后 loneliness / unresolved 趋于下降 → trust 高。

    注：社交接触本身带来轻微 stress 激活是正常的，不作为信任负信号。
    """
    profiles = getattr(entity, "_source_profiles", {})
    log = profiles.get(source_id, {}).get("delta_log", [])
    if not log:
        return 0.5  # 无历史 → 中性
    raw = sum(
        -e.get("loneliness", 0.0) * 2.0   # 孤独缓解是主要正信号
        - e.get("unresolved", 0.0)          # unresolved 上升是负信号
        for e in log
    ) / len(log)
    return 1.0 / (1.0 + math.exp(-raw / TRUST_SCALE))


def get_status_belief(entity, source_id: str) -> float:
    """status_belief ∈ [-1,1]；零基线，正值表示对方可能视我重要。"""
    profiles = getattr(entity, "_source_profiles", {})
    return profiles.get(source_id, {}).get("status_belief", 0.0)
