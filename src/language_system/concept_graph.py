"""
Concept Graph — 概念图（v1.0）

用已有躯体词作为底层锚点，向上组合出材料、力、形状、抽象属性等概念。
当输入包含某个概念词时，激活属性链，转换为状态偏置信号。

核心原则：
    - 概念 = 属性的组合 + 功能定义（不依赖视觉外观）
    - 激活是连续加权的，深度越深权重越小
    - 经验学习：词-状态共现积累后自动补充 state_bias
    - 纯函数，不直接修改 entity 状态（偏置由 pipeline 应用）
"""

import json
import logging
import math
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_GRAPH_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "concept_graph.json"
)
_GRAPH_CACHE: Optional[Dict] = None

# 属性值 → 状态偏置映射（从已有躯体词导出的经验性初始种子）
_ATTR_STATE_MAP: Dict[tuple, Dict[str, float]] = {
    ("weight",      "重"):  {"fatigue": 0.03,  "somatic_tone": -0.02},
    ("weight",      "轻"):  {"approach_drive": 0.02, "fatigue": -0.02},
    ("weight",      "中"):  {},
    ("texture",     "硬"):  {"stress": 0.02},
    ("texture",     "软"):  {"somatic_tone": 0.03},
    ("texture",     "流动"): {"somatic_tone": -0.01},
    ("temperature", "热"):  {"somatic_tone": 0.03},
    ("temperature", "冷"):  {"somatic_tone": -0.03},
    ("temperature", "暖"):  {"somatic_tone": 0.02},
    ("temperature", "凉"):  {"somatic_tone": -0.02},
    ("efficiency",  "高"):  {"curiosity": 0.05, "approach_drive": 0.03},
    ("efficiency",  "低"):  {"fatigue": 0.02,  "curiosity": -0.02},
    ("efficiency",  "中"):  {},
    ("wavelength",  "最长"): {"somatic_tone": 0.03, "approach_drive": 0.02},
    ("wavelength",  "长"):   {"somatic_tone": 0.02},
    ("wavelength",  "中长"): {"somatic_tone": 0.01, "joy": 0.01},
    ("wavelength",  "中"):   {},
    ("wavelength",  "短"):   {"somatic_tone": -0.01},
    ("wavelength",  "最短"): {"somatic_tone": -0.02, "stress": 0.02},
}

# 经验学习：积累多少次曝光后更新概念的 state_bias
_LEARN_THRESHOLD = 10
# 经验学习权重（和手动定义的比例）
_EXPERIENCE_WEIGHT = 0.3


def load_concept_graph() -> Dict:
    """加载概念图（带模块级缓存）。"""
    global _GRAPH_CACHE
    if _GRAPH_CACHE is not None:
        return _GRAPH_CACHE
    try:
        path = os.path.normpath(_GRAPH_PATH)
        with open(path, encoding="utf-8") as f:
            _GRAPH_CACHE = json.load(f)
        logger.info(f"[ConceptGraph] loaded {len(_GRAPH_CACHE)} concepts from {path}")
    except Exception as e:
        logger.warning(f"[ConceptGraph] failed to load: {e}")
        _GRAPH_CACHE = {}
    return _GRAPH_CACHE


def _attr_to_bias(attributes: Dict[str, str]) -> Dict[str, float]:
    """将属性 dict 转换为 state_bias dict。"""
    bias: Dict[str, float] = {}
    for attr_key, attr_val in attributes.items():
        mapped = _ATTR_STATE_MAP.get((attr_key, attr_val), {})
        for dim, delta in mapped.items():
            bias[dim] = bias.get(dim, 0.0) + delta
    return bias


def _merge_bias(
    target: Dict[str, float],
    source: Dict[str, float],
    weight: float,
) -> None:
    """将 source × weight 累加到 target，in-place。"""
    for dim, delta in source.items():
        target[dim] = target.get(dim, 0.0) + delta * weight


def _activate_one(word: str, graph: Dict, depth: int = 0) -> Dict[str, float]:
    """
    激活单个词，返回 state_bias。
    depth=0 是直接查到，depth=1 是 is_a 父节点（权重 0.5），不继续递归。
    """
    node = graph.get(word)
    if node is None:
        return {}

    bias: Dict[str, float] = {}

    # 直接 state_bias
    weight = 1.0 - depth * 0.5
    _merge_bias(bias, node.get("state_bias", {}), weight)

    # 属性链 → bias（仅直接命中时）
    if depth == 0:
        attr_bias = _attr_to_bias(node.get("attributes", {}))
        _merge_bias(bias, attr_bias, 0.8)

    # is_a 继承（深度 ≤ 1）
    if depth == 0:
        for parent in node.get("relations", {}).get("is_a", []):
            parent_bias = _activate_one(parent, graph, depth=1)
            _merge_bias(bias, parent_bias, 0.4)

    return bias


def scan_text_for_concepts(text: str) -> List[str]:
    """
    直接扫描文本，返回概念图中存在的词列表。
    用于补充 recognized_words（后者只含她已学会的词）。
    """
    if not text:
        return []
    graph = load_concept_graph()
    return [word for word in graph if word in text]


def activate_concepts(
    words: List[str],
    entity: Any,
) -> Dict[str, float]:
    """
    输入：识别出的词列表
    输出：合并后的 state_bias dict（由 pipeline 应用为瞬态偏置）

    流程：
        1. 直接查词 → 取 state_bias
        2. 查属性链 → 属性映射到状态偏置
        3. 查 is_a 父节点 → 继承（权重 × 0.4，深度 ≤ 1）
        4. 合并所有 bias（各维度加权求和）
        5. 限幅：每个维度最大偏置 ±0.15
    """
    if not words:
        return {}

    graph = load_concept_graph()
    merged: Dict[str, float] = {}

    for word in words:
        word_bias = _activate_one(word, graph, depth=0)
        _merge_bias(merged, word_bias, 1.0)

    # 加入经验学习补充的 bias（来自 entity._concept_learned_bias）
    learned = getattr(entity, "_concept_learned_bias", {})
    for word in words:
        lb = learned.get(word, {})
        _merge_bias(merged, lb, _EXPERIENCE_WEIGHT)

    # 限幅：连续 clamp，不用 if/else
    for dim in merged:
        v = merged[dim]
        merged[dim] = math.copysign(min(abs(v), 0.15), v)

    if merged:
        logger.debug(f"[ConceptGraph] activated {list(words)}: {merged}")

    return merged


def record_exposure(
    word: str,
    entity: Any,
    state_snapshot: Dict[str, float],
) -> None:
    """
    记录词-状态共现到 entity._concept_exposure_log。
    积累足够次数后触发经验学习。
    """
    log = getattr(entity, "_concept_exposure_log", None)
    if log is None:
        return

    graph = load_concept_graph()
    if word not in graph:
        return

    entry = log.setdefault(word, [])
    entry.append({
        "tick": getattr(entity, "tick", 0),
        "state": {
            k: float(state_snapshot.get(k, 0.0))
            for k in ("fatigue", "stress", "somatic_tone", "curiosity",
                       "approach_drive", "serenity", "joy", "loneliness")
        },
    })

    # 只保留最近 50 次
    if len(entry) > 50:
        log[word] = entry[-50:]

    # 达到阈值时尝试学习
    if len(entry) >= _LEARN_THRESHOLD:
        maybe_learn_from_exposure(word, entity)


def maybe_learn_from_exposure(word: str, entity: Any) -> None:
    """
    当词积累了 ≥ _LEARN_THRESHOLD 次曝光时，
    计算平均状态变化 → 补充/更新该词的经验性 state_bias。

    经验学习只写入 entity._concept_learned_bias，不修改 concept_graph.json。
    """
    log = getattr(entity, "_concept_exposure_log", {})
    entries = log.get(word, [])
    if len(entries) < _LEARN_THRESHOLD:
        return

    # 计算各维度均值
    dims = ("fatigue", "stress", "somatic_tone", "curiosity",
            "approach_drive", "serenity", "joy", "loneliness")
    sums: Dict[str, float] = {d: 0.0 for d in dims}
    for e in entries:
        for d in dims:
            sums[d] += e["state"].get(d, 0.0)
    n = len(entries)
    means = {d: sums[d] / n for d in dims}

    # 只保留偏离中性值（0.5）超过阈值的维度
    NEUTRAL = 0.5
    MIN_DEVIATION = 0.08
    learned_bias: Dict[str, float] = {}
    for d, mean_val in means.items():
        deviation = mean_val - NEUTRAL
        learned_bias[d] = deviation * 0.1 * (abs(deviation) > MIN_DEVIATION)

    # 过滤掉接近零的项
    learned_bias = {d: v for d, v in learned_bias.items() if abs(v) > 1e-4}

    if not hasattr(entity, "_concept_learned_bias"):
        return
    entity._concept_learned_bias[word] = learned_bias

    if learned_bias:
        logger.info(
            f"[ConceptGraph] learned bias for '{word}' "
            f"from {n} exposures: {learned_bias}"
        )
