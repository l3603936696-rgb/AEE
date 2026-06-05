"""
Interpretation Competition — 解释竞争机制（v1.0）

职责：
    实现纲领第三节"解释动力学"中的解释竞争子机制。

    多条经验被激活，指向不同的解释方向，彼此竞争。
    竞争力 = 经验强度 × f(当前状态变量) × 转换系数

    竞争不强制收敛到单一赢家——当多解竞争力接近时，
    系统进入张力悬置状态，多个 attractor 同时维持，
    这个悬置本身会渗透进输出。

设计原则：
    - 所有逻辑连续，无 if-else 分支
    - 用 max(strategies) + softmax 权重分发
    - 不修改 entity 状态，只输出竞争结果供后续使用
"""

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ============================================================================
# 常量
# ============================================================================

# 张力悬置门控：top1 / top2 分数比低于此值时进入悬置状态
TENSION_THRESHOLD: float = 1.15
# 竞争力最小有效差值（避免数值噪声）
COMPETITION_EPS: float = 0.001
# 最多保留的候选解释数量
MAX_CANDIDATES: int = 8
# 经验置信度基础值（未验证经验的默认值）
BASE_EXPERIENCE_CONFIDENCE: float = 0.5
# 经验衰退率（每 N tick 未被激活，置信度小幅下降）
CONFIDENCE_DECAY_RATE: float = 0.001


# ============================================================================
# 数据类
# ============================================================================

@dataclass
class ExperienceCandidate:
    """
    候选解释。

    字段：
        interpretation : 解释文本描述
        source_id     : 来源（刻板印象节点名 / 个体 profile 名）
        experience_id : 经验唯一标识
        confidence    : 经验置信度 [0, 1]，来自刻板印象树或个体 profile
        emotion_mod   : 该经验对当前情绪的激活程度（连续值）
        conversion    : 转换系数，实体天生对该类刺激的放大倍率
        competitive_score : 计算后的竞争力（由竞争器填充）
    """
    interpretation: str
    source_id: str
    experience_id: str
    confidence: float = BASE_EXPERIENCE_CONFIDENCE
    emotion_mod: float = 0.5
    conversion: float = 1.0
    competitive_score: float = 0.0

    def to_dict(self) -> dict:
        return {
            "interpretation": self.interpretation,
            "source_id": self.source_id,
            "experience_id": self.experience_id,
            "confidence": round(self.confidence, 4),
            "emotion_mod": round(self.emotion_mod, 4),
            "conversion": round(self.conversion, 4),
            "competitive_score": round(self.competitive_score, 4),
        }


@dataclass
class CompetitionResult:
    """
    竞争结果。

    字段：
        winner           : 胜出解释（竞争显著占优时），否则 None
        tension_level    : 张力水平 [0, 1]，悬置时 > 0
        tension_type     : "suspended"（悬置）| "attractor"（单一吸引子）| "none"（无竞争）
        candidates       : 所有候选及其竞争力
        top_scores       : top2 分数（用于调试）
    """
    winner: Optional[ExperienceCandidate]
    tension_level: float
    tension_type: str
    candidates: List[ExperienceCandidate]
    top_scores: Tuple[float, float]

    def to_dict(self) -> dict:
        return {
            "winner": self.winner.to_dict() if self.winner else None,
            "tension_level": round(self.tension_level, 4),
            "tension_type": self.tension_type,
            "top_scores": [round(s, 4) for s in self.top_scores],
            "candidates": [c.to_dict() for c in self.candidates],
        }


# ============================================================================
# 竞争力计算
# ============================================================================

def compute_competitive_score(
    candidate: ExperienceCandidate,
    state_snapshot: Dict[str, float],
) -> float:
    """
    竞争力 = 经验强度 × f(当前状态变量) × 转换系数

    经验强度：candidate.confidence ∈ [0, 1]
    f(当前状态变量)：复用行为动力学的情绪调制输出
    转换系数：candidate.conversion ∈ [0.5, 2.0]

    情绪调制：loneliness ↑ → 情感类经验竞争力增强
              stress ↑ → 分析类经验竞争力下降
              somatic_tone 负值 → 痛苦经验权重上升
    """
    # 经验强度
    strength = candidate.confidence

    # f(当前状态)：情绪调制连续函数
    loneliness = float(state_snapshot.get("loneliness", 0.3))
    stress = float(state_snapshot.get("stress", 0.1))
    somatic_tone = float(state_snapshot.get("somatic_tone", 0.0))
    boredom = float(state_snapshot.get("boredom", 0.2))

    # 孤独激活：提升情感共鸣类经验的竞争力
    emotion_boost = loneliness * 0.3

    # 压力衰减：stress 高时削弱理性分析类经验
    stress_decay = 1.0 - stress * 0.25

    # 痛苦放大：somatic_tone 负值时提升痛苦相关经验
    pain_amplify = 1.0 + max(0.0, -somatic_tone) * 0.2

    # 无聊微弱化：boredom 高时整体竞争力轻微衰减
    boredom_decay = 1.0 - boredom * 0.1

    f_state = (1.0 + emotion_boost) * stress_decay * pain_amplify * boredom_decay

    # 转换系数
    conversion = candidate.conversion

    # 最终竞争力（截断到合理范围）
    score = strength * f_state * conversion
    return max(0.0, min(3.0, score))


def _softmax_weights(scores: List[float], temperature: float = 0.1) -> List[float]:
    """
    Softmax 权重分发：分数 → 概率分布。

    temperature 低 → 强者权重极高（趋近 argmax）
    temperature 高 → 分布均匀（趋近均匀分布）
    """
    if not scores or all(s <= COMPETITION_EPS for s in scores):
        n = len(scores) if scores else 1
        return [1.0 / n] * n

    max_s = max(scores)
    exps = [math.exp((s - max_s) / temperature) for s in scores]
    total = sum(exps)
    if total < 1e-9:
        n = len(scores)
        return [1.0 / n] * n
    return [e / total for e in exps]


# ============================================================================
# 候选解释生成
# ============================================================================

def build_candidates_from_stereotype(
    input_text: str,
    stereotype_context: Optional[Any],
    spm_resonance: Dict[str, float],
    named_patterns: List[Dict[str, Any]],
) -> List[ExperienceCandidate]:
    """
    从刻板印象树和 SPM 共鸣构建候选解释。

    候选来源：
    1. 刻板印象树的 active_tags（高层先验）
    2. SPM 共鸣最强的符号（内部状态匹配）
    3. 已命名的内部符号（经验关联）

    每个候选的 confidence 来源：
    - 刻板印象节点置信度（来自 stereotype_context.confidence）
    - SPM 符号的 hit_count 归一化（作为经验深度代理）

    返回：ExperienceCandidate 列表
    """
    candidates: List[ExperienceCandidate] = []

    # ---- 来源 1: 刻板印象 active_tags ----
    if stereotype_context:
        tags = getattr(stereotype_context, "active_tags", []) or []
        depth = getattr(stereotype_context, "depth", 0)
        tag_confidence = getattr(stereotype_context, "confidence", BASE_EXPERIENCE_CONFIDENCE)

        for tag in tags[:4]:
            # 深度越深 → 置信度越高（个体层比类别层更精准）
            depth_bonus = min(0.2, depth * 0.05)
            candidates.append(ExperienceCandidate(
                interpretation=f"刻板印象[{tag}]视角：{input_text}",
                source_id=f"stereotype:{tag}",
                experience_id=f"st_{tag}",
                confidence=min(1.0, tag_confidence + depth_bonus),
                emotion_mod=0.5,
                conversion=1.0,
            ))

    # ---- 来源 2: SPM 共鸣符号 ----
    for symbol, resonance in spm_resonance.items():
        # 共鸣强度作为经验强度代理
        candidates.append(ExperienceCandidate(
            interpretation=f"内部共鸣'{symbol}'触发",
            source_id="spm_resonance",
            experience_id=f"spm_{symbol}",
            confidence=min(1.0, resonance * 0.8),
            emotion_mod=resonance,
            conversion=1.0,
        ))

    # ---- 来源 3: 已命名内部符号 ----
    for pattern in named_patterns:
        symbol = pattern.get("symbol", "")
        named_as = pattern.get("named_as", "")
        center = pattern.get("center", {})
        hit_count = pattern.get("hit_count", 1)

        if not symbol:
            continue

        # hit_count 归一化作为经验深度
        experience_depth = min(1.0, hit_count / 20.0)

        candidates.append(ExperienceCandidate(
            interpretation=f"经验'{named_as or symbol}'匹配",
            source_id="spm_named",
            experience_id=f"named_{symbol}",
            confidence=experience_depth * BASE_EXPERIENCE_CONFIDENCE,
            emotion_mod=0.5,
            conversion=1.0,
        ))

    # 去重（相同 experience_id 只保留最高置信度）
    seen: Dict[str, ExperienceCandidate] = {}
    for c in candidates:
        if c.experience_id not in seen or c.confidence > seen[c.experience_id].confidence:
            seen[c.experience_id] = c

    result = list(seen.values())
    result.sort(key=lambda c: c.confidence, reverse=True)
    return result[:MAX_CANDIDATES]


# ============================================================================
# 竞争主函数
# ============================================================================

def run_interpretation_competition(
    input_text: str,
    state_snapshot: Dict[str, float],
    stereotype_context: Optional[Any] = None,
    spm_resonance: Optional[Dict[str, float]] = None,
    spm_data: Optional[Dict[str, Any]] = None,
) -> CompetitionResult:
    """
    执行解释竞争。

    参数：
        input_text        : 原始输入文本
        state_snapshot    : 当前状态快照（用于情绪调制）
        stereotype_context: 刻板印象上下文（可选）
        spm_resonance     : SPM 共鸣信号（来自 s02b）
        spm_data          : SPM 完整数据（用于提取 named_patterns）

    返回：CompetitionResult
    """
    resonance = spm_resonance or {}
    patterns = spm_data.get("patterns", []) if spm_data else []
    named_patterns = [p for p in patterns if p.get("symbol")]

    # ---- 构建候选 ----
    candidates = build_candidates_from_stereotype(
        input_text=input_text,
        stereotype_context=stereotype_context,
        spm_resonance=resonance,
        named_patterns=named_patterns,
    )

    if not candidates:
        return CompetitionResult(
            winner=None,
            tension_level=0.0,
            tension_type="none",
            candidates=[],
            top_scores=(0.0, 0.0),
        )

    # ---- 计算每个候选的竞争力 ----
    for c in candidates:
        c.competitive_score = compute_competitive_score(c, state_snapshot)

    # ---- 排序 ----
    candidates.sort(key=lambda c: c.competitive_score, reverse=True)

    top_scores = (
        candidates[0].competitive_score,
        candidates[1].competitive_score if len(candidates) > 1 else 0.0,
    )

    # ---- 张力计算 ----
    s1, s2 = top_scores

    if s1 < COMPETITION_EPS:
        return CompetitionResult(
            winner=None,
            tension_level=0.0,
            tension_type="none",
            candidates=candidates,
            top_scores=top_scores,
        )

    ratio = s1 / max(s2, COMPETITION_EPS)

    # 张力水平：top1/top2 越接近，张力越高
    # ratio = 1.0 → 张力 = 1.0（完全悬置）
    # ratio → ∞  → 张力 → 0.0（单一 attractor）
    tension_level = max(0.0, 1.0 - math.log(ratio) / math.log(TENSION_THRESHOLD))
    tension_level = max(0.0, min(1.0, tension_level))

    # ---- 胜出判断 ----
    # 用 softmax 权重判断是否有明确胜者
    scores = [c.competitive_score for c in candidates]
    weights = _softmax_weights(scores, temperature=0.3)
    winner_weight = weights[0]

    # winner_weight > 0.5 → 有明确胜者
    attractor_w = max(0.0, winner_weight - 0.3) / 0.7  # 归一化到 [0,1]
    suspended_w = 1.0 - attractor_w

    # ---- 张力类型（连续）----
    # tension_level ∈ [0,1], attractor_w ∈ [0,1]
    # 当 tension_level 高且 attractor_w 低 → suspended
    # 当 tension_level 低或 attractor_w 高 → attractor
    suspended_score = tension_level * (1.0 - attractor_w)
    attractor_score = (1.0 - tension_level) * attractor_w + 0.5 * (1.0 - tension_level) * (1.0 - attractor_w)
    tension_type = "suspended" if suspended_score > attractor_score else "attractor"

    winner = candidates[0] if attractor_score > suspended_score else None

    result = CompetitionResult(
        winner=winner,
        tension_level=tension_level,
        tension_type=tension_type,
        candidates=candidates,
        top_scores=top_scores,
    )

    return result


# ============================================================================
# 管线集成入口
# ============================================================================

def run_interpretation_stage(ctx, entity) -> None:
    """
    Pipeline stage: 解释竞争。

    在 ctx 中读取：
        ctx.raw_input
        ctx.state_snapshot
        ctx._stereotype_context
        ctx._spm_resonance

    写入 ctx：
        ctx._interpretation_result : CompetitionResult
        ctx._tension_level         : float
    """
    input_text = str(ctx.raw_input or "")
    state_snapshot = ctx.state_snapshot or {}
    stereotype_context = getattr(ctx, "_stereotype_context", None)
    spm_resonance = getattr(ctx, "_spm_resonance", None)
    spm_data = getattr(entity, "_state_pattern_data", {})

    result = run_interpretation_competition(
        input_text=input_text,
        state_snapshot=state_snapshot,
        stereotype_context=stereotype_context,
        spm_resonance=spm_resonance,
        spm_data=spm_data,
    )

    ctx._interpretation_result = result
    ctx._tension_level = (result.tension_level if result else 0.0)

    # 写回 entity（供后续语言阶段使用）
    entity._last_interpretation_result = result
    entity._last_tension_level = (result.tension_level if result else 0.0)


# ============================================================================
# 前语言扰动：drive激活 → 内部符号共鸣 → 直接张力（不经过解释竞争）
# 理解机制纲领第七节：语言前扰动链路
# ============================================================================

def compute_prelinguistic_tension(
    spm_resonance: Optional[Dict[str, float]],
    activated_drive: Optional[Dict[str, float]],
) -> tuple[float, str]:
    """
    从 drive 激活模式与 SPM 共鸣结果直接计算前语言张力。

    这是"语言前扰动"的核心实现：
        drive激活 → 内部符号共鸣 → 直接产生张力 → 渗透语言输出

    与解释竞争产生的张力不同，这里的张力来自：
        1. 共鸣分布的均衡程度（多个符号同时激活 → 悬置）
        2. 激活 drive 与已有符号的偏离程度（新体验 → 陌生感张力）

    参数：
        spm_resonance  : ctx._spm_resonance，{symbol_name: resonance_score}
        activated_drive: 当前 drive 激活向量，{dim: value}

    返回：(tension_level, tension_type)
        tension_level : [0, 1] 张力量
        tension_type  : "resonance_dispersion" | "novelty_tension" | "none"
    """
    if not spm_resonance:
        return 0.0, "none"

    resonance_values = list(spm_resonance.values())
    active_values = [v for v in resonance_values if v > 0.01]

    if len(active_values) < 1:
        return 0.0, "none"

    # ---- 子机制 1：共鸣分散度 → 张力悬置 ----
    # 多个符号同时被激活（分散度高）→ 经验之间互相拉扯 → 悬置张力
    # 用归一化标准差衡量分散度：[0, 1]
    n = len(active_values)
    if n == 1:
        dispersion = 0.0
    else:
        mean = sum(active_values) / n
        variance = sum((v - mean) ** 2 for v in active_values) / n
        std = variance ** 0.5
        # 归一化到 [0, 1]：mean=0.5 附近时 std 最大（~0.5），作为归一化基准
        dispersion = min(1.0, std / 0.25)

    # ---- 子机制 2：drive 陌生度 → 新体验张力 ----
    # 如果激活的 drive 与 SPM 已有质心距离远 → 新体验 → 理解尚未完成 → 张力
    novelty = 0.0
    if activated_drive and active_values:
        # 用激活 drive 与共鸣最高的符号的质心做距离度量
        best_symbol = max(spm_resonance, key=spm_resonance.get)
        # 提取最佳符号的 drive 质心（需要从 entity._state_pattern_data 读取）
        # 这里用共鸣分数的补作为"偏离"代理：低相似度 = 高陌生度
        best_resonance = spm_resonance.get(best_symbol, 0.0)
        novelty = 1.0 - best_resonance

    # ---- 合成张力 ----
    # 分散度主导悬置，陌生度主导新体验张力
    tension_dispersion = dispersion * 0.6
    tension_novelty = novelty * 0.4
    tension = tension_dispersion + tension_novelty
    tension = min(1.0, max(0.0, tension))

    if tension < 0.05:
        return 0.0, "none"

    if dispersion > novelty:
        return tension, "resonance_dispersion"
    else:
        return tension, "novelty_tension"


def apply_prelinguistic_tension(
    scored_candidates: List[tuple],
    tension_level: float,
    tension_type: str,
) -> List[tuple]:
    """
    将前语言张力注入候选词评分。

    resonance_dispersion（悬置张力）：
        - 犹豫标记词加分
        - 短句加分（碎片化适合悬置状态）

    novelty_tension（新体验张力）：
        - 探索性词汇加分（"不知道""也许""试试"）
        - 确定性表达降权
    """
    if tension_level < 0.05 or tension_type == "none":
        return scored_candidates

    HESITATION_MARKERS = frozenset({
        "……", "嗯", "啊", "呢", "吧",
        "也许", "好像", "大概", "可能", "不知道",
        "似乎", "或许", "说不上来",
    })
    EXPLORATION_MARKERS = frozenset({
        "不知道", "也许", "试试", "不清楚", "可能吧",
        "嗯……", "我说不上来", "好像是这样",
    })
    CERTAINTY_MARKERS = frozenset({
        "一定", "肯定", "必须", "绝对", "毫无疑问",
        "就是", "当然", "明显", "显然",
    })

    adjusted: List[tuple] = []
    for word, score in scored_candidates:
        bonus = 0.0

        if tension_type == "resonance_dispersion":
            if any(m in word for m in HESITATION_MARKERS):
                bonus += tension_level * 0.12
            if any(m in word for m in CERTAINTY_MARKERS):
                bonus -= tension_level * 0.08
            if len(word) <= 3:
                bonus += tension_level * 0.04

        elif tension_type == "novelty_tension":
            if any(m in word for m in EXPLORATION_MARKERS):
                bonus += tension_level * 0.15
            if any(m in word for m in CERTAINTY_MARKERS):
                bonus -= tension_level * 0.12

        new_score = max(0.0, min(1.0, score + bonus))
        adjusted.append((word, new_score))

    return adjusted


# ============================================================================
# 张力注入语言系统（解释竞争来源）
# ============================================================================

def apply_tension_to_candidates(
    scored_candidates: List[tuple],
    tension_level: float,
    tension_type: str,
) -> List[tuple]:
    """
    将解释张力注入候选词评分。

    当 tension_type == "suspended"（张力悬置）时：
        - 模糊性/犹豫表达加分（"……" "也许" "好像" "不知道" "嗯"）
        - 高确定性表达降权（"一定" "肯定" "必须"）
        - 短句权重上升（张力状态下不需要完整论证）

    当 tension_type == "attractor"（单一吸引子）时：
        - 不做特殊调制，让正常的语义评分主导

    参数：
        scored_candidates: [(词, score), ...] 列表
        tension_level    : [0, 1] 张力量
        tension_type     : "suspended" | "attractor" | "none"

    返回：调整后的 [(词, 新score), ...]
    """
    if tension_type != "suspended" or tension_level < 0.05:
        return scored_candidates

    # 模糊/犹豫标记词
    HESITATION_MARKERS = frozenset({
        "……", "嗯", "啊", "呢", "吧",
        "也许", "好像", "大概", "可能", "不知道",
        "好像", "似乎", "或许", "说不上来",
    })
    # 高确定性词（张力悬置时应降权）
    CERTAINTY_MARKERS = frozenset({
        "一定", "肯定", "必须", "绝对", "毫无疑问",
        "就是", "当然", "明显", "显然",
    })

    adjusted: List[tuple] = []
    for word, score in scored_candidates:
        w = word
        bonus = 0.0

        # 犹豫词加分（与张力水平成比例）
        if any(m in w for m in HESITATION_MARKERS):
            bonus += tension_level * 0.15

        # 确定性词降权
        if any(m in w for m in CERTAINTY_MARKERS):
            bonus -= tension_level * 0.10

        # 短句加分（张力状态适合碎片化表达）
        if len(w) <= 3:
            bonus += tension_level * 0.05

        # 长句降权（张力状态不宜长篇论述）
        if len(w) >= 10:
            bonus -= tension_level * 0.08

        new_score = max(0.0, min(1.0, score + bonus))
        adjusted.append((word, new_score))

    return adjusted
