"""
Language Resistance Field — 语言阻力场（v11.1）

核心哲学：
    语法不是「对不对」，是「说起来费不费劲」。
    用 bigram 频率表做连续阻力——高频组合阻力低，低频组合阻力高。
    不禁止任何表达，只是让不通顺的组合「更费力」。

设计原则：
    - 全连续，无硬阈值
    - 频率表在模块加载时从词典自动生成
    - 可从外部 corpus 文件加载真实频率（覆盖内置估算）
    - 快——纯 dict 查表，单次 < 1μs
"""

import logging
from typing import Dict, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

# ============================================================================
# 频率表（模块级单例，加载时生成）
# ============================================================================

_BIGRAM_FREQ: Dict[str, float] = {}
_LOADED = False


def _build_bigram_table() -> Dict[str, float]:
    """
    从 SOMATIC_DICTIONARY 自动生成 bigram 频率估算表。

    规律（基于中文词序）：
    - 程度词在前 + 体感词在后 → 高频（很怕、有点累）
    - 体感词在前 + 疑问词在后 → 高频（怕吗、累呢）
    - 动作词在前 + 体感词在后 → 中高频（觉得怕、知道累）
    - 时间/逻辑在前 + 体感词在后 → 中高频（一直怕、因为累）
    - 反向组合（体感+程度、疑问+体感）→ 低频
    - 同类别组合 → 中频

    注意：这只是估算。加载真实语料频率表会覆盖。
    """
    table: Dict[str, float] = {}

    try:
        from .somatic_dictionary import SOMATIC_DICTIONARY

        # 收集各类别词表
        somatic_words: list = []
        for cat in ["body", "emotion", "social", "cognitive", "existential", "micro"]:
            for w in SOMATIC_DICTIONARY.get(cat, {}):
                if w not in somatic_words:
                    somatic_words.append(w)

        degree_words = list(SOMATIC_DICTIONARY.get("degree", {}).keys())
        question_words = list(SOMATIC_DICTIONARY.get("question", {}).keys())
        action_words = list(SOMATIC_DICTIONARY.get("actions", {}).keys())
        time_words = list(SOMATIC_DICTIONARY.get("time", {}).keys())
        logic_words = list(SOMATIC_DICTIONARY.get("logic", {}).keys())

        # ----------------------------------------------------------------
        # 模式 1: degree + somatic → 高频 (0.85-0.95)
        # ----------------------------------------------------------------
        for d in degree_words:
            for s in somatic_words:
                table[f"{d}{s}"] = 0.90

        # ----------------------------------------------------------------
        # 模式 2: somatic + question → 高频 (0.80-0.90)
        # ----------------------------------------------------------------
        for s in somatic_words:
            for q in question_words:
                k = f"{s}{q}"
                if k not in table:
                    table[k] = 0.85

        # ----------------------------------------------------------------
        # 模式 3: action + somatic → 中高频 (0.70-0.85)
        # ----------------------------------------------------------------
        for a in action_words:
            for s in somatic_words:
                k = f"{a}{s}"
                if k not in table:
                    table[k] = 0.78

        # ----------------------------------------------------------------
        # 模式 4: time/logic + somatic → 中高频 (0.65-0.80)
        # ----------------------------------------------------------------
        for t in time_words + logic_words:
            for s in somatic_words:
                k = f"{t}{s}"
                if k not in table:
                    table[k] = 0.72

        # ----------------------------------------------------------------
        # 模式 5: 反向组合（somatic+degree, question+somatic）→ 低频
        #          这些在中文里不通顺，但不说完全不可能
        # ----------------------------------------------------------------
        for s in somatic_words:
            for d in degree_words:
                k = f"{s}{d}"
                if k not in table:
                    table[k] = 0.05
        for q in question_words:
            for s in somatic_words:
                k = f"{q}{s}"
                if k not in table:
                    table[k] = 0.03

        # ----------------------------------------------------------------
        # 模式 6: 同体感词重复 → 高频（激动激动、想你...）
        # ----------------------------------------------------------------
        for w in somatic_words:
            k = f"{w}{w}"
            if k not in table:
                table[k] = 0.88

        logger.info(
            f"[LanguageResistance] 内置 bigram 表: {len(table)} 条 "
            f"(somatic={len(somatic_words)}, degree={len(degree_words)}, "
            f"question={len(question_words)}, action={len(action_words)})"
        )

    except Exception as e:
        logger.warning(f"[LanguageResistance] 生成 bigram 表失败: {e}")

    return table


def _load_corpus_freq(path: str) -> Dict[str, float]:
    """
    从外部 corpus 频率文件加载真实 bigram 频率。
    格式（JSON）:
        {"很怕": 0.92, "有点累": 0.88, "怕很": 0.01, ...}
    值应该是 0-1 之间的归一化频率。
    """
    import json
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return {k: float(v) for k, v in data.items()}
    except Exception as e:
        logger.warning(f"[LanguageResistance] 加载 corpus 文件失败: {path} — {e}")
    return {}


def init(resistance_weight: float = 0.15, corpus_path: Optional[str] = None) -> None:
    """
    初始化语言阻力场（幂等，全局只加载一次）。

    参数：
        resistance_weight : 阻力在总分中的权重 [0, 1]，默认 0.15
        corpus_path       : 可选的外部 bigram 频率 JSON 文件路径
    """
    global _BIGRAM_FREQ, _RESISTANCE_WEIGHT, _LOADED
    if _LOADED:
        return

    _BIGRAM_FREQ = _build_bigram_table()
    _RESISTANCE_WEIGHT = resistance_weight

    # 外部 corpus 覆盖（优先级更高）
    if corpus_path:
        external = _load_corpus_freq(corpus_path)
        if external:
            _BIGRAM_FREQ.update(external)
            logger.info(f"[LanguageResistance] corpus 覆盖: {len(external)} 条")

    _LOADED = True


# 阻力权重（init 后设置）
_RESISTANCE_WEIGHT: float = 0.15


def get_resistance(phrase: str) -> float:
    """
    计算一个短语的「语言阻力」。

    阻力 = 1 - bigram 频率（高频 = 低阻力）
    查不到的组合 → 默认阻力 0.85（高频惩罚未知组合）

    返回值：
        0.0 = 完全通顺（「很怕」）
        1.0 = 极不通顺（「怕很」）
    """
    if not _BIGRAM_FREQ:
        # 未初始化 → 惰性加载
        init()

    freq = _BIGRAM_FREQ.get(phrase, 0.15)  # 未知=低频
    return max(0.0, min(1.0, 1.0 - freq))


def get_resistance_weight() -> float:
    """返回当前阻力权重。"""
    return _RESISTANCE_WEIGHT


# ============================================================================
# 便捷函数：直接修改候选分数
# ============================================================================

def apply_resistance(candidates: list, weight: Optional[float] = None) -> list:
    """
    对候选词列表施加语言阻力，返回调整后的 (word, score) 列表。

    参数：
        candidates : [(word, score), ...]  如 BGE 打分结果
        weight     : 阻力权重，默认使用全局 _RESISTANCE_WEIGHT

    返回：
        [(word, adjusted_score), ...]  已减去阻力的分数
    """
    w = weight if weight is not None else _RESISTANCE_WEIGHT

    adjusted = []
    for word, score, _ in candidates:
        resistance = get_resistance(word)
        adjusted_score = score - resistance * w
        adjusted.append((word, max(0.0, adjusted_score), 0.0))

    return adjusted
