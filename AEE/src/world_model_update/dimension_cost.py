"""
Dimension Cost — 维度维护成本（奥卡姆剃刀动力学实现）

核心概念（纲领 v2）：
    每个被世界模型追踪的维度都有维护成本。
    新维度净收益 = 压缩收益 - 长期维护成本。
    净收益为负的维度应当被剪枝。

    这是奥卡姆剃刀的动力学版本：
    不是"简单模型更好"（静态判断），
    而是"无法自付维护费的维度被自然淘汰"（动态过程）。

"维度"的操作定义：
    world model rules 的 expected_deltas 中出现的字段名。
    例：{"loneliness": -0.15, "energy": -0.03} 追踪 loneliness 和 energy 两个维度。

维度价值评估：
    从 entity.snapshots 的 prediction_error_map 中提取逐字段预测质量。
    - 活跃度：字段值跨 tick 的方差（不变的字段不值得预测）
    - 预测质量：该字段的预测误差均值（误差小 = 预测准 = 有价值）
    - 维护成本：多少条规律在追踪该字段（越多越贵）
    - 净价值 = 活跃度 × 预测质量 - 维护成本

输出用途：
    - 净价值为负的维度 → 追踪它的规律面临额外衰减压力
    - 净价值为正的维度 → 追踪它的规律获得衰减保护
"""

import math
from typing import Any, Dict, List, Optional, Tuple

from .rules import Rule, Snap


# ---- 参数 ----

# 最少快照数（不足时不评估）
_MIN_SNAPS = 10

# 维护成本缩放（每条规律追踪一个字段的成本）
_COST_PER_RULE = 0.05

# 活跃度阈值（方差低于此值的字段视为"休眠"）
_DORMANT_VARIANCE = 0.0001

# 维度价值对衰减的最大调制（±30%）
_MAX_DECAY_MODULATION = 0.3


def compute_dimension_values(
    wm_rules: List[Any],
    snapshots: List[Any],
    max_snaps: int = 50,
) -> Dict[str, float]:
    """
    计算每个被追踪维度的净价值。

    参数：
        wm_rules  : 当前世界模型规律列表
        snapshots : 最近的 Snap 列表（含 prediction_error_map、pre/post_state）
        max_snaps : 最多使用多少个最近的 snap

    返回：
        {field: net_value}
        正值 = 维度值得追踪（压缩收益 > 维护成本）
        负值 = 维度不值得追踪（应当被剪枝）
        不包含未被任何规律追踪的字段
    """
    # ---- 1. 盘点：哪些字段被哪些规律追踪 ----
    safe_rules = _safe_rules(wm_rules)
    active_rules = [r for r in safe_rules if r.status == "active"]

    field_rule_count: Dict[str, int] = {}
    for r in active_rules:
        for field in r.expected_deltas:
            field_rule_count[field] = field_rule_count.get(field, 0) + 1

    if not field_rule_count:
        return {}

    # ---- 2. 从快照提取逐字段统计 ----
    safe_snaps = _safe_snaps(snapshots, max_snaps)
    n = len(safe_snaps)

    if n < _MIN_SNAPS:
        # 样本不足，返回中性值
        return {f: 0.0 for f in field_rule_count}

    # 逐字段收集 (actual_delta, prediction_error)
    field_deltas: Dict[str, List[float]] = {f: [] for f in field_rule_count}
    field_pred_errors: Dict[str, List[float]] = {f: [] for f in field_rule_count}

    for snap in safe_snaps:
        pre = snap.pre_state
        post = snap.post_state
        pe_map = snap.prediction_error_map

        for field in field_rule_count:
            # 实际变化量
            pre_val = float(pre.get(field, 0.0))
            post_val = float(post.get(field, pre_val))
            delta = post_val - pre_val
            field_deltas[field].append(delta)

            # 预测误差（可能缺失）
            if field in pe_map:
                field_pred_errors[field].append(abs(float(pe_map[field])))

    # ---- 3. 计算每个字段的三个指标 ----
    result: Dict[str, float] = {}

    total_active = max(1, len(active_rules))

    for field, rule_count in field_rule_count.items():
        deltas = field_deltas[field]
        pred_errors = field_pred_errors[field]

        # 活跃度 = 变化量的方差（高方差 = 字段经常变 = 值得预测）
        if len(deltas) >= _MIN_SNAPS:
            mean_delta = sum(deltas) / len(deltas)
            variance = sum((d - mean_delta) ** 2 for d in deltas) / len(deltas)
        else:
            variance = 0.0

        # 预测质量 = 1 - mean(|prediction_error|)（误差越小越好）
        if len(pred_errors) >= 3:
            mean_error = sum(pred_errors) / len(pred_errors)
            # clamp: 如果 mean_error > 1，quality 为 0
            prediction_quality = max(0.0, 1.0 - mean_error)
        else:
            prediction_quality = 0.5  # 数据不足，给中性值

        # 维护成本 = 该字段被多少条规律追踪（占比）
        cost = rule_count * _COST_PER_RULE

        # 活跃度归一化（取 log 防止极端值）
        if variance < _DORMANT_VARIANCE:
            activity = 0.0  # 休眠字段
        else:
            activity = min(1.0, math.log1p(variance * 1000) / math.log1p(10))

        # 净价值 = 压缩收益 - 维护成本
        # 压缩收益 = 活跃度 × 预测质量（活跃且预测准 = 有价值）
        compression_benefit = activity * prediction_quality
        net_value = compression_benefit - cost

        result[field] = round(net_value, 4)

    return result


def dimension_decay_modifier(
    rule: Rule,
    dimension_values: Dict[str, float],
) -> float:
    """
    根据规律追踪的维度价值，计算衰减速率调制系数。

    规律主要追踪高价值维度 → 衰减减慢（被保护）。
    规律主要追踪低价值维度 → 衰减加速（应当被剪枝）。

    返回 ∈ [1 - _MAX_DECAY_MODULATION, 1 + _MAX_DECAY_MODULATION]。
    """
    if not rule.expected_deltas or not dimension_values:
        return 1.0

    # 计算该规律追踪维度的平均净价值
    total_value = 0.0
    tracked_count = 0
    for field in rule.expected_deltas:
        if field in dimension_values:
            total_value += dimension_values[field]
            tracked_count += 1

    if tracked_count == 0:
        return 1.0

    avg_value = total_value / tracked_count
    # 正净价值 → 衰减减慢（系数 < 1）
    # 负净价值 → 衰减加速（系数 > 1）
    modifier = 1.0 - avg_value * _MAX_DECAY_MODULATION / 0.5  # 0.5 为归一化基准
    return max(1.0 - _MAX_DECAY_MODULATION, min(1.0 + _MAX_DECAY_MODULATION, modifier))


# ---- 辅助 ----

def _safe_rules(items: Any) -> List[Rule]:
    if not items:
        return []
    result = []
    for r in items:
        if isinstance(r, Rule):
            result.append(r)
        elif isinstance(r, dict):
            result.append(Rule.from_dict(r))
    return result


def _safe_snaps(items: Any, max_n: int) -> List[Snap]:
    if not items:
        return []
    recent = items[-max_n:] if len(items) > max_n else items
    result = []
    for s in recent:
        if isinstance(s, Snap):
            result.append(s)
        elif isinstance(s, dict):
            result.append(Snap.from_dict(s))
    return result
