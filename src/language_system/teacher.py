"""
teacher — 教学模块

职责（一句话）：根据实体当前状态从 teacher_lexicon 选出最匹配的概念，
生成反射句，在合适时机注入到输出层。

设计约束：
- 禁止 if/else 做逻辑路由——所有分支用 softmax 或连续函数替代
- 禁止调用 LLM——纯规则/查表
- 单文件单职责
- ≤ 400 行
"""

import math
from typing import Optional

import numpy as np

from .teacher_lexicon import TEACHER_LEXICON

# === 常量 ===
MIN_TEACH_STRENGTH = 0.25
SOFTMAX_TEMPERATURE = 1.2


def _get_state_val(state, key: str) -> float:
    """安全获取状态属性，不存在返回 0.0。"""
    return getattr(state, key, 0.0)


def _get_delta(state, key: str) -> float:
    """获取状态值的变化量 delta（如无历史快照取 0）。"""
    val = _get_state_val(state, key)
    snapshots = getattr(state, "snapshots", [])
    if len(snapshots) >= 2:
        prev_val = snapshots[-2].get(key, val) if isinstance(snapshots[-2], dict) else getattr(snapshots[-2], key, val)
        return val - prev_val
    return 0.0


def score_concept(concept_key: str, state) -> float:
    """
    计算一个词条与当前状态的匹配分。

    匹配逻辑：词条 state_hint 里每个维度都有期望方向（"high"/"low"/
    "rising"/"dropping"/"active"），实体状态里对应维度的实际值与期望
    方向越一致，分数越高。

    方向对应的分数计算方式：
    - "high"     → score += clamp(val, 0, 1)
    - "low"      → score += clamp(1 - val, 0, 1)
    - "rising"   → score += clamp(delta, 0, 1)
    - "dropping" → score += clamp(-delta, 0, 1)
    - "active"   → score += clamp(abs(val - 0.5) * 2, 0, 1)
    """
    entry = TEACHER_LEXICON.get(concept_key)
    if entry is None:
        return 0.0

    state_hint = entry.get("state_hint", {})
    if not state_hint:
        return 0.0

    total_score = 0.0
    dim_count = 0

    for dim, direction in state_hint.items():
        val = _get_state_val(state, dim)
        delta = _get_delta(state, dim)

        if direction == "high":
            contribution = float(np.clip(val, 0.0, 1.0))
        elif direction == "low":
            contribution = float(np.clip(1.0 - val, 0.0, 1.0))
        elif direction == "rising":
            contribution = float(np.clip(delta, 0.0, 1.0))
        elif direction == "dropping":
            contribution = float(np.clip(-delta, 0.0, 1.0))
        elif direction == "active":
            contribution = float(np.clip(abs(val - 0.5) * 2, 0.0, 1.0))
        else:
            contribution = 0.0

        total_score += contribution
        dim_count += 1

    return total_score / max(dim_count, 1)


def _softmax(logits: list[float], temperature: float = 1.0) -> list[float]:
    """
    计算 softmax 分布。
    使用 max-normalization 防止指数溢出。
    """
    if not logits:
        return []
    max_logit = max(logits)
    exps = [math.exp((x - max_logit) / temperature) for x in logits]
    sum_exps = sum(exps)
    return [e / sum_exps for e in exps]


def select_concept(state, top_k: int = 3) -> list[tuple[str, float]]:
    """
    对 TEACHER_LEXICON 里所有词条打分，softmax 归一化后返回 top_k 个。

    返回:
        list[tuple[str, float]]  — 格式 [(concept_key, probability), ...]，
        按概率降序。
    """
    keys = list(TEACHER_LEXICON.keys())
    raw_scores = [score_concept(k, state) for k in keys]
    probs = _softmax(raw_scores, temperature=SOFTMAX_TEMPERATURE)

    keyed_probs = list(zip(keys, probs))
    keyed_probs.sort(key=lambda x: x[1], reverse=True)

    return keyed_probs[:top_k]


def should_teach(state) -> float:
    """
    返回 0~1 的触发强度。

    触发条件：
    - unresolved 高（她有东西悬着）
    - loneliness 高（她需要被接住）
    - 两者叠加时触发强度最高

    公式（纯连续，无阈值）：
        raw = 1.0 - (1.0 - unresolved) * (1.0 - loneliness)
    """
    unresolved = _get_state_val(state, "unresolved")
    loneliness = _get_state_val(state, "loneliness")
    raw = 1.0 - (1.0 - unresolved) * (1.0 - loneliness)
    return float(np.clip(raw, 0.0, 1.0))


def make_teaching(state) -> Optional[dict]:
    """
    主入口。组合以上函数，返回教学内容或 None（强度太低时）。

    返回:
        None  — 触发强度 < MIN_TEACH_STRENGTH
        {
            "concept":         str,       # 词条 key
            "description":     str,       # 体感入口描述
            "phrase":          str,       # 用她的词拼出的翻译句
            "opposite_phrase": str,       # 对立面
            "reflect":         str,       # 反射句（老师说的话）
            "strength":        float,     # 触发强度
            "probability":     float,     # 该词条在 softmax 里的概率
        }
    """
    strength = should_teach(state)
    if strength < MIN_TEACH_STRENGTH:
        return None

    candidates = select_concept(state, top_k=1)
    if not candidates:
        return None

    concept_key, probability = candidates[0]
    entry = TEACHER_LEXICON[concept_key]

    return {
        "concept": concept_key,
        "description": entry["description"],
        "phrase": entry["phrase"],
        "opposite_phrase": entry["opposite_phrase"],
        "reflect": entry["reflect"],
        "strength": strength,
        "probability": probability,
    }
