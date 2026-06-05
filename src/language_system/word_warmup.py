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


# drive_state_hash 解码表（桶标签 → 区间中值）
# 与 quenching.py 的 _hash_state 对应
_COARSE_MID: Dict[str, float] = {"L": 0.1, "ML": 0.3, "M": 0.5, "MH": 0.7, "H": 0.9}
_FINE_MID: Dict[str, float] = {
    "vL": 0.05, "L": 0.15, "LM": 0.25, "M": 0.35, "MH": 0.45,
    "H": 0.55, "H+": 0.65, "VH": 0.75, "VH+": 0.85, "MAX": 0.95,
}
# 使用细粒度桶的维度（与 quenching.py._hash_state 保持一致）
_FINE_KEYS = frozenset({"danger_level", "fatigue", "stress", "pain", "unresolved", "relief_debt"})


def _decode_state_hash(state_hash: str) -> Dict[str, float]:
    """将 quenching 的 drive_state_hash 字符串解码为近似状态 dict。

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
        # 如果 _warm_words 里还没有状态画像，从 quenching records 聚合一个
        # 这是 reading 共现数据真正被使用的地方
        _wm = getattr(entity, "_warm_words", None)
        if _wm is None:
            entity._warm_words = {}
            _wm = entity._warm_words
        if word not in _wm:
            _profile = _build_word_profile(entity, word)
            if _profile:
                _wm[word] = {
                    "profile": _profile,
                    "acquired_tick": current_tick,
                    "source": "reading",
                }
                logger.info(f"[WordWarmup] 状态画像: {word} → {list(_profile.keys())}")
    
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
                current_candidates.append((variant_word, base_score))
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


# add_social_comprehension 和 resonate_with_word 已迁移到 social_comprehension.py，
# 此处重新导出保持调用方兼容。
from .social_comprehension import (  # noqa: E402, F401
    add_social_comprehension,
    resonate_with_word,
)


# ============================================================================
# Rest Consolidation — 休息期间的词汇巩固
# ============================================================================

# 各 action_type 的基础巩固权重（dict dispatch，无 if-else）
REST_CONSOLIDATION_WEIGHT = {
    "rest": 1.0, "comfort": 0.3, "idle": 0.1,
    "sleep": 0.8, "avoid": 0.0, "seek": 0.0,
    "explore": 0.0, "repair": 0.0,
}

# 每 tick 最大合成记录数
MAX_SYNTHETIC_PER_TICK = 2

# 合成记录的消力效率（低于真实表达 0.1~0.5，高于阅读注入 0.0）
SYNTHETIC_QUENCHING_EFFICIENCY = 0.05

# fatigue=0 时仍保留的最低巩固强度比例
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
    base_weight = REST_CONSOLIDATION_WEIGHT.get(action_type, 0.0)
    fatigue = float(getattr(entity, "fatigue", 0.5))
    rest_strength = base_weight * (MIN_REST_STRENGTH_RATIO + (1.0 - MIN_REST_STRENGTH_RATIO) * fatigue)
    n_synthetic = int(MAX_SYNTHETIC_PER_TICK * rest_strength)

    # n_synthetic == 0 → 本 action 不巩固，range(0) 自然跳过
    quenching = getattr(entity, "_quenching", None)
    stats = get_word_stats(entity)
    current_tick = getattr(entity, "tick", 0)

    # 候选：连续 priority scoring
    # warmth = hit_count/3 ∈ [0,1]，gap = 1-warmth（已 warm 则 gap=0，自然排除）
    # recency = 距上次出现的新近度 ∈ [0,1]
    # priority = gap * (warmth * 0.4 + recency * 0.6)
    #   gap 项保证已 warm 的词 priority=0
    #   warmth * 0.4 偏好"差一点就 warm"的词（hit=2 > hit=1）
    #   recency * 0.6 偏好最近接触过的词
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
        # priority 极低时合成效率也趋近 0，自然不影响
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

    if injected > 0:
        _words = [c[0] for c in candidates[:injected]]
        print(f"[WordWarmup] Rest consolidation: {injected} synthetic records for {_words}", flush=True)
        logger.info(f"[WordWarmup] Rest consolidation: {injected} records")

    return injected
