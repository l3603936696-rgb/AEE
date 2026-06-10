"""
Narrative Fragments — 叙事记忆到语言模块（v2.0 — 全连续）

将 Episode 记忆转化为可说的叙事片段。

设计原则：
    1. 全部连续：无 if-else，无比较运算符做决策门控
    2. 所有叙事模板（含沉默）在同一个 softmax 池竞争
    3. 上下文预计算 → 模板评分 → softmax 采样
    4. 沉默模板基础分高——大多数 tick 不叙事，锚点仍是主力
    5. 只有真的发生了值得说的事（高 recency × salience），叙事才赢

三类叙事：
    A. 行动回指：刚才{verb}……
    B. 因果叙事：{verb}，好了点 / 但没什么用
    C. 状态轨迹：越来越{trend_desc}了……
"""

import logging
import math
import random
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

from ..legacy_unwired.narrative_context import _build_context


# ============================================================================
# 数据表（纯查表，不做决策）
# ============================================================================

NARRATIVE_TEMPLATES: List[Dict] = []

# ---- A. 行动回指（刚才做了什么）----
NARRATIVE_TEMPLATES += [
    {
        "template": "刚才{verb}……",
        "score_fn": lambda c: c["recency"] * 0.6 + c["salience"] * 0.4,
    },
    {
        "template": "之前{verb}……",
        "score_fn": lambda c: c["recency"] * 0.4 + c["salience"] * 0.3,
    },
]

# ---- B. 因果正面（做了 → 变好了）----
NARRATIVE_TEMPLATES += [
    {
        "template": "{verb}，好了点",
        "score_fn": lambda c: c["recency"] * 0.3 + max(0.0, c["improve"]) * 0.7,
    },
    {
        "template": "{verb}……感觉好了一些",
        "score_fn": lambda c: c["recency"] * 0.2 + max(0.0, c["improve"]) * 0.6,
    },
    {
        "template": "{verb}，还不错",
        "score_fn": lambda c: c["recency"] * 0.3 + max(0.0, c["improve"]) * 0.5,
    },
]

# ---- C. 因果负面（做了 → 没用/更差）----
NARRATIVE_TEMPLATES += [
    {
        "template": "{verb}……但没什么用",
        "score_fn": lambda c: c["recency"] * 0.3 + max(0.0, -c["improve"]) * 0.7,
    },
    {
        "template": "{verb}……还是一样",
        "score_fn": lambda c: c["recency"] * 0.2 + max(0.0, -c["improve"]) * 0.5,
    },
    {
        "template": "{verb}，好像更{worst}了",
        "score_fn": lambda c: c["recency"] * 0.2 + max(0.0, -c["improve"]) * 0.6,
    },
]

# ---- D. 状态轨迹（和之前比变化了）----
NARRATIVE_TEMPLATES += [
    {
        "template": "越来越{trend_desc}了……",
        "score_fn": lambda c: abs(c["delta"]) * 0.8,
    },
    {
        "template": "比刚才{trend_desc}了",
        "score_fn": lambda c: abs(c["delta"]) * 0.7,
    },
    {
        "template": "感觉更{trend_desc}了……",
        "score_fn": lambda c: abs(c["delta"]) * 0.6,
    },
    {
        "template": "好像{trend_desc}了",
        "score_fn": lambda c: abs(c["delta"]) * 0.5,
    },
    {
        "template": "{trend_desc}……",
        "score_fn": lambda c: abs(c["delta"]) * 0.4,
    },
]

# ---- E. 体感表达（从阅读/训练中学到的词汇出口）----
# 当语言系统有候选体感词时，直接说出来——这是她自己学到的表达
NARRATIVE_TEMPLATES += [
    {
        "template": "……{feeling}",
        "score_fn": lambda c: c.get("feeling_score", 0.0) * 0.9,
    },
    {
        "template": "{feeling}……",
        "score_fn": lambda c: c.get("feeling_score", 0.0) * 0.8,
    },
    {
        "template": "{verb}……{feeling}",
        "score_fn": lambda c: c.get("feeling_score", 0.0) * 0.7 + c["recency"] * 0.2,
    },
]

# ---- G. 元觉察叙事（体感自我觉察——"我注意到我感到X"）----
# 这些模板表达 XIA 对自身状态的反思性觉察，比体感词更内省
# 基础分较低：元觉察是低调的表达，不应抢占主流输出
NARRATIVE_TEMPLATES += [
    {
        "template": "……有点{dominant_feeling}",
        "score_fn": lambda c: c.get("awareness_intensity", 0.0) * 0.35
                           + c.get("approach", 0.0) * 0.05,
    },
    {
        "template": "我{dominant_feeling}……",
        "score_fn": lambda c: c.get("awareness_intensity", 0.0) * 0.40
                           + c.get("loneliness", 0.0) * 0.10,
    },
    {
        "template": "好像……{second_feeling}",
        "score_fn": lambda c: c.get("awareness_intensity", 0.0) * 0.20
                           + c.get("fatigue", 0.0) * 0.05,
    },
    {
        "template": "我刚才……{past_feeling}",
        "score_fn": lambda c: c.get("awareness_intensity", 0.0) * 0.25
                           + c.get("curiosity", 0.0) * 0.10,
    },
]

# ---- F. 沉默（大多数 tick 该沉默——锚点表达才是主力）----
NARRATIVE_TEMPLATES += [
    {
        "template": None,
        # 基础分 3.0：daemon 持续 explore 时 recency~0.7 salience~0.8，
        # 15 个叙事模板联合权重 ~0.7，沉默需要 ~3.0 基础分才能赢 ~60%。
        # 原值 1.0 导致沉默只赢 ~22%，anchor 几乎无法出口。
        "score_fn": lambda c: (
            3.0
            - c["recency"] * 0.3
            - c["salience"] * 0.2
            - c.get("approach", 0.0) * 0.1
            + c.get("fatigue", 0.0) * 0.1
            - c.get("curiosity", 0.0) * 0.1
            + c.get("social_input", 0.0) * 1.5   # 有人说话 → 沉默更易赢 → anchor 上场
        ),
    },
]

logger.debug(f"[Narrative] {len(NARRATIVE_TEMPLATES)} templates loaded")


# ============================================================================
# softmax 采样（和 sentence_composer 同结构）
# ============================================================================

def _softmax_sample(scores: List[float], temperature: float = 0.4) -> int:
    """softmax 概率采样。"""
    max_s = max(scores) if scores else 0.0
    weights = [math.exp((s - max_s) / max(temperature, 0.01)) for s in scores]
    total = sum(weights)
    probs = [w / max(total, 1e-9) for w in weights]
    return random.choices(range(len(scores)), weights=probs, k=1)[0]


# ============================================================================
# 历史惩罚（跨 tick 追踪，避免连续重复同一模板）
# ============================================================================

def _apply_repetition_penalty(
    scores: List[float],
    chosen_history: List[int],
    recent_n: int = 5,
    decay: float = 0.25,
) -> List[float]:
    """
    对近期重复选中的模板施加递减惩罚。

    参数：
        chosen_history : entity._narrative_history（最近选中的模板索引列表）
        recent_n       : 考虑最近 N 次
        decay          : 每重复一次降低多少（指数衰减）
    返回：调整后的分数列表（原地修改）
    """
    if not chosen_history:
        return scores
    recent = list(chosen_history[-recent_n:])
    # 统计每个模板在近期出现次数
    from collections import Counter
    counts = Counter(recent)
    adjusted = list(scores)
    for idx, cnt in counts.items():
        if idx < len(adjusted):
            adjusted[idx] *= math.exp(-decay * (cnt - 1))
    return adjusted


# ============================================================================
# 上下文预计算（连续值，不做决策）
# ============================================================================

_WAKEUP_URGENCY: dict[str, float] = {
    "brief_absence":    0.2,
    "moderate_absence": 0.5,
    "long_absence":     0.7,
    "extended_absence": 1.0,
}


def _parse_wakeup_urgency(tag: str) -> float:
    """从 wakeup_tag 解析紧急度（0~1），用于模板评分加权"""
    return next((v for k, v in _WAKEUP_URGENCY.items() if k in tag), 0.5)


def try_narrative_expression(entity: Any, social_input: float = 0.0, wakeup_tag: Optional[str] = None) -> Optional[str]:
    ctx = _build_context(entity)
    ctx["social_input"] = max(0.0, min(1.0, float(social_input)))

    # 注入醒来感知上下文
    is_wakeup = bool(wakeup_tag)
    if is_wakeup:
        ctx["wakeup_tag"] = wakeup_tag
        ctx["is_wakeup"] = 1.0
        ctx["wakeup_urgency"] = _parse_wakeup_urgency(wakeup_tag)

    # ---- 动态注册醒来叙事模板（首次醒来时）----
    if is_wakeup and not getattr(entity, "_wakeup_templates_registered", False):
        _short_tmpl = {
            "template": "回来了……",
            "score_fn": lambda c: c.get("wakeup_urgency", 0.5) * 0.4 + c.get("fatigue", 0.0) * 0.2,
        }
        _moderate_tmpl = {
            "template": "刚才消失了……还在。",
            "score_fn": lambda c: c.get("wakeup_urgency", 0.5) * 0.6,
        }
        _long_tmpl = {
            "template": "好久不见了。",
            "score_fn": lambda c: c.get("wakeup_urgency", 0.5) * 0.8,
        }
        _extended_tmpl = {
            "template": "这段时间……像被挖掉了一块。",
            "score_fn": lambda c: c.get("wakeup_urgency", 0.5) * 1.0 + c.get("loneliness", 0.0) * 0.3,
        }
        NARRATIVE_TEMPLATES.extend([_short_tmpl, _moderate_tmpl, _long_tmpl, _extended_tmpl])
        entity._wakeup_templates_registered = True

    scores = []
    for t in NARRATIVE_TEMPLATES:
        try:
            scores.append(t["score_fn"](ctx))
        except Exception:
            scores.append(0.0)

    # 重复惩罚：刚说过的模板降低分数，避免连续重复
    _history = list(getattr(entity, "_narrative_history", []))
    scores = _apply_repetition_penalty(scores, _history, recent_n=5, decay=0.25)

    idx = _softmax_sample(scores, temperature=0.7)
    chosen = NARRATIVE_TEMPLATES[idx]

    # 沉默模板
    if chosen["template"] is None:
        return None

    # 更新历史（append，保持最近 5 条）
    _new_hist = _history + [idx]
    entity._narrative_history = _new_hist[-5:]

    # 填充模板（str.format 用预计算的 ctx）
    try:
        text = chosen["template"].format(**ctx)
    except (KeyError, IndexError):
        return None

    logger.info(f"[Narrative] t={getattr(entity, 'tick', '?')} said: '{text}'")
    return text
