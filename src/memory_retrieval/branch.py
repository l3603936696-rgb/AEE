"""
Branch Retrieval — 枝干联想检索（联想通道）

后台随机采样记忆，计算与当前情境的契合度，
浮现契合度高且受状态调制的记忆，注入 thought_packet 产生意外联想感。

职责：
    1. 从 episodes_db 随机采样
    2. 计算每条记忆与当前 concept_tags 的契合度
    3. 应用状态敏感调制
    4. 返回通过阈值的记忆
"""

from typing import Any, Dict, List, Optional
import math

# 参数默认值
DEFAULT_BRANCH_SAMPLE_COUNT: int = 8
DEFAULT_BRANCH_FLOAT_THRESHOLD: float = 0.50


def _tokenize(text: str) -> List[str]:
    """轻量分词：提取中文连续词 + 英文词。"""
    import re
    if not text:
        return []
    tokens: List[str] = []
    # 英文词
    for part in re.split(r"[^\w]+", text.lower()):
        if part and len(part) >= 2 and part.isalpha():
            tokens.append(part)
    # 中文连续词
    chinese = re.findall(r"[\u4e00-\u9fff]{2,}", text)
    for seq in chinese:
        tokens.append(seq)
        for i in range(len(seq) - 1):
            tokens.append(seq[i : i + 2])
    return tokens


def _cosine_sim(a: Dict[str, int], b: Dict[str, int]) -> float:
    """词频向量的余弦相似度。"""
    common = set(a) & set(b)
    if not common:
        return 0.0
    dot = sum(a[w] * b[w] for w in common)
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _compute_affinity(episode_tags: List[str], concept_tags: List[str]) -> float:
    """
    计算记忆与当前情境的契合度。

    用 episode 的 tags 和 input 文本与 concept_tags 做词级重叠度。
    返回 [0.0, 1.0]。
    """
    if not episode_tags and not concept_tags:
        return 0.0

    ep_text = " ".join(str(t) for t in episode_tags)
    ctx_text = " ".join(str(t) for t in concept_tags)

    ep_tokens = set(_tokenize(ep_text))
    ctx_tokens = set(_tokenize(ctx_text))

    if not ep_tokens or not ctx_tokens:
        return 0.0

    overlap = len(ep_tokens & ctx_tokens)
    total = len(ctx_tokens)
    return min(1.0, overlap / total * 2.0)  # 放大重叠效果


def _compute_coherence_coherence(recent_deltas: Any) -> float:
    """从 recent_deltas 计算 coherence（复刻 compute_coherence 逻辑）。"""
    if not recent_deltas:
        return 0.5
    try:
        deltas = [abs(float(d.get("somatic_tone", 0.0))) for d in recent_deltas]
        if not deltas:
            return 0.5
        mean = sum(deltas) / len(deltas)
        variance = sum((d - mean) ** 2 for d in deltas) / len(deltas)
        return max(0.0, min(1.0, 1.0 / (1.0 + variance * 10.0)))
    except Exception:
        return 0.5


def _sample_random_episodes(count: int) -> List[Any]:
    """从 episodes_db 随机采样 episode。"""
    try:
        from ..memory_hub.episodes_db import get_recent_episodes
        episodes = get_recent_episodes(limit=min(count * 4, 100))
        if len(episodes) <= count:
            return episodes
        import random
        return random.sample(episodes, count)
    except Exception:
        return []


def branch_retrieval(
    entity_state: Any,
    concept_tags: List[str],
    *,
    sample_count: int = DEFAULT_BRANCH_SAMPLE_COUNT,
    base_threshold: float = DEFAULT_BRANCH_FLOAT_THRESHOLD,
) -> List[Dict[str, Any]]:
    """
    枝干联想检索入口。

    参数：
        entity_state  : EntityCore 实例（需有 loneliness / stress / recent_deltas 属性）
        concept_tags  : 当前 concept_tags 列表
        sample_count  : 随机采样条数
        base_threshold: 基础浮出阈值

    返回：
        List[Dict[str, Any]] : 按得分降序排列的浮出记忆
            [{
                "episode": Episode,
                "score": float,
                "affinity": float,
                "floated": bool,  # 是否通过了调制阈值
            }]
    """
    try:
        from .state_modulation import compute_state_sensitive_weight

        loneliness = float(getattr(entity_state, "loneliness", 0.0))
        stress = float(getattr(entity_state, "stress", 0.0))
        recent_deltas = getattr(entity_state, "recent_deltas", None)
        coherence = _compute_coherence_coherence(recent_deltas)

        # 状态敏感调制阈值
        threshold_mod = compute_state_sensitive_weight(loneliness, stress, coherence)
        effective_threshold = base_threshold * threshold_mod

        # 随机采样
        episodes = _sample_random_episodes(sample_count)
        if not episodes:
            return []

        # 计算每条记忆的契合度
        scored: List[Dict[str, Any]] = []
        for ep in episodes:
            tags = getattr(ep, "tags", []) or []
            raw_input = getattr(ep, "raw_input", "") or ""
            full_text = " ".join(str(t) for t in tags) + " " + raw_input
            ep_tokens = _tokenize(full_text)

            affinity = _compute_affinity(ep_tokens, concept_tags)

            # 加入随机扰动（让联想有意外感）
            import random
            noise = random.uniform(0.0, 0.05)
            score = affinity * (1.0 + noise)

            floated = score >= effective_threshold

            if floated:
                scored.append({
                    "episode": ep,
                    "score": round(score, 3),
                    "affinity": round(affinity, 3),
                    "floated": floated,
                    "threshold": round(effective_threshold, 3),
                })

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:3]

    except Exception:
        return []


if __name__ == "__main__":
    print("=== 枝干检索测试 ===\n")

    # 模拟 entity_state
    class FakeEntity:
        loneliness = 0.3
        stress = 0.2
        recent_deltas = [{"somatic_tone": 0.1}, {"somatic_tone": 0.2}]

    fake_entity = FakeEntity()
    fake_concepts = ["孤独", "朋友", "连接", "社交"]

    result = branch_retrieval(fake_entity, fake_concepts)
    print(f"采样8条，随机浮出{len(result)}条：")
    for item in result:
        ep = item["episode"]
        print(f"  score={item['score']:.3f} | affinity={item['affinity']:.3f} | {ep.raw_input or '(无input)'}")

    print("\n全部测试完成")
