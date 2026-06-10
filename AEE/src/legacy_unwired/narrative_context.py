"""Context construction for narrative fragments."""

from __future__ import annotations

import math
import random
from typing import Any, Dict, List
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

def _build_context(entity: Any) -> Dict[str, Any]:
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
        "loneliness": float(state.get("loneliness", 0.3)),
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
        # 元觉察（体感自我觉察——从 somatic_self_awareness 注入）
        "awareness_intensity": 0.0,
        "dominant_feeling": "",
        "second_feeling": "",
        "past_feeling": "",
    }

    # ---- 体感自我觉察注入 ----
    try:
        from .somatic_self_awareness import SomaticSelfAwareness
        _aw = SomaticSelfAwareness()
        _sa_snap = _aw.observe(state, entity)
        ctx["awareness_intensity"] = _sa_snap.awareness_intensity
        if _sa_snap.top_descriptions:
            ctx["dominant_feeling"] = _sa_snap.top_descriptions[0]
            ctx["second_feeling"] = _sa_snap.top_descriptions[1] if len(_sa_snap.top_descriptions) > 1 else ""
    except Exception:
        pass

    # ---- 过去体感觉察（从历史快照中提取）----
    try:
        _history = getattr(entity, "_state_pattern_data", {}).get("patterns", [])
        if not _history and snapshots:
            _history = snapshots[-5:]
        if _history:
            _past_snap = _history[-1] if isinstance(_history[-1], dict) else {}
            _past_feeling_dims = ["loneliness", "fatigue", "somatic_tone", "boredom"]
            _best_past = 0.0
            _past_desc = ""
            for _dim in _past_feeling_dims:
                _pv = float(_past_snap.get(_dim, 0.5)) if _past_snap else 0.5
                _neutral = 0.3 if _dim == "loneliness" else 0.1
                _dev = abs(_pv - _neutral)
                if _dev > _best_past:
                    _best_past = _dev
                    _past_desc_map = {"loneliness": "孤独", "fatigue": "累",
                                      "somatic_tone": "难受", "boredom": "无聊"}
                    _past_desc = _past_desc_map.get(_dim, "")
            ctx["past_feeling"] = _past_desc
    except Exception:
        pass

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
