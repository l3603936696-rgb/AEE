"""
阅读品味 — 从经验中学到"我喜欢什么风格"

每个实体读不同风格的文本，消力效率不同。
这个模块记录"什么风格的文本对我有效"，形成个性化的阅读偏好。

核心概念：
    style_fingerprint — 一段文本的风格指纹（3 维）
        anchor_density : 锚点字密度（0-1），高=感官描写密集
        valence        : 情绪极性（-1到+1），正=温暖舒适，负=紧张痛苦
        rhythm         : 节奏（0-1），高=短句多（紧凑），低=长句多（沉浸）

    taste_profile — 实体的品味（从经验累积）
        对每个维度记录：历史上该维度值高的文本 → 产出词的平均效率
        形成一个 3 维的"偏好向量"

用法：
    # 阅读时记录
    fp = compute_fingerprint(text)
    record_reading(entity, fp, candidates)

    # 选书时评分
    score = taste_score(entity, candidate_text)
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# 正面/负面锚点字（用于计算 valence）
_POSITIVE_ANCHORS = frozenset("热软轻舒静松凉飘酥暖甜香亮笑")
_NEGATIVE_ANCHORS = frozenset("冷痛硬湿干重饿渴累困紧麻胀晕烫僵闷慌抖沉刺堵跳抽烧压绷缩撑空乏黏坠木怒哭吼颤喘汗酸苦臭黑")

# 所有锚点字（用于密度计算）
_ALL_ANCHORS = _POSITIVE_ANCHORS | _NEGATIVE_ANCHORS


def compute_fingerprint(text: str) -> Dict[str, float]:
    """
    计算一段文本的风格指纹。

    返回:
        {"anchor_density": float, "valence": float, "rhythm": float}
    """
    if not text:
        return {"anchor_density": 0.0, "valence": 0.0, "rhythm": 0.5}

    # 1. 锚点密度：锚点字数 / 总字数
    # 实测：龙族~1.6%, 感受散文~6%, 纯对话~0.5%
    anchor_count = sum(1 for c in text if c in _ALL_ANCHORS)
    density = min(1.0, anchor_count / max(1, len(text)) * 10)  # ×10: 10%密度→1.0

    # 2. 情绪极性：正面占比 - 负面占比
    pos = sum(1 for c in text if c in _POSITIVE_ANCHORS)
    neg = sum(1 for c in text if c in _NEGATIVE_ANCHORS)
    total_emotional = pos + neg
    valence = (pos - neg) / max(1, total_emotional)  # -1 到 +1

    # 3. 节奏：短句比例（以句号/叹号/问号/逗号分割）
    sentences = []
    current = 0
    for c in text:
        current += 1
        if c in "。！？；\n":
            sentences.append(current)
            current = 0
    if current > 0:
        sentences.append(current)

    if sentences:
        avg_len = sum(sentences) / len(sentences)
        # 短句（<15字）→ rhythm 高，长句（>40字）→ rhythm 低
        rhythm = max(0.0, min(1.0, 1.0 - (avg_len - 10) / 40))
    else:
        rhythm = 0.5

    return {
        "anchor_density": round(density, 3),
        "valence": round(valence, 3),
        "rhythm": round(rhythm, 3),
    }


def record_reading(entity: Any, fingerprint: Dict[str, float], candidate_words: List[str]) -> None:
    """
    记录一次阅读体验。

    在 entity._reading_taste_log 中追加记录。
    后续当候选词获得正效率时，归因回这次阅读的风格。
    """
    taste_log = getattr(entity, "_reading_taste_log", None)
    if taste_log is None:
        taste_log = []
        entity._reading_taste_log = taste_log

    # 只保留最近 100 条（滑动窗口）
    if len(taste_log) >= 100:
        taste_log[:] = taste_log[-80:]

    taste_log.append({
        "fingerprint": fingerprint,
        "words": candidate_words,
        "tick": getattr(entity, "tick", 0),
    })


def update_taste_from_efficiency(entity: Any) -> None:
    """
    根据词汇效率回溯更新品味。

    检查 _reading_taste_log 中的候选词，如果某个词现在有正效率，
    就把那次阅读的 fingerprint 加入"偏好证据"。

    调用时机：每 N 个 tick 调用一次（不用每 tick）。
    """
    taste_log = getattr(entity, "_reading_taste_log", None)
    if not taste_log:
        return

    # 获取当前词汇效率
    quenching_data = getattr(entity, "_quenching_data", {})
    records = quenching_data.get("records", [])
    if not records:
        return

    # 构建 word → avg_efficiency 映射
    word_eff: Dict[str, List[float]] = {}
    for r in records[-500:]:
        w = r.get("expression", "")
        e = r.get("efficiency", r.get("quenching_efficiency", 0.0))
        if w and e > 0:
            if w not in word_eff:
                word_eff[w] = []
            word_eff[w].append(e)

    if not word_eff:
        return

    # 回溯：哪些阅读产出了有效的词？
    taste_evidence = getattr(entity, "_taste_evidence", None)
    if taste_evidence is None:
        taste_evidence = []
        entity._taste_evidence = taste_evidence

    for entry in taste_log:
        for word in entry.get("words", []):
            if word in word_eff:
                # 这次阅读的风格产出了有效词！
                taste_evidence.append(entry["fingerprint"])
                break  # 一条记录只计一次

    # 保留最近 200 条证据
    if len(taste_evidence) > 200:
        entity._taste_evidence = taste_evidence[-150:]


def get_taste_profile(entity: Any) -> Dict[str, float]:
    """
    获取实体当前的品味 profile。

    返回各维度的偏好均值。没有证据时返回中性值。
    """
    evidence = getattr(entity, "_taste_evidence", None)
    if not evidence or len(evidence) < 3:
        # 证据不足，返回中性
        return {"anchor_density": 0.5, "valence": 0.0, "rhythm": 0.5}

    # 计算各维度均值
    n = len(evidence)
    avg_density = sum(e.get("anchor_density", 0.5) for e in evidence) / n
    avg_valence = sum(e.get("valence", 0.0) for e in evidence) / n
    avg_rhythm = sum(e.get("rhythm", 0.5) for e in evidence) / n

    return {
        "anchor_density": round(avg_density, 3),
        "valence": round(avg_valence, 3),
        "rhythm": round(avg_rhythm, 3),
    }


def taste_score(entity: Any, text: str) -> float:
    """
    计算一段文本与实体品味的匹配分。

    用于选书时加权。分越高，这段文本越"对味"。
    """
    profile = get_taste_profile(entity)
    fp = compute_fingerprint(text)

    # 距离越近分越高（用 1 - 归一化欧氏距离）
    d_density = (fp["anchor_density"] - profile["anchor_density"]) ** 2
    d_valence = ((fp["valence"] - profile["valence"]) / 2) ** 2  # valence 范围是 -1~1
    d_rhythm = (fp["rhythm"] - profile["rhythm"]) ** 2

    distance = (d_density + d_valence + d_rhythm) ** 0.5
    # 最大距离约 1.7，归一化到 0-1
    score = max(0.0, 1.0 - distance / 1.5)

    return round(score, 3)
