"""
输入主题在线聚类（input_class 来源） — PLAN_learn_from_outside §2a

把到达的输入文本经 BGE 嵌入后，在线聚类成少数固定主题槽，为「输入→后果」
规则归纳（induct_input）提供**稳定且可复现**的 input_class 标签——
稳定是关键：同一类输入反复落到同一 theme_id，对应规则才能攒够证据被验证。

约束：
    - 复用既有 BGE（language_system.bge_analyzer），不引入 LLM。
    - 固定 N 槽：空槽由前 N 条不同输入填充；填满后 argmax 最近质心 + EMA 更新。
      纯 argmax 分配，无"够不够近"的阈值比较（填空槽 = 存在性初始化，非行为门控）。
    - 质心存进 entity._input_theme_data，随 entity_core.json 持久化。
    - 纯分类基础设施：guard 子句沿用 entity_state._json_default 的工程风格。
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

# ── 常量（来源标注）──
# 主题槽数：种子值，待 PLAN_learn_from_outside §6 用真实数据标定。
_N_THEMES = 6
# 质心 EMA 更新率：种子值，§6 标定。越小越稳、越大越跟新输入走。
_THEME_EMA = 0.2
# 归并阈值：余弦 >= 此值 → 并入最近主题，否则（且有空槽）立新主题。
# 这是在线聚类固有的感知阈值（非行为门控）。BGE-zh 归一化嵌入上「同主题」
# 余弦通常 > 0.6。种子值，§6 标定。
_THEME_MERGE_SIM = 0.6


def _embed(text: str) -> Optional[List[float]]:
    """用 BGE 把文本编码为归一化向量；BGE 不可用 / 异常 → None。"""
    try:
        from ..language_system.bge_analyzer import _get_bge_model
        model = _get_bge_model()
        if model is None:
            return None
        vec = model.encode([text], normalize_embeddings=True)[0]
        return [float(x) for x in vec]
    except Exception:
        return None


def _cos(a: List[float], b: List[float]) -> float:
    """两个已归一化向量的余弦（点积即余弦）。"""
    n = min(len(a), len(b))
    return sum(a[i] * b[i] for i in range(n))


def _ema_update(centroid: List[float], vec: List[float], alpha: float) -> List[float]:
    """EMA 混合后重新归一化，保持质心在单位球面上。"""
    n = min(len(centroid), len(vec))
    blended = [centroid[i] * (1.0 - alpha) + vec[i] * alpha for i in range(n)]
    norm = math.sqrt(sum(x * x for x in blended)) or 1.0
    return [x / norm for x in blended]


def _get_store(entity: Any) -> Dict[str, Any]:
    """取/初始化 entity 上的主题存储。结构全为 JSON 原生类型，可直接持久化。"""
    store = getattr(entity, "_input_theme_data", None)
    if not (isinstance(store, dict) and "centroids" in store):
        store = {"centroids": [], "ids": [], "counts": []}
        entity._input_theme_data = store
    return store


def _spawn(store: Dict[str, Any], vec: List[float]) -> str:
    """新立一个主题槽，返回其 theme_id。"""
    tid = f"theme_{len(store['centroids'])}"
    store["centroids"].append(vec)
    store["ids"].append(tid)
    store["counts"].append(1)
    return tid


def _assign(store: Dict[str, Any], idx: int, vec: List[float]) -> str:
    """并入已有主题 idx：EMA 更新质心、计数 +1，返回其 theme_id。"""
    store["centroids"][idx] = _ema_update(store["centroids"][idx], vec, _THEME_EMA)
    store["counts"][idx] += 1
    return store["ids"][idx]


def classify_input(entity: Any, text: str) -> str:
    """
    把输入文本归到一个主题槽（在线 leader 聚类），返回 theme_id（如 "theme_2"）。

    空文本（daemon 自主拍，无输入）/ BGE 不可用 → 返回 ""，
    该次快照不带 input_class，自然不进 input 归纳旁路。
    """
    text = (text or "").strip()
    if not text:
        return ""
    vec = _embed(text)
    if vec is None:
        return ""

    store = _get_store(entity)
    centroids = store["centroids"]

    # 首个输入 → 第一个主题
    if not centroids:
        return _spawn(store, vec)

    sims = [_cos(vec, c) for c in centroids]
    idx = max(range(len(sims)), key=lambda i: sims[i])

    # 足够相似 → 并入最近主题（稳定性：相同输入余弦≈1 必落同一主题）
    if sims[idx] >= _THEME_MERGE_SIM:
        return _assign(store, idx, vec)

    # 不够相似但有空槽 → 立新主题
    if len(centroids) < _N_THEMES:
        return _spawn(store, vec)

    # 满槽且都不够近 → 归最近主题（避免无界增长）
    return _assign(store, idx, vec)
