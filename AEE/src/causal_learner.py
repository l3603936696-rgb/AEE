"""
因果学习器 — 从 (输入来源, 状态delta) 配对中提取因果关联

读取 entity._causal_observations 缓冲，统计每种输入来源对各状态维度的
平均影响，减去无输入时的基线漂移，得到净因果效应。

输出示例：
    {
        "sibling":  {"loneliness": -0.012, "approach_drive": 0.03, ...},
        "external": {"loneliness": -0.018, "info_gap": -0.005, ...},
    }

含义："收到姐妹消息时，loneliness 平均比没有输入时多降 0.012"。
这就是她对"姐妹说话"这个事物的因果理解——不是定义，是经验。

调用方式：
    from .causal_learner import extract_causal_associations
    effects = extract_causal_associations(entity._causal_observations)
"""

from __future__ import annotations

from typing import Any, Dict, List

# 最少需要多少条同源观测才认为统计有意义
_MIN_SAMPLES = 5


def extract_causal_associations(
    observations: List[Dict[str, Any]],
    min_samples: int = _MIN_SAMPLES,
) -> Dict[str, Dict[str, float]]:
    """
    从因果观测缓冲中提取每种输入来源的净状态效应。

    参数：
        observations: entity._causal_observations 列表
        min_samples:  同源观测少于此数时不报告该来源

    返回：
        {source: {dimension: net_effect}}
        不包含 "none"（基线本身不是因果效应）。
    """
    # ---- 按来源累加 delta ----
    sums: Dict[str, Dict[str, float]] = {}
    counts: Dict[str, int] = {}

    for obs in observations:
        src = obs.get("source", "none")
        delta = obs.get("delta", {})
        counts[src] = counts.get(src, 0) + 1
        acc = sums.get(src)
        if acc is None:
            acc = {}
            sums[src] = acc
        for dim, val in delta.items():
            acc[dim] = acc.get(dim, 0.0) + float(val)

    # ---- 各来源平均 delta ----
    means: Dict[str, Dict[str, float]] = {}
    for src, acc in sums.items():
        n = counts[src]
        means[src] = {dim: total / n for dim, total in acc.items()}

    # ---- 基线：无输入时的自然漂移 ----
    baseline = means.get("none", {})

    # ---- 净因果效应 = 有输入均值 - 无输入均值 ----
    effects: Dict[str, Dict[str, float]] = {}
    for src, src_mean in means.items():
        if src == "none":
            continue
        if counts.get(src, 0) < min_samples:
            continue
        effect = {}
        for dim in src_mean:
            net = src_mean[dim] - baseline.get(dim, 0.0)
            effect[dim] = round(net, 6)
        effects[src] = effect

    return effects


def summarize_associations(
    effects: Dict[str, Dict[str, float]],
    top_n: int = 5,
) -> Dict[str, List[tuple]]:
    """
    对每个来源，按绝对效应值排序，返回影响最大的维度。

    返回：
        {source: [(dimension, net_effect), ...]}  按 |effect| 降序，最多 top_n 个。
    """
    summary: Dict[str, List[tuple]] = {}
    for src, dims in effects.items():
        ranked = sorted(dims.items(), key=lambda x: abs(x[1]), reverse=True)
        summary[src] = ranked[:top_n]
    return summary
