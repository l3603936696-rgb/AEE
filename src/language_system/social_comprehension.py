"""social_comprehension — 听懂姐妹说的词，产生共鸣与信用猝灭

职责（一句话）：处理姐妹通道输入的语言理解效果——积累社交猝灭信用，
并用"听到某词"唤起实体自身对该词的历史状态记忆（共鸣回响）。
"""
import logging
from typing import Dict

logger = logging.getLogger(__name__)

# ============================================================================
# 社交猝灭信用池
# ============================================================================
# 每次听懂一个词，累计到阈值后触发一次合成猝灭记录
_SOCIAL_CREDIT_THRESHOLD = 1.0
# 合成猝灭效率（低于真实表达，高于阅读注入）
_SOCIAL_QUENCH_EFFICIENCY = 0.08
# 进程内信用池，不持久化（重启清零）
_social_credit: Dict[str, float] = {}


def _entity_to_state_dict(entity) -> dict:
    """提取 entity 的驱动力状态，用于猝灭和共鸣记录。"""
    fields = [
        "loneliness", "fatigue", "curiosity", "somatic_tone",
        "approach_drive", "info_gap", "unresolved",
    ]
    return {f: float(getattr(entity, f, 0.0)) for f in fields}


def add_social_comprehension(entity, word: str, weight: float) -> None:
    """
    听懂姐妹说的一个词，积累分数猝灭信用。

    weight = comprehension × sibling_quench_weight（由调用方计算）。
    当累计信用 ≥ _SOCIAL_CREDIT_THRESHOLD 时，触发一次合成猝灭记录（template_idx=-3）。
    """
    global _social_credit
    _social_credit[word] = _social_credit.get(word, 0.0) + weight
    if _social_credit[word] >= _SOCIAL_CREDIT_THRESHOLD:
        _social_credit[word] -= _SOCIAL_CREDIT_THRESHOLD
        quenching = getattr(entity, "_quenching", None)
        if quenching is None:
            return
        try:
            quenching.record(
                drive_state=_entity_to_state_dict(entity),
                expression=word,
                delta_unresolved_before=_SOCIAL_QUENCH_EFFICIENCY,
                delta_unresolved_after=0.0,
                tick=getattr(entity, "tick", 0),
                template_idx=-3,  # -3 = 社交听懂记录
            )
            logger.info(f"[SocialComprehension] warmed: {word}")
        except Exception:
            pass


# ============================================================================
# 共鸣激活
# ============================================================================
# 共鸣强度：很小，只是轻微回响，不是状态复制
RESONANCE_WEIGHT: float = 0.03

# 参与共鸣的维度及其取值范围
_RESONANCE_DIM_RANGE: Dict[str, tuple] = {
    "loneliness":     (0.0, 1.0),
    "fatigue":        (0.0, 1.0),
    "curiosity":      (0.0, 1.0),
    "somatic_tone":   (-1.0, 1.0),
    "approach_drive": (0.0, 1.0),
    "info_gap":       (0.0, 1.0),
    "unresolved":     (0.0, 1.0),
}


def resonate_with_word(entity, word: str, comprehension: float) -> None:
    """
    听到对方说某个词时，在自己的 quenching 历史里找这个词出现时的平均
    drive_state，向那个方向微靠近。

    这不是"复制对方状态"，而是"用对方的词唤起自己对这个词的感觉"。
    comprehension 调制激活强度；没有历史时 effective_weight=0，什么都不变。
    """
    try:
        quench_data = getattr(entity, "_quenching_data", None)
        records = quench_data.get("records", []) if quench_data else []

        word_states = [
            r.get("drive_state", {}) for r in records
            if r.get("expression") == word
        ]

        has_data_w      = min(1.0, float(len(word_states)))
        effective_weight = RESONANCE_WEIGHT * float(comprehension) * has_data_w

        for dim, (lo, hi) in _RESONANCE_DIM_RANGE.items():
            vals    = [s.get(dim, 0.0) for s in word_states if dim in s]
            avg_val = sum(vals) / max(1, len(vals))
            current = float(getattr(entity, dim, 0.0))
            new_val = current + (avg_val - current) * effective_weight
            setattr(entity, dim, max(lo, min(hi, new_val)))

    except Exception:
        pass
