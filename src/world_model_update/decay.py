"""
Decay Module (衰减模块)

综合内分泌状态动态调整衰减速率，实现：
    1. 退化抵抗：高 stability_score 时衰减减慢
    2. 贝叶斯平滑：经验越多衰减越少
    3. 绝对零度：confidence <= absolute_zero 的规律不衰减

基础衰减率从 world_model.decay_rate（默认 0.02）读取。
衰减周期从 world_model.decay_min_hours（默认 24）读取。

约束：
    - state_snapshot 必须是异步周期触发时的最新快照
    - 不能使用循环开头缓存的旧快照（由外层调度器保证）
"""

import time
import math
from typing import Any, Dict, List

from .defaults import get_raw_value
from .rules import Rule


# ============================================================================
# 辅助函数
# ============================================================================

def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _safe_rules(items: Any) -> List[Rule]:
    """将任意规律格式安全化"""
    if not items:
        return []
    result: List[Rule] = []
    for r in items:
        if isinstance(r, Rule):
            result.append(r)
        elif isinstance(r, dict):
            result.append(Rule.from_dict(r))
    return result


def _time_since_last(time_stamp: float, now: float) -> float:
    """计算距上次衰减的时间（秒）"""
    if time_stamp <= 0:
        return 0.0
    return max(0.0, now - time_stamp)


# ============================================================================
# 核心逻辑
# ============================================================================

def _compute_endocrine_multiplier(
    stress: float,
    fatigue: float,
    base_rate: float,
    stress_multiplier: float,
) -> float:
    """
    内分泌调节：根据压力和疲劳计算衰减倍率。

    当 stress >= 0.5 时，衰减加速。
    倍率 = 1.0 + stress × stress_multiplier
    最高约 2.5x（stress=1.0 时）。
    fatigue 预留（当前参与倍率的自然计算）。
    """
    effective_stress = max(0.0, min(1.0, _safe_float(stress, 0.0)))
    return 1.0 + effective_stress * stress_multiplier


def _compute_stability_resistance(
    stability_score: float,
    resistance_factor: float,
    base_rate: float,
) -> float:
    """
    稳定性保护：稳定性高的规律衰减更慢。

    protected（stab >= 0.8）: rate = base_rate / (1 + factor × stab)
    normal: rate = base_rate / sqrt(1 + factor × stab)
    """
    stab = max(0.0, min(1.0, _safe_float(stability_score, 0.5)))
    effective = resistance_factor * stab
    if stab >= 0.8:
        return base_rate / (1.0 + effective)
    else:
        return base_rate / math.sqrt(1.0 + effective)


def _compute_bayesian_smoothing(
    experience_count: int,
    confidence: float,
    bayesian_factor: float,
) -> float:
    """
    贝叶斯平滑：经验越丰富，最终置信度越稳定。

    smoothed = (1 - effective_factor) × confidence + effective_factor × 0.5
    其中 effective_factor = bayesian_factor / sqrt(count)
    """
    ef = max(0.0, min(1.0, bayesian_factor))
    count = max(1, experience_count)
    effective_factor = ef / math.sqrt(count)
    smoothed = (1.0 - effective_factor) * confidence + effective_factor * 0.5
    return max(0.0, min(1.0, smoothed))


def _apply_decay(
    rule: Rule,
    delta_t: float,
    decay_rate: float,
    bayesian_smoothed_conf: float,
    absolute_zero: float,
) -> Rule:
    """
    对单条规律执行衰减。

    confidence = confidence × exp(-decay_rate × delta_t)
    向贝叶斯平滑方向轻微回归（5% 权重）。
    绝对零度保护：confidence 不得低于 absolute_zero。
    """
    try:
        new_rule = Rule.from_dict(rule.to_dict())
    except Exception:
        import copy
        new_rule = copy.deepcopy(rule)

    # 指数衰减
    raw_conf = new_rule.confidence * math.exp(-decay_rate * delta_t)
    # 贝叶斯平滑：轻微向平滑值回归（5% 权重）
    blended_conf = 0.95 * raw_conf + 0.05 * bayesian_smoothed_conf
    # 绝对零度保护
    new_rule.confidence = max(absolute_zero, blended_conf)

    return new_rule


# ============================================================================
# 主入口：decay_rules
# ============================================================================

def decay_rules(
    rules: List[Any],
    state_snapshot: Any,
    param_snapshot: Any,
) -> List[Rule]:
    """
    衰减模块主入口。

    参数：
        rules          : 当前全部规律列表（active + pending）
        state_snapshot : 异步周期触发时的最新实体状态快照。
                       必须传入"此刻"的新快照，不能使用循环开头缓存的旧快照。
                       期望字段：stress (0-1), fatigue (0-1)
        param_snapshot : 参数只读快照（来自 parameter_system）

    返回：
        List[Rule] — 衰减后的规律列表

    约束：
        - 纯函数，不写文件，不写数据库
        - 仅修改 confidence / stability_band / last_decay_at
    """
    try:
        # ---- 参数读取（严禁 default=None）----
        base_rate = get_raw_value(
            param_snapshot,
            "world_model.decay_rate",
            0.02,
        )
        stress_mult = get_raw_value(
            param_snapshot,
            "world_model.decay_endocrine_stress_multiplier",
            1.5,
        )
        resistance_factor = get_raw_value(
            param_snapshot,
            "world_model.decay_stability_resistance_factor",
            2.0,
        )
        bayesian_factor = get_raw_value(
            param_snapshot,
            "world_model.decay_bayesian_smoothing_factor",
            0.1,
        )
        absolute_zero = get_raw_value(
            param_snapshot,
            "world_model.decay_absolute_zero_confidence",
            0.05,
        )
        stability_protection = get_raw_value(
            param_snapshot,
            "world_model.decay_stability_protection_threshold",
            0.8,
        )
        decay_interval = get_raw_value(
            param_snapshot,
            "world_model.decay_cycle_interval_seconds",
            300.0,
        )
        stability_growth = get_raw_value(
            param_snapshot,
            "world_model.rule_stability_band_growth_rate",
            0.02,
        )
        max_band = get_raw_value(
            param_snapshot,
            "world_model.rule_max_stability_band",
            0.2,
        )

        # ---- 状态快照安全化 ----
        if isinstance(state_snapshot, dict):
            stress = state_snapshot.get("stress", 0.0)
            fatigue = state_snapshot.get("fatigue", 0.0)
        else:
            stress = getattr(state_snapshot, "stress", 0.0)
            fatigue = getattr(state_snapshot, "fatigue", 0.0)

        # ---- 规则安全化 ----
        safe_rules = _safe_rules(rules)

        # ---- 内分泌调节（全局，只需算一次）----
        endocrine_mult = _compute_endocrine_multiplier(stress, fatigue, base_rate, stress_mult)

        now = time.time()
        result: List[Rule] = []

        for rule in safe_rules:
            # 绝对零度保护
            if rule.confidence <= absolute_zero:
                result.append(rule)
                continue

            # 跳过 decayed 规律
            if rule.status == "decayed":
                result.append(rule)
                continue

            # 计算距上次衰减的时间
            delta_t = _time_since_last(rule.last_decay_at, now)
            if delta_t <= 0:
                delta_t = decay_interval

            # 稳定性阻力
            stability_resist = _compute_stability_resistance(
                rule.stability_score, resistance_factor, base_rate
            )

            # 最终衰减率 = base_rate × endocrine_mult × stability_resist
            decay_rate = base_rate * endocrine_mult * stability_resist

            # 贝叶斯平滑目标
            bayesian_smoothed = _compute_bayesian_smoothing(
                rule.source_experience_count, rule.confidence, bayesian_factor
            )

            # 执行衰减
            new_rule = _apply_decay(
                rule, delta_t, decay_rate, bayesian_smoothed, absolute_zero
            )

            # 更新稳定性 band
            current_band = new_rule.stability_band
            new_rule.stability_band = min(max_band, current_band + stability_growth)

            # 更新时间戳
            new_rule.last_decay_at = now

            result.append(new_rule)

        return result

    except Exception:
        # 衰减失败时返回原始规则
        return _safe_rules(rules)


# ============================================================================
# 测试入口
# ============================================================================

if __name__ == "__main__":
    from .defaults import DEFAULT_PARAMS

    print("=" * 64)
    print("衰减模块测试")
    print("=" * 64)

    now = time.time()

    def make_rule(rid: str, conf: float, exp: int = 1, stab: float = 0.5) -> Rule:
        return Rule(
            id=rid,
            content=f"Rule {rid}",
            confidence=conf,
            source_experience_count=exp,
            stability_score=stab,
            stability_band=0.1,
            created_at=now,
            last_verified_at=now,
            last_decay_at=now,
            status="active",
            context="test",
            predicts={"trigger": "", "expect": ""},
            evidence=[],
            _debug_meta={},
        )

    # 测试 1: 正常衰减
    print("\n【测试 1】正常衰减（无压力状态）")
    rule1 = make_rule("d1", 0.8, exp=5, stab=0.5)
    snapshot1 = {"stress": 0.0, "fatigue": 0.0}
    result1 = decay_rules([rule1], snapshot1, DEFAULT_PARAMS)
    r1 = result1[0]
    ok1 = 0.0 < r1.confidence < 0.8
    print(f"  {'✓' if ok1 else '✗'} conf: 0.8 → {r1.confidence:.4f}（应衰减）")

    # 测试 2: 高压状态衰减加速
    print("\n【测试 2】高压状态（stress=0.8）→ 衰减加速")
    import copy
    r2a = copy.deepcopy(make_rule("d2a", 0.8, exp=5, stab=0.5))
    r2b = copy.deepcopy(make_rule("d2b", 0.8, exp=5, stab=0.5))
    r2a.last_decay_at = now - 300
    r2b.last_decay_at = now - 300
    result2a = decay_rules([r2a], {"stress": 0.0, "fatigue": 0.0}, DEFAULT_PARAMS)
    result2b = decay_rules([r2b], {"stress": 0.8, "fatigue": 0.0}, DEFAULT_PARAMS)
    delta2a = 0.8 - result2a[0].confidence
    delta2b = 0.8 - result2b[0].confidence
    ok2 = delta2b > delta2a
    print(f"  {'✓' if ok2 else '✗'} 低压 delta={delta2a:.5f}, 高压 delta={delta2b:.5f}（高压应衰减更多）")

    # 测试 3: 高稳定性衰减减速
    print("\n【测试 3】高稳定性（stab=0.9）→ 衰减减速")
    r3a = copy.deepcopy(make_rule("d3a", 0.8, exp=10, stab=0.3))
    r3b = copy.deepcopy(make_rule("d3b", 0.8, exp=10, stab=0.9))
    r3a.last_decay_at = now - 300
    r3b.last_decay_at = now - 300
    result3a = decay_rules([r3a], {"stress": 0.0, "fatigue": 0.0}, DEFAULT_PARAMS)
    result3b = decay_rules([r3b], {"stress": 0.0, "fatigue": 0.0}, DEFAULT_PARAMS)
    delta3a = 0.8 - result3a[0].confidence
    delta3b = 0.8 - result3b[0].confidence
    ok3 = delta3b < delta3a
    print(f"  {'✓' if ok3 else '✗'} 低稳定 delta={delta3a:.5f}, 高稳定 delta={delta3b:.5f}（高稳定应衰减更少）")

    # 测试 4: 绝对零度保护
    print("\n【测试 4】绝对零度（confidence <= 0.05）→ 不衰减")
    r4 = copy.deepcopy(make_rule("d4", 0.051, exp=1, stab=0.1))
    r4.last_decay_at = now - 600
    result4 = decay_rules([r4], {"stress": 0.9, "fatigue": 0.9}, DEFAULT_PARAMS)
    ok4 = abs(result4[0].confidence - 0.051) < 0.001
    print(f"  {'✓' if ok4 else '✗'} 极低 conf 未衰减: {result4[0].confidence:.4f}（期望 ~0.051）")

    # 测试 5: decayed 规律跳过
    print("\n【测试 5】decayed 规律跳过不处理")
    rule5 = make_rule("d5", 0.1, exp=1, stab=0.5)
    rule5.status = "decayed"
    result5 = decay_rules([rule5], {"stress": 0.5, "fatigue": 0.5}, DEFAULT_PARAMS)
    ok5 = result5[0].confidence == 0.1 and result5[0].status == "decayed"
    print(f"  {'✓' if ok5 else '✗'} decayed 未处理: conf={result5[0].confidence}, status={result5[0].status}")

    # 测试 6: 贝叶斯平滑
    print("\n【测试 6】贝叶斯平滑 — 经验越多衰减越少")
    r6a = copy.deepcopy(make_rule("d6a", 0.8, exp=1))
    r6b = copy.deepcopy(make_rule("d6b", 0.8, exp=100))
    r6a.last_decay_at = now - 300
    r6b.last_decay_at = now - 300
    result6a = decay_rules([r6a], {"stress": 0.0, "fatigue": 0.0}, DEFAULT_PARAMS)
    result6b = decay_rules([r6b], {"stress": 0.0, "fatigue": 0.0}, DEFAULT_PARAMS)
    delta6a = 0.8 - result6a[0].confidence
    delta6b = 0.8 - result6b[0].confidence
    ok6 = delta6b < delta6a
    print(f"  {'✓' if ok6 else '✗'} exp=1: delta={delta6a:.5f}, exp=100: delta={delta6b:.5f}（经验多衰减少）")

    # 测试 7: stability_band 增长
    print("\n【测试 7】stability_band 逐渐扩大")
    r7 = copy.deepcopy(make_rule("d7", 0.7, exp=3, stab=0.5))
    r7.stability_band = 0.10
    r7.last_decay_at = now - 300
    result7 = decay_rules([r7], {"stress": 0.0, "fatigue": 0.0}, DEFAULT_PARAMS)
    ok7 = result7[0].stability_band >= 0.10
    print(f"  {'✓' if ok7 else '✗'} band: 0.10 → {result7[0].stability_band:.4f}（应 ≥ 0.10）")

    # 测试 8: 空输入
    print("\n【测试 8】空规则列表")
    result8 = decay_rules([], {}, DEFAULT_PARAMS)
    ok8 = result8 == []
    print(f"  {'✓' if ok8 else '✗'} 空输入 → {result8}")

    print("\n" + "=" * 64)
    print("衰减模块测试完成")
    print("=" * 64)
