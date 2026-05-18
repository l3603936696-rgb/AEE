"""
Associative Recall — 驱动力触发的联想回忆（v1.0 — 全连续）

核心原理：
    回忆比探索便宜。info_gap 高的时候，先查记忆里有没有
    上次类似状态下探索过的结果。有就用，省掉 LLM 调用。

    不需要"设计"联想动机——回忆零成本，探索花 token，
    优化压力自然让她先走便宜路径。

衰减机制（防止只会回忆）：
    - 重复衰减：同一条 episode 被回忆 n 次，收益 × 1/(1+n)
    - 时效衰减：episode 越老，收益 × exp(-age/τ)
    两个衰减一乘，回忆的性价比持续下滑，最终探索更划算。

设计原则：
    1. 全连续：回忆和探索在同一个连续评分空间竞争
    2. 无 if-else 门控：衰减函数自然归零
    3. 纯函数，不写文件
"""

import logging
import math
import random
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# 中文短语提取（复用 reading_acquisition 的正则）
_PHRASE_RE = re.compile(r"[一-鿿]{2,8}")

# 指称表达停词
_STOP = frozenset({
    "什么", "这个", "那个", "可以", "不是", "就是", "因为", "所以",
    "但是", "而且", "或者", "如果", "已经", "没有", "他们", "我们",
    "搜索", "结果", "相关", "内容", "信息", "问题", "回答", "输出",
})

# 衰减参数
_FRESHNESS_TAU = 120.0   # 时效半衰期（tick 数）
_REPEAT_DECAY_RATE = 1.0 # 重复衰减速率

# 驱动力维度（用于状态相似度计算）
_DRIVE_DIMS = [
    "curiosity", "info_gap", "loneliness", "fatigue", "stress",
    "anxiety", "boredom", "approach_drive", "avoid_drive",
    "unresolved", "energy", "somatic_tone",
]

# 行动类型 → 回忆相关的驱动力维度（哪些驱动力触发了这类行动）
_ACTION_DRIVE_WEIGHTS: Dict[str, Dict[str, float]] = {
    "explore": {"curiosity": 0.4, "info_gap": 0.4, "boredom": 0.2},
    "seek":    {"loneliness": 0.5, "approach_drive": 0.3, "unresolved": 0.2},
    "repair":  {"unresolved": 0.5, "stress": 0.3, "anxiety": 0.2},
    "write":   {"unresolved": 0.4, "curiosity": 0.3, "approach_drive": 0.3},
}


# ============================================================================
# 指称表达模板（softmax 竞争）
# ============================================================================

RECALL_TEMPLATES: List[Dict] = [
    {
        "template": "上次{topic}的时候……",
        "score_fn": lambda c: c["benefit"] * 0.7 + c["freshness"] * 0.3,
    },
    {
        "template": "之前看过{topic}……",
        "score_fn": lambda c: c["benefit"] * 0.6 + c["freshness"] * 0.2,
    },
    {
        "template": "记得{topic}……",
        "score_fn": lambda c: c["benefit"] * 0.5 + c["freshness"] * 0.4,
    },
    {
        "template": "那个{topic}……想再看看",
        "score_fn": lambda c: (
            c["benefit"] * 0.5
            + c.get("curiosity", 0.0) * 0.3
            + c["freshness"] * 0.2
        ),
    },
    {
        "template": "{topic}……之前好像看到过",
        "score_fn": lambda c: c["benefit"] * 0.4 + c["freshness"] * 0.3,
    },
    {
        "template": "想起来了……{topic}",
        "score_fn": lambda c: c["benefit"] * 0.6 + c["freshness"] * 0.2,
    },
    # 沉默：回忆不够好，应该去探索
    {
        "template": None,
        "score_fn": lambda c: (
            0.55
            - c["benefit"] * 0.6
            - c["freshness"] * 0.3
            + c.get("fatigue", 0.0) * -0.2  # 累的时候更愿意回忆（省力）
        ),
    },
]


def _softmax_sample(scores: List[float], temperature: float = 0.4) -> int:
    """softmax 采样。"""
    max_s = max(scores) if scores else 0.0
    weights = [math.exp((s - max_s) / max(temperature, 0.01)) for s in scores]
    total = sum(weights)
    probs = [w / max(total, 1e-9) for w in weights]
    return random.choices(range(len(scores)), weights=probs, k=1)[0]


# ============================================================================
# 核心：联想回忆尝试
# ============================================================================

def attempt_recall(
    entity: Any,
    action_type: str,
    drive_state: Dict[str, float],
) -> Optional[Dict[str, Any]]:
    """
    尝试用驱动力场从记忆中召回相关经历。

    回忆和探索在连续评分空间竞争。回忆便宜但收益衰减，
    探索贵但收益稳定。当回忆收益衰减到不如探索时，返回 None。

    参数：
        entity      : EntityState
        action_type : 涌现行为选出的行动类型（"explore"/"seek"/...）
        drive_state : 当前驱动力场

    返回：
        dict {"expression": str, "episode_id": int, "benefit": float}
        或 None（回忆不划算，应该走探索）
    """
    # 只对有记忆价值的行动类型做回忆
    drive_weights = _ACTION_DRIVE_WEIGHTS.get(action_type)
    if not drive_weights:
        return None

    # ---- 从 Episode DB 拉取候选 ----
    episodes = _get_candidate_episodes(action_type, limit=30)
    if not episodes:
        return None

    current_tick = getattr(entity, "tick", 0)
    recall_counts = getattr(entity, "_recall_counts", {})

    # ---- 对每条 episode 计算回忆收益（全连续）----
    scored: List[Tuple[Any, float, float, List[str]]] = []
    for ep in episodes:
        ep_state = ep.state_snapshot or {}
        ep_id = ep.iteration_id
        if ep_id is None:
            continue
        ep_tick = ep_id  # iteration_id ≈ tick

        # 1) 状态相似度：当前驱动力场 vs 当时的驱动力场
        similarity = _state_similarity(drive_state, ep_state, drive_weights)

        # 2) 驱动力缓解量：那次行动后，相关驱动力降了多少？
        #    从 episode 的 tags 或 importance 推断
        relief = ep.importance * 0.5  # importance 越高，当时的行动越有效

        # 3) 时效衰减
        age = max(0, current_tick - ep_tick)
        freshness = math.exp(-age / _FRESHNESS_TAU)

        # 4) 重复衰减
        n_recalled = recall_counts.get(ep_id, 0)
        repeat_factor = 1.0 / (1.0 + _REPEAT_DECAY_RATE * n_recalled)

        # 综合收益
        benefit = similarity * relief * freshness * repeat_factor

        # 提取内容关键词
        keywords = _extract_keywords(ep.output_text or "", max_kw=3)

        scored.append((ep, benefit, freshness, keywords))

    if not scored:
        return None

    # ---- 取收益最高的 episode ----
    scored.sort(key=lambda x: x[1], reverse=True)
    best_ep, best_benefit, best_freshness, best_keywords = scored[0]

    if not best_keywords:
        return None  # 没有可指称的内容

    # ---- 生成指称表达（softmax 竞争，含沉默）----
    topic = best_keywords[0]  # 最显著的关键词
    ctx = {
        "benefit": best_benefit,
        "freshness": best_freshness,
        "topic": topic,
        "curiosity": float(drive_state.get("curiosity", 0.5)),
        "fatigue": float(drive_state.get("fatigue", 0.1)),
    }

    scores = []
    for t in RECALL_TEMPLATES:
        try:
            scores.append(t["score_fn"](ctx))
        except Exception:
            scores.append(0.0)

    idx = _softmax_sample(scores, temperature=0.4)
    chosen = RECALL_TEMPLATES[idx]

    # 沉默赢了 → 回忆不划算，去探索
    if chosen["template"] is None:
        return None

    # 填充模板
    try:
        expression = chosen["template"].format(**ctx)
    except (KeyError, IndexError):
        return None

    # 更新回忆计数（调用方负责写回 entity）
    ep_id = best_ep.iteration_id
    new_counts = dict(recall_counts)
    new_counts[ep_id] = new_counts.get(ep_id, 0) + 1

    logger.info(
        f"[Recall] t={current_tick} recalled ep={ep_id} "
        f"benefit={best_benefit:.3f} topic='{topic}' "
        f"→ '{expression}'"
    )

    return {
        "expression": expression,
        "episode_id": ep_id,
        "benefit": best_benefit,
        "topic": topic,
        "recall_counts": new_counts,
    }


# ============================================================================
# 辅助函数
# ============================================================================

def _get_candidate_episodes(action_type: str, limit: int = 30) -> list:
    """从 Episode DB 获取候选（同类行动的历史 episode）。"""
    try:
        from ..memory_hub.episodes_db import get_recent_episodes
        all_eps = get_recent_episodes(limit=limit * 3, min_importance=0.2)
        # 筛选同类行动（排除回忆产出的 episode）
        result = []
        for ep in all_eps:
            ep_action = (ep.decision or {}).get("action_type", "")
            if ep_action != action_type:
                continue
            text = ep.output_text or ""
            if len(text) < 15:
                continue  # 太短，可能是回忆残留
            # 排除回忆自引用：output 主要是回忆模板元词
            if _is_recall_echo(text):
                continue
            result.append(ep)
            if len(result) >= limit:
                break
        return result
    except Exception as e:
        logger.debug(f"[Recall] Episode retrieval failed: {e}")
        return []


# 回忆模板中的元词——如果 output_text 主要由这些组成，说明是回忆自引用
_RECALL_META = frozenset({
    "上次", "之前", "记得", "想起来了", "那个", "好像看到过",
    "想再看看", "的时候",
})


def _is_recall_echo(text: str) -> bool:
    """检测 output_text 是否是回忆产出的自引用。"""
    # 如果文本中回忆元词覆盖了大部分内容，就是自引用
    covered = 0
    for w in _RECALL_META:
        if w in text:
            covered += len(w)
    # 元词覆盖 > 50% 的文本长度 → 自引用
    return covered > len(text) * 0.5


def _state_similarity(
    current: Dict[str, float],
    past: Dict[str, float],
    weights: Dict[str, float],
) -> float:
    """
    加权状态相似度（余弦思路，连续）。

    权重来自 _ACTION_DRIVE_WEIGHTS：只关注触发行动的那些维度。
    """
    dot = 0.0
    norm_c = 0.0
    norm_p = 0.0
    for dim in _DRIVE_DIMS:
        w = weights.get(dim, 0.1)  # 非关键维度给低权重
        c = float(current.get(dim, 0.5)) * w
        p = float(past.get(dim, 0.5)) * w
        dot += c * p
        norm_c += c * c
        norm_p += p * p
    denom = math.sqrt(max(norm_c, 1e-9)) * math.sqrt(max(norm_p, 1e-9))
    return dot / denom


def _extract_keywords(text: str, max_kw: int = 3) -> List[str]:
    """从 episode output_text 提取可指称的关键词。"""
    if not text:
        return []
    phrases = _PHRASE_RE.findall(text)
    seen = set()
    result = []
    for p in phrases:
        if p in seen or p in _STOP or len(p) < 2:
            continue
        seen.add(p)
        result.append(p)
        if len(result) >= max_kw:
            break
    return result
