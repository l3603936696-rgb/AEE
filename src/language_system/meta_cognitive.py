"""
Meta-Cognitive Monitor -- 快照驱动的自我观察学习（v1.0）

核心哲学：
    她不只是在学"什么词对应什么状态"，她还在学"我的学习进行得怎么样"。
    这是第二层学习——元认知。通过扫描自己的快照历史，察觉：
    - 反复说同一个词但无效 → 厌倦/绝望
    - 词汇太窄 → 语言压力
    - 状态维度锁死 → 好奇心或挫折感

设计原则：
    - 只读快照，不修改快照
    - 输出是 somatic/emotion delta，由调用方选择是否应用
    - 所有信号连续，无硬阈值
    - 参数外置，随训练阶段可调
"""

import logging
from typing import Any, Dict, List, Optional, Set
from collections import Counter

logger = logging.getLogger(__name__)


def analyze_snapshots(
    entity,
    snapshots: List[Dict[str, Any]],
    quenching_records: List[Dict[str, Any]],
    lookback: int = 15,
) -> Dict[str, float]:
    """扫描最近 snapshots，生成元认知信号。"""
    if not snapshots or not quenching_records:
        return {}

    recent_snaps = snapshots[-lookback:] if len(snapshots) > lookback else snapshots
    recent_quench = quenching_records[-lookback:] if len(quenching_records) > lookback else quenching_records

    signals: Dict[str, float] = {}

    # 1. 口头死锁检测
    if recent_quench:
        expr_counter = Counter()
        zero_eff_counter = Counter()
        for r in recent_quench:
            expr = r.get("expression", "")
            eff = r.get("quenching_efficiency", 0)
            expr_counter[expr] += 1
            if eff < 0.01:
                zero_eff_counter[expr] += 1

        total = len(recent_quench)
        if total >= 3:
            dominant_expr, dominant_count = expr_counter.most_common(1)[0]
            dominance_ratio = dominant_count / total
            zero_count = zero_eff_counter.get(dominant_expr, 0)
            if dominance_ratio > 0.6 and zero_count >= dominant_count * 0.8:
                lock_severity = dominance_ratio
                signals["boredom_despair"] = lock_severity * 0.03
                signals["boredom_futility"] = lock_severity * 0.04
                signals["stress"] = lock_severity * 0.02
                logger.info(
                    f"[MetaCognitive] Verbal deadlock: '{dominant_expr}' "
                    f"dominates {dominance_ratio:.0%} with zero efficiency"
                )

    # 2. 词汇贫乏检测
    unique_words: Set[str] = set()
    for r in recent_quench:
        unique_words.add(r.get("expression", ""))
    vocab_size = len(unique_words)
    if len(recent_quench) >= 5 and vocab_size <= 2:
        poverty = 1.0 - (vocab_size / 5.0)
        signals["boredom_despair"] = signals.get("boredom_despair", 0) + poverty * 0.02
        signals["stress"] = signals.get("stress", 0) + poverty * 0.015
        logger.info(
            f"[MetaCognitive] Vocabulary poverty: {vocab_size} words "
            f"in {len(recent_quench)} expressions"
        )

    # 3. 状态锁死检测
    LOCK_DIMS = {
        "approach_drive": 0.5, "avoid_drive": 0.5,
        "stress": 0.1, "somatic_tone": 0.0,
        "energy": 0.5, "loneliness": 0.3,
    }
    stuck_count: Dict[str, int] = {}
    for dim, neutral in LOCK_DIMS.items():
        extreme_count = 0
        for snap in recent_snaps:
            val = snap.get(dim, neutral)
            if abs(val - neutral) > 0.4:
                extreme_count += 1
        if extreme_count >= len(recent_snaps) * 0.8:
            stuck_count[dim] = extreme_count

    if stuck_count:
        lock_ratio = len(stuck_count) / len(LOCK_DIMS)
        signals["boredom_futility"] = signals.get("boredom_futility", 0) + lock_ratio * 0.03
        if "curiosity" not in signals:
            signals["curiosity"] = 0.02
        logger.info(
            f"[MetaCognitive] State lock: {list(stuck_count.keys())} "
            f"stuck in {len(recent_snaps)} snaps"
        )

    # 4. 效率趋势
    if len(recent_quench) >= 8:
        mid = len(recent_quench) // 2
        first_half = recent_quench[:mid]
        second_half = recent_quench[mid:]
        avg_first = sum(r.get("quenching_efficiency", 0) for r in first_half) / max(1, len(first_half))
        avg_second = sum(r.get("quenching_efficiency", 0) for r in second_half) / max(1, len(second_half))
        trend = avg_second - avg_first
        if trend < -0.03:
            signals["sadness"] = abs(trend) * 0.5
            logger.info(f"[MetaCognitive] Efficiency declining: {avg_first:.3f} -> {avg_second:.3f}")
        elif trend > 0.03:
            signals["joy"] = trend * 0.3
            logger.info(f"[MetaCognitive] Efficiency improving: {avg_first:.3f} -> {avg_second:.3f}")

    return signals


def apply_meta_cognitive(
    entity,
    snapshots: List[Dict[str, Any]],
    quenching_records: List[Dict[str, Any]],
    lookback: int = 15,
    scaling: float = 1.0,
) -> Dict[str, float]:
    """一站式：分析快照 + 应用元认知信号到 entity。"""
    signals = analyze_snapshots(entity, snapshots, quenching_records, lookback)

    applied = {}
    for dim, delta in signals.items():
        if hasattr(entity, dim) and abs(delta) > 1e-6:
            current = float(getattr(entity, dim, 0.0))
            scaled = delta * scaling
            if dim in ("somatic_tone",):
                lo, hi = -1.0, 1.0
            else:
                lo, hi = 0.0, 1.0
            setattr(entity, dim, max(lo, min(hi, current + scaled)))
            applied[dim] = round(scaled, 4)

    if applied:
        logger.info(
            f"[MetaCognitive] Applied: "
            f"{', '.join(f'{k}{v:+.3f}' for k, v in applied.items())}"
        )
        reasons = []
        if "boredom_despair" in applied or "boredom_futility" in applied:
            recent_exprs = [r.get("expression","") for r in quenching_records[-lookback:]]
            if recent_exprs:
                c = Counter(recent_exprs)
                dom, cnt = c.most_common(1)[0]
                if cnt >= len(recent_exprs) * 0.6:
                    reasons.append(f"最近{len(recent_exprs)}次中说了'{dom}'{cnt}次但效率接近零")
        event = {
            "type": "meta_cognitive",
            "signals_applied": applied,
            "reasons": reasons,
            "description": "元认知检测：" + "；".join(reasons) if reasons else "",
            "tick": getattr(entity, "tick", 0),
        }
        if hasattr(entity, "_last_meta_event"):
            entity._last_meta_event = event

    return applied


def get_language_intervention(
    quenching_records: List[Dict[str, Any]],
    lookback: int = 15,
) -> Dict[str, Any]:
    """
    从消力记录中诊断语言学习状态，返回候选词选择干预策略。

    不修改 entity 状态——只返回干预信号，由调用方在候选词排序时应用。

    返回：
        {
            "deadlock_detected": bool,
            "dominant_word": str | None,
            "dominance_ratio": float,
            "penalty_words": {str: float},    # 词 → 惩罚系数（乘在分数上）
            "exploration_boost": float,       # 非主导词的加分
            "vocab_size": int,
            "avg_efficiency": float,
        }
    """
    if not quenching_records:
        return {"deadlock_detected": False, "dominant_word": None}

    recent = quenching_records[-lookback:] if len(quenching_records) > lookback else quenching_records
    total = len(recent)
    if total < 3:
        return {"deadlock_detected": False, "dominant_word": None}

    # 统计词频和效率
    expr_counter = Counter()
    zero_eff_counter = Counter()
    eff_by_word: Dict[str, list] = {}
    for r in recent:
        expr = r.get("expression", "")
        eff = r.get("quenching_efficiency", 0)
        expr_counter[expr] += 1
        if eff < 0.01:
            zero_eff_counter[expr] += 1
        eff_by_word.setdefault(expr, []).append(eff)

    dominant_word, dominant_count = expr_counter.most_common(1)[0]
    dominance_ratio = dominant_count / total
    zero_count = zero_eff_counter.get(dominant_word, 0)

    intervention: Dict[str, Any] = {
        "deadlock_detected": False,
        "dominant_word": dominant_word,
        "dominance_ratio": round(dominance_ratio, 3),
        "penalty_words": {},
        "exploration_boost": 0.0,
        "vocab_size": len(expr_counter),
        "avg_efficiency": round(
            sum(sum(vals) for vals in eff_by_word.values()) / max(1, sum(len(v) for v in eff_by_word.values())),
            4
        ),
    }

    # 口头死锁：主导词占 >60% 且效率为零
    if dominance_ratio > 0.6 and zero_count >= dominant_count * 0.8:
        intervention["deadlock_detected"] = True
        # 惩罚力度 = 主导率 × 效率衰减（0 效率 → 强惩罚）
        penalty = dominance_ratio * (1.0 - intervention["avg_efficiency"])
        intervention["penalty_words"][dominant_word] = max(0.3, penalty * 0.7)
        # 探索 boost = 死锁严重度
        intervention["exploration_boost"] = dominance_ratio * 0.15
        logger.info(
            f"[MetaCognitive] Language intervention: penalize '{dominant_word}' "
            f"by {intervention['penalty_words'][dominant_word]:.2f}, "
            f"exploration_boost={intervention['exploration_boost']:.3f}"
        )

    # 词汇贫乏：≤2 个词在 lookback 窗口 → 额外探索 boost
    if len(expr_counter) <= 2 and total >= 5:
        intervention["exploration_boost"] += 0.10
        logger.info(
            f"[MetaCognitive] Vocabulary poverty boost: +0.10 exploration"
        )

    # 效率整体下降 → 增加探索
    if total >= 8:
        mid = total // 2
        avg_first = sum(
            sum(eff_by_word.get(r.get("expression", ""), [0]))
            for r in recent[:mid]
        ) / max(1, mid)
        avg_second = sum(
            sum(eff_by_word.get(r.get("expression", ""), [0]))
            for r in recent[mid:]
        ) / max(1, total - mid)
        if avg_second < avg_first * 0.7:
            intervention["exploration_boost"] += 0.08
            logger.info(
                f"[MetaCognitive] Efficiency decline boost: +0.08 exploration"
            )

    return intervention
