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


# ============================================================================
# 数据表（纯查表，不做决策）
# ============================================================================

_ACTION_VERBS: Dict[str, List[str]] = {
    "explore": ["看了点东西", "搜了一下", "翻了翻"],
    "seek":    ["找人聊了一下", "问了一下", "想找人说说"],
    "repair":  ["修了一下", "弄了弄", "调了调"],
    "write":   ["写了点东西", "记了一下"],
    "comfort": ["休息了一会", "缓了缓"],
    "rest":    ["歇了一下", "躺了会"],
    "voice":   ["说了句话", "嘟囔了一下"],
    "avoid":   ["躲了一下", "退开了"],
    "idle":    ["发了会呆", "什么都没做"],
}

# 行动叙事价值（连续权重，不是开关）
_ACTION_SALIENCE: Dict[str, float] = {
    "explore": 0.8, "seek": 0.7, "repair": 0.6, "write": 0.5,
    "voice": 0.3, "comfort": 0.2, "rest": 0.1, "avoid": 0.3, "idle": 0.0,
}

# 维度趋势描述词：(值上升时的词, 值下降时的词)
_DIM_WORDS: Dict[str, tuple] = {
    "fatigue":      ("累",      "不那么累"),
    "loneliness":   ("孤独",    "没那么孤独"),
    "energy":       ("有精神",  "没什么劲"),
    "stress":       ("紧张",    "放松了点"),
    "anxiety":      ("焦虑",    "没那么焦虑"),
    "curiosity":    ("好奇",    "没什么兴趣"),
    "boredom":      ("无聊",    "没那么无聊"),
    "joy":          ("开心",    "不太开心"),
    "sadness":      ("难过",    "好了点"),
    "somatic_tone": ("舒服",    "难受"),
}

# 负向维度集合（值上升 = 状态变差）
_NEG_DIMS = {"fatigue", "loneliness", "stress", "anxiety", "boredom", "sadness"}


# ============================================================================
# 叙事模板池（全部在同一个 softmax 里竞争）
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

def _build_context(entity: Any) -> Dict[str, Any]:
    """
    从 entity 状态和 snapshots 预计算叙事上下文。

    所有值都是连续 float 或预解析的 str。
    不做任何决策——决策交给 softmax。
    """
    snapshots = getattr(entity, "snapshots", [])
    current_tick = getattr(entity, "tick", 0)
    state = entity.to_state_snapshot() if hasattr(entity, "to_state_snapshot") else {}

    # 体感表达词（从语言系统学到的候选词，包括阅读词）
    _feeling = str(getattr(entity, "_language_best_candidate", "") or "")
    _feeling_score = float(getattr(entity, "_language_best_score", 0.0))
    # 过短的词不适合单独做叙事——用连续衰减替代 if 判断（单字锚点走 anchor 路径）
    _feeling_score *= math.exp(-max(0.0, 3 - len(_feeling)))

    # 阅读词体感验证：锚点密度太低的词不得竞争 feeling 槽
    # "可能在瞬间烧穿舰体"（锚点0）→ 直接排除
    # "心里软软的"（锚点2/5=0.4）→ 通过
    try:
        from .somatic_concept_map import SOMATIC_ANCHORS
        _all_anchors = set(SOMATIC_ANCHORS.keys())
    except Exception:
        _all_anchors = frozenset()

    # 阅读词作为感受候选（连续 argmax 竞争）
    _taste_log = getattr(entity, "_reading_taste_log", [])
    for _entry in _taste_log[-3:]:
        _entry_tick = _entry.get("tick", 0)
        _entry_recency = math.exp(-(current_tick - _entry_tick) * 0.15)
        for _rw in _entry.get("words", []):
            # 体感验证：锚点密度门槛
            _rw_anchors = sum(1 for c in set(_rw) if c in _all_anchors)
            _rw_density = _rw_anchors / max(1, len(_rw))
            _density_gate = 1.0 - math.exp(-3.0 * _rw_density)  # 密度0→0，密度0.3→0.60，密度0.5→0.78
            if _density_gate < 0.3:
                continue  # 密度过低（≤1锚点/9字），直接跳过
            _rw_len_factor = math.exp(-max(0.0, 3 - len(_rw)))
            _rw_score = 0.45 * _density_gate * _rw_len_factor * _entry_recency
            if _rw_score > _feeling_score:
                _feeling = _rw
                _feeling_score = _rw_score

    ctx: Dict[str, Any] = {
        # 当前状态（沉默模板用）
        "approach":  float(state.get("approach_drive", 0.0)),
        "curiosity": float(state.get("curiosity", 0.5)),
        "fatigue":   float(state.get("fatigue", 0.1)),
        # 行动相关（默认：无行动 → 模板自然低分）
        "recency":  0.0,
        "salience":  0.0,
        "verb":      "做了点什么",   # 兜底动词，实际很少用到
        "improve":   0.0,
        "worst":     "累",
        # 轨迹相关
        "delta":     0.0,
        "trend_desc": "",
        # 体感表达（阅读/训练学到的词）
        "feeling":       _feeling if _feeling_score > 0.0 else "",
        "feeling_score": _feeling_score,
    }

    # ---- 最显著的近期行动（argmax: recency × salience）----
    best_score = 0.0
    for snap in snapshots:
        tick_dist = current_tick - snap.get("snap_index", current_tick)
        recency = math.exp(-tick_dist * 0.3)   # 指数衰减
        action_type = snap.get("action_type", "idle")
        salience = _ACTION_SALIENCE.get(action_type, 0.0)
        score = recency * salience

        # argmax（连续比较，不是门控）
        if score > best_score:
            best_score = score
            ctx["recency"] = recency
            ctx["salience"] = salience
            verbs = _ACTION_VERBS.get(action_type, [])
            ctx["verb"] = random.choice(verbs) if verbs else ctx["verb"]

            # 因果：pre/post 对比
            pre = snap.get("pre_state", {})
            post = snap.get("post_state", {})
            tone_d = float(post.get("somatic_tone", 0)) - float(pre.get("somatic_tone", 0))
            stress_d = float(pre.get("stress", 0)) - float(post.get("stress", 0))
            ctx["improve"] = tone_d + stress_d

            # 最差恶化维度（argmax 取绝对增幅最大的负向维度）
            worst_val, worst_word = 0.0, "累"
            for dim in _NEG_DIMS:
                d = float(post.get(dim, 0)) - float(pre.get(dim, 0))
                w = max(0.0, d)  # 只看增幅
                # argmax
                if w > worst_val:
                    worst_val = w
                    worst_word = _DIM_WORDS.get(dim, ("累", ""))[0]
            ctx["worst"] = worst_word

    # ---- 状态轨迹（当前 vs 最近 snapshot 的 post_state）----
    past_states = [s.get("post_state", s.get("pre_state", {})) for s in snapshots[-3:]]
    if past_states:
        past = past_states[-1]
        best_abs = 0.0
        best_dim = ""
        best_signed = 0.0
        for dim in _DIM_WORDS:
            cur_val = float(state.get(dim, 0.5))
            past_val = float(past.get(dim, 0.5))
            signed = cur_val - past_val
            if abs(signed) > best_abs:
                best_abs = abs(signed)
                best_dim = dim
                best_signed = signed
        ctx["delta"] = best_signed
        # 趋势描述词：值上升取 [0]，值下降取 [1]
        # 用 (1+sign)/2 做连续 0/1 选择器
        if best_dim:
            up_w, dn_w = _DIM_WORDS[best_dim]
            selector = 0.5 * (1.0 + math.copysign(1.0, best_signed + 1e-9))
            # selector ≈ 1.0 when positive, ≈ 0.0 when negative
            # 但字符串无法插值，这里用离散选择
            ctx["trend_desc"] = up_w if selector > 0.5 else dn_w

    return ctx


# ============================================================================
# 公开接口
# ============================================================================

def try_narrative_expression(entity: Any, social_input: float = 0.0) -> Optional[str]:
    """
    尝试从近期经历生成叙事表达。

    所有叙事模板（含沉默）在同一个 softmax 里竞争。
    大多数 tick 沉默赢（返回 None），锚点表达仍是主力。
    只有近期有显著行动且状态有利时，叙事才会赢过沉默。

    social_input: 0.0~1.0，有人在说话时 > 0，沉默模板获得加分。
    返回：叙事字符串，或 None（沉默赢了）。
    """
    ctx = _build_context(entity)
    ctx["social_input"] = max(0.0, min(1.0, float(social_input)))

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
