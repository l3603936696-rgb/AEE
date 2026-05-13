"""
Word Warmup — 单字→短句的渐进学习（v1.1）

核心哲学：
    小孩学语的自然路径：
        1. 先会说"好"（单字，锚定一个状态）
        2. 验证"好"是对的 → 说"很好"、"有点好"、"好的"（加修饰语）
        3. 修饰语也被验证 → 说"我今天很好"（组合）
    这是词汇到句法的温跃层——不靠 LLM 生成，靠"已验证的词+模板"。

机制：
    - 追踪每个词的命中次数和平均效率
    - 命中 ≥3 → "永久解锁"，加入 entity._unlocked_vocabulary
    - 永久词汇不会因消力记录被挤出而丢失
    - 变体模板：很{词}、有点{词}、{词}的、{词}了、挺{词}的
    - 变体分数略低于原词（更难，更值钱）

v11.3 改动：解锁与遗忘分离
    - 解锁：累计命中 ≥3 → 永久记入词汇表
    - 活跃度：最近 200 tick 内出现过才产生变体
    - 遗忘：长期不用停止变体注入，但词本身保留（可快速重新激活）
"""

from typing import Any, Dict, List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)

# 短句变体模板
WARMUP_TEMPLATES = [
    "很{word}",
    "有点{word}",
    "{word}的",
    "{word}了",
    "挺{word}",
    "好{word}",
    "{word}一点",
    "不太{word}",
]

# 只有单字或双字词才适用模板（长词加修饰语会不自然）
MAX_WORD_LEN_FOR_WARMUP = 2

# 活跃度窗口：最近 N 个 tick 内出现过才产生变体（约 33 分钟 @10s/tick）
RECENCY_WINDOW_TICKS = 200


def _get_unlocked_vocabulary(entity) -> set:
    """返回永久解锁的词汇表"""
    vocab = getattr(entity, "_unlocked_vocabulary", None)
    if vocab is None:
        return set()
    return set(vocab)


def _unlock_word(entity, word: str):
    """将一个词永久加入词汇表（去重）"""
    vocab = getattr(entity, "_unlocked_vocabulary", None)
    if vocab is None:
        entity._unlocked_vocabulary = []
        vocab = entity._unlocked_vocabulary
    if word not in vocab:
        vocab.append(word)
        print(f"[WordWarmup] 永久解锁: {word}", flush=True)
        logger.info(f"[WordWarmup] 永久解锁: {word}")


def get_word_stats(entity) -> Dict[str, Dict[str, float]]:
    """
    从 entity 的消力记录中提取每个词的统计：
        - hit_count: 使用次数
        - avg_efficiency: 平均消力效率
        - last_tick: 最后使用 tick
    """
    quench_data = getattr(entity, "_quenching_data", None)
    records = quench_data.get("records", []) if quench_data else []
    
    stats: Dict[str, Dict[str, float]] = {}
    for r in records:  # 全部记录（deque maxlen=500，可控）
        expr = r.get("expression", "")
        eff = r.get("quenching_efficiency", 0)
        tick = r.get("tick", 0) if "tick" in r else 0
        
        if expr not in stats:
            stats[expr] = {"hit_count": 0, "total_eff": 0.0, "last_tick": 0}
        stats[expr]["hit_count"] += 1
        stats[expr]["total_eff"] += eff
        stats[expr]["last_tick"] = max(stats[expr]["last_tick"], tick)
    
    # 计算平均值
    for w in stats:
        stats[w]["avg_efficiency"] = stats[w]["total_eff"] / max(1, stats[w]["hit_count"])
    
    return stats


def get_warm_words(
    entity,
    min_hits: int = 3,
    min_best_efficiency: float = 0.15,
) -> List[str]:
    """
    返回已达到"热身"标准的词。

    v11.3:
        - 滑动窗口内 ≥min_hits 次命中 → 永久解锁，加入词汇表
        - 永久词汇表中近期活跃的词也返回（不因记录挤出而丢失）
        - 长期不活跃的词不产生变体，但保留在词汇表中

    v11.2: 纯频率驱动——≥min_hits 次命中即解锁变体。
    效率仍然记录（用于消力反馈/策略地图），但不卡热身门槛。
    """
    stats = get_word_stats(entity)
    unlocked = _get_unlocked_vocabulary(entity)
    current_tick = getattr(entity, "tick", 0)
    
    warm = []
    
    # 1) 滑动窗口内达标 → 永久解锁
    for word, s in stats.items():
        if len(word) > MAX_WORD_LEN_FOR_WARMUP:
            continue
        if s["hit_count"] < min_hits:
            continue
        warm.append(word)
        # 永久解锁（去重自动处理）
        _unlock_word(entity, word)
    
    # 2) 永久词汇表中的词直接保持暖词（不依赖消力窗口时效）
    #    已解锁 = 持久化确认过"这个词在多种身体状态下被匹配过"。
    #    不应因为重启或记录挤出而丢失热身状态。
    try:
        from .somatic_concept_map import SOMATIC_ANCHORS as _SA
    except Exception:
        _SA = {}
    for word in unlocked:
        if word in warm:
            continue
        if len(word) > MAX_WORD_LEN_FOR_WARMUP:
            continue
        # 在锚点表里的词 → 无条件暖词
        if word in _SA:
            warm.append(word)
            continue
        # 不在锚点表但在 stats 里且近期活跃 → 仍可暖
        if word in stats:
            last_tick = stats[word]["last_tick"]
            if (current_tick - last_tick) < RECENCY_WINDOW_TICKS:
                warm.append(word)
    
    if warm:
        print(f"[WordWarmup] get_warm_words found: {warm}", flush=True)
    return warm


def generate_warmup_variants(warm_words: List[str], anchor_scores: Optional[Dict[str, float]] = None) -> List[Tuple[str, float]]:
    """
    为每个热身词生成模板变体。

    返回: [(variant_word, base_score), ...]
        变体基础分 = 父词锚点分 × 0.7（无锚点分时默认 0.30），
        确保变体只在父词真正匹配的状态下才有竞争力。
    """
    variants = []
    for word in warm_words:
        # 变体基础分 = 父词锚点分的 70%，比原词保守
        parent_score = anchor_scores.get(word, 0.30) if anchor_scores else 0.30
        base = parent_score * 0.5
        for template in WARMUP_TEMPLATES:
            variant = template.format(word=word)
            # 避免生成无意义的重复（"好好的"、"很很"）
            if word in variant.replace(word, "", 1):
                continue  # 原词出现两次 → 跳过
            variants.append((variant, base))
    return variants


def inject_warmup_candidates(
    entity,
    current_candidates: List[Tuple[str, float]],
    min_hits: int = 3,
    min_best_efficiency: float = 0.15,
    anchor_scores: Optional[Dict[str, float]] = None,
) -> List[Tuple[str, float]]:
    """
    一站式：检测热身词 → 生成变体 → 注入候选池。

    anchor_scores: {word: anchor_match_score} — 如果提供，只对锚点分 > 0.2 的词注入变体，
                   防止热身词在不相关的状态下抢镜（如“累”抢冷态的表达）。
    """
    try:
        warm_words = get_warm_words(entity, min_hits, min_best_efficiency)
        logger.info(f"[WordWarmup] checked: {len(warm_words)} warm, {len(current_candidates)} candidates")
        if not warm_words:
            return current_candidates

        # 过滤：只保留在当前状态下纯匹配率 > 0.5 的热身词
        if anchor_scores is not None:
            filtered = [w for w in warm_words if anchor_scores.get(w, 0.0) > 0.5]
            if len(filtered) < len(warm_words):
                logger.debug(
                    f"[WordWarmup] anchor filter: {len(filtered)}/{len(warm_words)} "
                    f"warm words relevant (match>0.5)"
                )
            warm_words = filtered
        if not warm_words:
            return current_candidates

        variants = generate_warmup_variants(warm_words, anchor_scores)
        if not variants:
            return current_candidates
        
        # 已有候选的词名集合
        existing_words = {c[0] for c in current_candidates}
        
        injected = 0
        for variant_word, base_score in variants:
            if variant_word not in existing_words:
                current_candidates.append((variant_word, base_score, 0.0))
                injected += 1
        
        if injected > 0:
            logger.info(
                f"[WordWarmup] {len(warm_words)} warm words ({', '.join(warm_words)}) "
                f"→ {injected} variants injected"
            )
            # Also print for debugging in case logger isn't configured
            print(f"[WordWarmup] {len(warm_words)} warm words → {injected} variants", flush=True)
    except Exception as e:
        logger.debug(f"[WordWarmup] failed: {e}")
    
    return current_candidates
