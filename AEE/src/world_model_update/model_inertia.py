"""
Model Inertia — 模型惰性（思考动力学·第七齿轮）

核心概念：
    每条规律的"沉没成本"决定它多难被改变。
    惰性不是缺陷，是有限算力下的合理策略。
    频繁更新模型的成本可能高于忍受轻微误差。

惰性来源（纲领 v2）：
    1. 历史沉没成本 — 年龄 × 经验 × 置信度积分
    2. 下游耦合 — 多少其他规律预测同一字段
    3. 更新的临时不稳定 — 改动高惯性规律后系统会暂时不稳定

惰性效应：
    - 衰减减缓：高惯性规律 confidence 下降更慢
    - 验证抵抗：单次反面证据对高惯性规律影响更小
    - 能量代价：显著改动高惯性规律消耗 energy

边界条件（纲领 v2）：
    惰性失控 = 系统拒绝任何反馈。
    防线：累积误差持续超过维护成本时，inertia 自然被突破。

副产品：
    人格 ≈ 沉没成本最高的那组规律。
"""

import math
import time as _time
from typing import Any, Dict, List, Optional, Tuple

from .rules import Rule


# ---- 惯性计算参数 ----

# 各成分权重（和 = 1.0）
_W_AGE = 0.20          # 年龄
_W_EXPERIENCE = 0.30   # 经验量
_W_CONFIDENCE = 0.25   # 置信度
_W_STABILITY = 0.10    # 稳定性
_W_COUPLING = 0.15     # 下游耦合

# 归一化基准
_AGE_NORM_HOURS = 720.0     # 30 天 → age_factor ≈ 1.0
_EXP_NORM_COUNT = 100       # 100 次经验 → exp_factor ≈ 1.0

# 惯性对衰减的最大减速（0.7 = 高惯性规律衰减减慢 70%）
_INERTIA_DECAY_DAMPING = 0.7

# 惯性对负面验证的最大缓冲（0.5 = 高惯性规律受负面证据影响减半）
_INERTIA_VERIFY_BUFFER = 0.5

# 显著变化阈值（confidence 变动超过此值 → 触发能量代价）
_SIGNIFICANT_CHANGE_THRESHOLD = 0.08

# 每点惯性的能量代价缩放
_ENERGY_COST_PER_INERTIA = 0.01


def compute_inertia(
    rule: Rule,
    all_rules: Optional[List[Rule]] = None,
    now: Optional[float] = None,
) -> float:
    """
    计算单条规律的惯性（沉没成本代理）。

    返回 ∈ [0, 1]。高值 = 深嵌的核心信念，低值 = 新生的试探性模型。

    参数：
        rule      : 待计算的规律
        all_rules : 全部活跃规律（用于计算下游耦合）。可选。
        now       : 当前时间戳。可选，默认 time.time()。
    """
    if now is None:
        now = _time.time()

    # ---- 1. 年龄因子：log 缩放，老规律变化缓慢 ----
    age_hours = max(0.0, now - rule.created_at) / 3600.0
    age_factor = math.log1p(age_hours) / math.log1p(_AGE_NORM_HOURS)
    age_factor = min(1.0, age_factor)

    # ---- 2. 经验因子：sqrt 缩放 ----
    exp_factor = math.sqrt(max(1, rule.source_experience_count)) / math.sqrt(_EXP_NORM_COUNT)
    exp_factor = min(1.0, exp_factor)

    # ---- 3. 置信度因子：平方（高 confidence 惯性急增）----
    conf_factor = min(1.0, rule.confidence) ** 2

    # ---- 4. 稳定性因子：直接使用 ----
    stab_factor = min(1.0, max(0.0, rule.stability_score))

    # ---- 5. 下游耦合因子 ----
    coupling_factor = 0.0
    if all_rules and rule.expected_deltas:
        coupling_factor = _compute_coupling(rule, all_rules)

    # ---- 加权合成 ----
    raw = (
        _W_AGE * age_factor +
        _W_EXPERIENCE * exp_factor +
        _W_CONFIDENCE * conf_factor +
        _W_STABILITY * stab_factor +
        _W_COUPLING * coupling_factor
    )
    return max(0.0, min(1.0, raw))


def _compute_coupling(rule: Rule, all_rules: List[Rule]) -> float:
    """
    下游耦合度：有多少其他活跃规律预测与本规律相同的字段。

    共享字段越多 → 改动本规律时需要重新协调的关联模型越多。
    """
    my_fields = set(rule.expected_deltas.keys())
    if not my_fields:
        return 0.0

    overlap_count = 0
    active_count = 0
    for other in all_rules:
        if other.id == rule.id:
            continue
        if other.status != "active":
            continue
        active_count += 1
        other_fields = set(other.expected_deltas.keys())
        overlap = len(my_fields & other_fields)
        if overlap > 0:
            overlap_count += overlap

    if active_count == 0:
        return 0.0
    # 归一化：每条规律平均 1 个重叠字段 → coupling ≈ 1.0
    return min(1.0, overlap_count / max(1.0, active_count))


def inertia_decay_factor(inertia: float) -> float:
    """
    惯性对衰减率的减速因子。

    返回 ∈ [1 - _INERTIA_DECAY_DAMPING, 1.0]。
    衰减率 × 此因子 → 高惯性规律衰减更慢。
    """
    return 1.0 - inertia * _INERTIA_DECAY_DAMPING


def inertia_verify_factor(inertia: float) -> float:
    """
    惯性对负面验证的缓冲因子。

    仅影响负面验证（verification failure → confidence 下降）。
    正面验证不受影响（好消息不需要克服惯性）。

    返回 ∈ [1 - _INERTIA_VERIFY_BUFFER, 1.0]。
    负面 delta × 此因子 → 高惯性规律受单次反面证据影响更小。
    """
    return 1.0 - inertia * _INERTIA_VERIFY_BUFFER


def compute_update_energy_cost(
    old_confidence: float,
    new_confidence: float,
    inertia: float,
) -> float:
    """
    计算规律更新的能量代价。

    只在 confidence 显著变化时产生代价。
    代价 = |Δconfidence| × inertia × scaling。

    返回 energy 扣减量 ∈ [0, ~0.01]。
    """
    delta = abs(new_confidence - old_confidence)
    if delta < _SIGNIFICANT_CHANGE_THRESHOLD:
        return 0.0
    return delta * inertia * _ENERGY_COST_PER_INERTIA


def identify_personality_core(
    rules: List[Rule],
    top_n: int = 5,
) -> List[Tuple[str, float]]:
    """
    识别"人格核心"——沉没成本最高的那组规律。

    纲领：人格 = 沉没成本最高的那组模型。
    这些规律最难被改变，定义了系统的行为基线。

    返回 [(rule_id, inertia)] 按惯性降序排列，最多 top_n 条。
    """
    now = _time.time()
    active_rules = [r for r in rules if r.status == "active"]
    scored = [
        (r.id, compute_inertia(r, active_rules, now))
        for r in active_rules
    ]
    scored.sort(key=lambda x: -x[1])
    return scored[:top_n]
