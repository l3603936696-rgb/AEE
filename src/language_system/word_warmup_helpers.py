"""
Word Warmup Helpers — 解码与休息巩固。

包含：
    _decode_state_hash() — drive_state_hash 字符串解码
    _build_word_profile() — 词状态画像构建
    REST_CONSOLIDATION_WEIGHT / MAX_SYNTHETIC_PER_TICK / SYNTHETIC_QUENCHING_EFFICIENCY / MIN_REST_STRENGTH_RATIO
    _entity_to_state_dict()
    consolidate_during_rest()
"""

from typing import Dict

# drive_state_hash 解码表（桶标签 → 区间中值）
# 与 quenching_helpers._hash_state 对应
_COARSE_MID: Dict[str, float] = {"L": 0.1, "ML": 0.3, "M": 0.5, "MH": 0.7, "H": 0.9}
_FINE_MID: Dict[str, float] = {
    "vL": 0.05, "L": 0.15, "LM": 0.25, "M": 0.35, "MH": 0.45,
    "H": 0.55, "H+": 0.65, "VH": 0.75, "VH+": 0.85, "MAX": 0.95,
}
_FINE_KEYS = frozenset({"danger_level", "fatigue", "stress", "pain", "unresolved", "relief_debt"})


def _decode_state_hash(state_hash: str) -> Dict[str, float]:
    """将 drive_state_hash 字符串解码为近似状态 dict。

    格式示例：'fatigue=MH|loneliness=L|curiosity=H'
    返回：{'fatigue': 0.45, 'loneliness': 0.1, 'curiosity': 0.9}
    （fatigue 是 fine key，MH→0.45；loneliness/curiosity 是 coarse key，L→0.1，H→0.9）
    """
    if not state_hash:
        return {}
    result: Dict[str, float] = {}
    for part in state_hash.split("|"):
        if "=" not in part:
            continue
        key, bucket = part.split("=", 1)
        table = _FINE_MID if key in _FINE_KEYS else _COARSE_MID
        val = table.get(bucket)
        if val is not None:
            result[key] = val
    return result


def _build_word_profile(entity, word: str) -> Dict[str, float]:
    """
    从 quenching records 聚合词的状态画像。

    对所有含该词的记录，解码 drive_state_hash 得到近似状态，取均值。
    结果是"她遇到这个词时通常处于什么状态"——reading 共现的积累。
    """
    quench_data = getattr(entity, "_quenching_data", None)
    records = quench_data.get("records", []) if quench_data else []

    state_sums: Dict[str, float] = {}
    count = 0
    for r in records:
        if r.get("expression") != word:
            continue
        decoded = _decode_state_hash(r.get("drive_state_hash", ""))
        if not decoded:
            continue
        for dim, val in decoded.items():
            state_sums[dim] = state_sums.get(dim, 0.0) + val
        count += 1

    if count == 0:
        return {}
    return {dim: v / count for dim, v in state_sums.items()}


# ============================================================================
# Rest Consolidation — 休息期间的词汇巩固
# ============================================================================

# 各 action_type 的基础巩固权重
REST_CONSOLIDATION_WEIGHT = {
    "rest": 1.0, "comfort": 0.3, "idle": 0.1,
    "sleep": 0.8, "avoid": 0.0, "seek": 0.0,
    "explore": 0.0, "repair": 0.0,
}
MAX_SYNTHETIC_PER_TICK = 2
SYNTHETIC_QUENCHING_EFFICIENCY = 0.05
MIN_REST_STRENGTH_RATIO = 0.2


def _entity_to_state_dict(entity) -> dict:
    """提取 entity 的驱动力状态用于消力记录。"""
    fields = [
        "loneliness", "fatigue", "curiosity", "somatic_tone",
        "approach_drive", "info_gap", "unresolved",
    ]
    result = {}
    for f in fields:
        val = getattr(entity, f, None)
        result[f] = float(val) if val is not None else 0.0
    return result


def consolidate_during_rest(entity, action_type: str) -> int:
    """
    Rest 期间的词汇巩固：对最近接触但未达标的词产生合成消力记录。

    类比人在休息时反刍最近学过的东西。不是重新获取信息，
    而是把已接触的词在内部"重新匹配"一遍，加速从冷到温的进程。

    返回注入的合成记录数。
    """
    from src.language_system.word_warmup import get_word_stats, RECENCY_WINDOW_TICKS
    base_weight = REST_CONSOLIDATION_WEIGHT.get(action_type, 0.0)
    fatigue = float(getattr(entity, "fatigue", 0.5))
    rest_strength = base_weight * (MIN_REST_STRENGTH_RATIO + (1.0 - MIN_REST_STRENGTH_RATIO) * fatigue)
    n_synthetic = int(MAX_SYNTHETIC_PER_TICK * rest_strength)

    quenching = getattr(entity, "_quenching", None)
    stats = get_word_stats(entity)
    current_tick = getattr(entity, "tick", 0)

    candidates = []
    for word, s in stats.items():
        warmth = min(1.0, s["hit_count"] / 3.0)
        gap = 1.0 - warmth
        recency = max(0.0, 1.0 - (current_tick - s["last_tick"]) / max(1, RECENCY_WINDOW_TICKS))
        priority = gap * (warmth * 0.4 + recency * 0.6)
        candidates.append((word, priority))

    candidates.sort(key=lambda x: x[1], reverse=True)

    injected = 0
    for i in range(min(n_synthetic, len(candidates))):
        word, _pri = candidates[i]
        eff = SYNTHETIC_QUENCHING_EFFICIENCY * min(1.0, _pri * 5.0)
        try:
            quenching.record(
                drive_state=_entity_to_state_dict(entity),
                expression=word,
                delta_unresolved_before=eff,
                delta_unresolved_after=0.0,
                tick=current_tick,
                template_idx=-2,   # -2 = 合成巩固记录，区别于 -1 的阅读注入
            )
            injected += 1
        except Exception:
            pass

    return injected
