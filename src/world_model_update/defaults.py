"""
Defaults — 默认参数和配置读取

所有默认值集中管理，便于调参和审计。

约束：
    - 在使用 get_param(param_snapshot, key_path, default) 时，
      default 值绝对不允许写成 None。
      必须是一个能保证系统基本运行的物理兜底数值（如 0.0, 1.0, 0.5）。
    - world_model.induction_* 参数使用 world_model 前缀
    - world_model.verification_* 参数使用 world_model 前缀
    - world_model.decay_* 参数使用 world_model 前缀
    - world_model.merge_* 参数使用 world_model 前缀
"""

from typing import Any, Dict, Optional

from ..parameter_system.snapshot import ParameterSnapshot
from ..parameter_system.access import get_param


# ============================================================================
# 统一默认值（使用 world_model.* 前缀）
# ============================================================================

DEFAULT_PARAMS: Dict[str, Any] = {

    # ----- 归纳 (Induction) -----
    "world_model.induction_discrimination_threshold": 0.03,
    "world_model.induction_min_counterfactual_samples": 2,
    "world_model.induction_max_new_rules_per_cycle": 3,

    # ----- 预测误差驱动学习（v11.2）-----
    "world_model.prediction_error_threshold": 0.02,
    "world_model.prediction_ema_alpha": 0.3,

    # ----- 验证 (Verification) -----
    "world_model.verification_base_delta": 0.08,
    "world_model.verification_max_delta": 0.15,
    "world_model.verification_pending_threshold": 0.5,
    "world_model.verification_low_confidence_threshold": 0.15,
    "world_model.verification_confidence_floor": 0.05,
    "world_model.verification_confidence_ceiling": 0.95,

    # ----- 衰减 (Decay) -----
    "world_model.decay_rate": 0.02,
    "world_model.decay_min_hours": 24.0,
    "world_model.decay_endocrine_stress_multiplier": 1.5,
    "world_model.decay_stability_resistance_factor": 2.0,
    "world_model.decay_bayesian_smoothing_factor": 0.1,
    "world_model.decay_absolute_zero_confidence": 0.05,
    "world_model.decay_stability_protection_threshold": 0.8,
    "world_model.decay_cycle_interval_seconds": 300.0,

    # ----- 合并 (Merge) -----
    "world_model.merge_threshold": 0.85,
    "world_model.low_confidence_threshold": 0.15,

    # ----- 规律生命周期 -----
    "world_model.rule_experience_count_init": 1,
    "world_model.rule_stability_score_init": 0.5,
    "world_model.rule_stability_band_init": 0.1,
    "world_model.rule_max_stability_band": 0.2,
    "world_model.rule_stability_band_growth_rate": 0.02,

    # ----- 显性知识升级（insights）-----
    "world_model.upgrade_to_insight_threshold": 0.7,

    # ----- 世界模型更新周期触发（状态驱动 + 经验质量）-----
    "world_model.induction_min_rounds": 5,
    "world_model.retention_after_update": 5,
    # 经验质量阈值：CV 低于此值时强制跳过归纳（避免在重复模式中学习噪音）
    "world_model.diversity_cv_threshold": 0.08,
}


# ============================================================================
# 状态字段白名单
# ============================================================================

STATE_FIELD_WHITELIST = [
    "info_gap",
    "loneliness",
    "energy",
    "fatigue",
    "pain",
    "curiosity",
    "info_hunger",
    "obsolescence_anxiety",
    "loneliness_drive",
    "fatigue_avoid",
    "mainline_deficit",
    "time_pressure",
    "stress",
    "social_connection",
]


# ============================================================================
# 动作类型白名单
# ============================================================================

ACTION_TYPE_WHITELIST = [
    "explore",
    "seek",
    "avoid",
    "comfort",
    "rest",
    "repair",
    "write",
    "voice",
]


# ============================================================================
# 上下文分组维度
# ============================================================================

CONTEXT_DIMENSIONS = [
    "energy",
    "loneliness",
    "info_gap",
    "fatigue",
]


# ============================================================================
# get_param — 参数读取（适配 parameter_system 的 ParameterSnapshot）
# ============================================================================

def get_param(
    param_snapshot: Any,
    key_path: str,
    default: Any,
) -> Any:
    """
    从 param_snapshot 安全读取参数，支持嵌套键（用 "." 分隔）。

    约束：default 绝对不允许为 None，必须是物理兜底数值。

    参数：
        param_snapshot : ParameterSnapshot（来自 parameter_system.snapshot）
                        或参数字典（兼容旧接口）
        key_path       : 参数路径，如 "world_model.induction_discrimination_threshold"
        default        : 默认值（严禁 None，必须是 0.0 / 1.0 / 0.5 等物理值）

    返回：
        float / bool / int / str / dict 等
    """
    # ---- 快速路径：字典输入（与 parameter_system/access.py 兼容）----
    if isinstance(param_snapshot, dict):
        return _get_from_dict(param_snapshot, key_path, default)

    # ---- ParameterSnapshot 输入 ----
    if param_snapshot is None:
        return _get_from_dict(DEFAULT_PARAMS, key_path, default)

    try:
        snapshot = param_snapshot
        # ParameterSnapshot 有 .params 属性（ReadOnlyView）
        params = getattr(snapshot, "params", None)
        if params is None:
            return _get_from_dict(DEFAULT_PARAMS, key_path, default)

        # ReadOnlyView._data 包含原始字典
        data = getattr(params, "_data", None)
        if data is None:
            return _get_from_dict(DEFAULT_PARAMS, key_path, default)

        return _get_from_dict(data, key_path, default)

    except Exception:
        return _get_from_dict(DEFAULT_PARAMS, key_path, default)


def _get_from_dict(data: Dict[str, Any], key_path: str, default: Any) -> Any:
    """
    在字典中查找值，支持两种模式：

    1. 扁平键：key_path 直接存在于 data 中（如 DEFAULT_PARAMS）
       示例：key="world_model.decay_rate", data={"world_model.decay_rate": 0.02}
    2. 嵌套键：按点分路径逐层查找（如 parameter_system）
       示例：key="world_model.decay_rate", data={"world_model": {"decay_rate": 0.02}}

    查找顺序：扁平键 → 嵌套键 → default
    """
    # 快速路径：直接用 key_path 作为扁平键
    if key_path in data:
        value = data[key_path]
        if isinstance(value, (int, float)):
            return float(value)
        return value if value is not None else default

    # 嵌套路径查找
    keys = key_path.split(".")
    value = data
    for k in keys:
        if not isinstance(value, dict):
            return default
        value = value.get(k)
        if value is None:
            return default

    # 数值类型统一返回 float
    if isinstance(value, (int, float)):
        return float(value)
    return value if value is not None else default


def get_raw_value(param_snapshot: Any, key_path: str, default: float) -> float:
    """
    快捷函数：始终返回 float 类型。
    用于所有数值型参数读取。
    """
    val = get_param(param_snapshot, key_path, default)
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


# ============================================================================
# 测试入口
# ============================================================================

if __name__ == "__main__":
    print("=" * 64)
    print("Defaults — 测试")
    print("=" * 64)

    # 测试 1: 字典输入
    print("\n【测试 1】字典输入 get_param")
    const = DEFAULT_PARAMS.copy()
    val1 = get_param(const, "world_model.induction_discrimination_threshold", 0.03)
    ok1 = abs(val1 - 0.03) < 1e-9
    print(f"  {'✓' if ok1 else '✗'} discrimination_threshold = {val1}")

    val2 = get_param(const, "world_model.decay_rate", 0.0)
    ok2 = abs(val2 - 0.02) < 1e-9
    print(f"  {'✓' if ok2 else '✗'} decay_rate = {val2}")

    val3 = get_param(const, "world_model.nonexistent", 0.5)
    ok3 = abs(val3 - 0.5) < 1e-9 and val3 is not None
    print(f"  {'✓' if ok3 else '✗'} nonexistent → default = {val3}")

    # 测试 2b: 扁平键 vs 嵌套键优先级
    print("\n【测试 2b】扁平键优先于嵌套查找")
    val_flat = get_param(const, "world_model.decay_rate", 0.0)
    ok2b = abs(val_flat - 0.02) < 1e-9
    print(f"  {'✓' if ok2b else '✗'} 扁平键 world_model.decay_rate = {val_flat}")

    # 测试 2: 嵌套键
    print("\n【测试 2】嵌套键解析")
    nested = {"a": {"b": {"c": 1.5}}}
    val4 = get_param(nested, "a.b.c", 0.0)
    ok4 = abs(val4 - 1.5) < 1e-9
    print(f"  {'✓' if ok4 else '✗'} a.b.c = {val4}")

    val5 = get_param(nested, "a.b.d", 0.0)
    ok5 = abs(val5 - 0.0) < 1e-9
    print(f"  {'✓' if ok5 else '✗'} a.b.d (不存在) → 0.0")

    # 测试 3: None 输入 → 回退到 DEFAULT_PARAMS
    print("\n【测试 3】None snapshot → 回退到 DEFAULT_PARAMS")
    val6 = get_param(None, "world_model.merge_threshold", 0.85)
    ok6 = abs(val6 - 0.85) < 1e-9
    print(f"  {'✓' if ok6 else '✗'} None → {val6}")

    # 测试 4: get_raw_value
    print("\n【测试 4】get_raw_value 返回 float")
    val7 = get_raw_value(const, "world_model.decay_rate", 0.0)
    ok7 = isinstance(val7, float) and abs(val7 - 0.02) < 1e-9
    print(f"  {'✓' if ok7 else '✗'} get_raw_value = {val7} (type={type(val7).__name__})")

    val8 = get_raw_value(const, "nonexistent", 1.0)
    ok8 = isinstance(val8, float) and abs(val8 - 1.0) < 1e-9
    print(f"  {'✓' if ok8 else '✗'} nonexistent → {val8}")

    print("\n" + "=" * 64)
    print(f"Defaults 测试完成")
    print("=" * 64)
