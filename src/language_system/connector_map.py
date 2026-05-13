"""
Connector Map — 连接词连续评分系统（v11.5）

连接词（"好"、"太"、"了"、"啊"）是锚点词的状态映射伙伴。
它们同样有驱动力场签名，描述"什么状态下说这个词"。

设计原则：
    - 全部连续，无 if-else 阈值
    - 高斯评分 + softmax 采样（与锚点词评分机制完全一致）
    - 无需单独 unlock 学习环，随锚点词一起自然出现

三类连接词：
    1. 强度前缀  — 基于 _intensity 评分（"有点" / "好" / "太"）
    2. 语气开头  — 基于情绪维度评分（"嗯…" / "啊…" / "唉…"）
    3. 后缀语气  — 基于变化量 + 社会信号评分（"了" / "啊" / "吧"）
"""

import math
import random
from typing import Dict


def _gauss(x: float, mu: float, sigma: float) -> float:
    """
    高斯评分函数。
    x 越接近 mu 得分越高，sigma 控制甜点宽度。
    返回值 ∈ (0, 1]。
    """
    dx = x - mu
    return math.exp(-0.5 * (dx / sigma) ** 2)


def _softmax_sample(scores: Dict[str, float], temperature: float = 0.15) -> str:
    """
    softmax 概率采样（与锚点词采样机制完全一致）。
    temperature 越高越发散，越低越集中。
    返回选中的词（空字符串表示不选任何词）。
    """
    if not scores:
        return ""

    items = list(scores.items())
    weights = [math.exp(s / max(temperature, 0.01)) for _, s in items]
    total = sum(weights)
    if total < 1e-9:
        return items[0][0]
    probs = [w / total for w in weights]
    return random.choices([k for k, _ in items], weights=probs, k=1)[0]


# ============================================================================
# 1. 强度前缀（基于 _intensity 评分）
# ============================================================================

def score_intensity_prefix(intensity: float) -> Dict[str, float]:
    """
    强度前缀的高斯评分。

    | 词     | μ    | σ    | 直觉含义           |
    |--------|------|------|-------------------|
    | ""     | 0.10 | 0.12 | 平淡，不需要强调   |
    | "有点" | 0.25 | 0.15 | 轻微不适          |
    | "好"   | 0.50 | 0.20 | 中度感受（正负通用）|
    | "太"   | 0.70 | 0.18 | 强烈感受          |

    无 if-else，全部通过高斯连续评分。
    """
    return {
        "":     _gauss(intensity, 0.10, 0.12),
        "有点": _gauss(intensity, 0.25, 0.15),
        "好":   _gauss(intensity, 0.50, 0.20),
        "太":   _gauss(intensity, 0.70, 0.18),
    }


def sample_intensity_prefix(intensity: float, temperature: float = 0.15) -> str:
    """强度前缀采样。"""
    return _softmax_sample(score_intensity_prefix(intensity), temperature)


# ============================================================================
# 2. 语气开头词（基于情绪维度评分）
# ============================================================================

def score_opening_particle(
    fatigue: float,
    somatic_distress: float,
    sadness: float,
    energy: float,
) -> Dict[str, float]:
    """
    语气开头词的高斯评分。

    | 词     | 维度              | μ    | σ    | 直觉含义         |
    |--------|-------------------|------|------|------------------|
    | ""     | —                 | —    | —    | 中性陈述         |
    | "嗯…" | fatigue           | 0.40 | 0.20 | 疲倦的低语       |
    | "啊…" | somatic_distress  | 0.35 | 0.20 | 躯体不适的叹声   |
    | "唉…" | sadness + low_e   | 0.40 | 0.18 | 低落             |

    注意："啊…"和"啊"（后缀）共享同一个汉字，语境决定歧义消解。
    """
    low_energy = 1.0 - energy
    composite = (sadness + low_energy) / 2.0

    return {
        "":     _gauss(max(fatigue, somatic_distress, sadness), 0.05, 0.08),
        "嗯…": _gauss(fatigue, 0.40, 0.20),
        "啊…": _gauss(somatic_distress, 0.35, 0.20),
        "唉…": _gauss(composite, 0.40, 0.18),
    }


def sample_opening_particle(
    fatigue: float,
    somatic_distress: float,
    sadness: float,
    energy: float,
    temperature: float = 0.15,
) -> str:
    """语气开头词采样。"""
    return _softmax_sample(
        score_opening_particle(fatigue, somatic_distress, sadness, energy),
        temperature,
    )


# ============================================================================
# 3. 后缀语气词（基于变化量 + 社会信号评分）
# ============================================================================

def score_suffix_particle(
    delta_total: float,
    loneliness: float,
    approach: float,
    anxiety: float,
    unresolved: float,
) -> Dict[str, float]:
    """
    后缀语气词的高斯评分。

    | 词  | 维度                  | μ    | σ    | 直觉含义             |
    |-----|----------------------|------|------|----------------------|
    | ""  | —                    | 0.00 | 0.04 | 陈述，不需要修饰     |
    | "了" | delta(fatigue+avoid - energy - stress) | 0.08 | 0.05 | 状态正在变化/已发生 |
    | "啊" | loneliness + approach | 0.50 | 0.25 | 说给某人听，呼告     |
    | "吧" | anxiety + unresolved   | 0.40 | 0.20 | 不确定，向对方确认   |

    无 if-else，全部通过高斯连续评分。
    """
    social_signal = (loneliness + approach) / 2.0
    uncertainty_signal = (anxiety + unresolved) / 2.0

    return {
        "":   _gauss(delta_total, 0.00, 0.04),
        "了": _gauss(delta_total, 0.08, 0.05),
        "啊": _gauss(social_signal, 0.50, 0.25),
        "吧": _gauss(uncertainty_signal, 0.40, 0.20),
    }


def sample_suffix_particle(
    delta_total: float,
    loneliness: float,
    approach: float,
    anxiety: float,
    unresolved: float,
    temperature: float = 0.15,
) -> str:
    """后缀语气词采样。"""
    return _softmax_sample(
        score_suffix_particle(delta_total, loneliness, approach, anxiety, unresolved),
        temperature,
    )
