"""参数漂移注册表 — 定义所有可漂移参数的元数据。"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class DriftableParam:
    """单个可漂移参数的元数据。"""
    path: str               # 参数路径，例 "personality.trust_threshold"
    tier: int               # 漂移层级：1=表层, 2=中层, 3=深层
    baseline_default: float # 出厂默认值（首次启动用）
    min_value: float        # 允许漂移的下界
    max_value: float        # 允许漂移的上界
    asymmetry: float = 1.5  # 负方向漂移速率倍数（>1 = 受伤比恢复快）


# ---- 漂移层级 → EMA 窗口（tick 数） ----
TIER_WINDOWS = {
    1: 86_400,       # 表层：1 天
    2: 604_800,      # 中层：7 天
    3: 3_888_000,    # 深层：45 天
}


def tier_alpha(tier: int) -> float:
    """返回指定层级的 EMA 平滑系数。"""
    window = TIER_WINDOWS.get(tier, TIER_WINDOWS[2])
    return 1.0 / window


# ---- 漂移速率基数（每 tick 最大漂移量） ----
TIER_DRIFT_RATES = {
    1: 1e-5,    # 表层：每 tick 最多漂移 0.00001
    2: 2e-6,    # 中层：每 tick 最多漂移 0.000002
    3: 5e-7,    # 深层：每 tick 最多漂移 0.0000005
}


REGISTRY: Dict[str, DriftableParam] = {}


def register(param: DriftableParam) -> None:
    """注册一个可漂移参数。"""
    REGISTRY[param.path] = param


def get_driftable(path: str) -> Optional[DriftableParam]:
    """查询参数是否可漂移，返回元数据。"""
    return REGISTRY.get(path)


def list_all() -> list:
    """返回所有已注册的可漂移参数。"""
    return list(REGISTRY.values())


# ---- 初始注册 ----
_TIER1 = [
    DriftableParam("llm.temperature",                    1, 0.7,  0.1, 1.5),
    DriftableParam("decision.fallback_priority",         1, 0.0, -0.5, 1.0),
]

_TIER2 = [
    DriftableParam("personality.trust_threshold",        2, 0.5,  0.05, 0.95),
    DriftableParam("personality.rejection_sensitivity",  2, 0.3,  0.05, 0.95),
    DriftableParam("personality.social_risk_weight",     2, 0.3,  0.05, 0.95),
    DriftableParam("decision.survival_override_threshold", 2, 0.85, 0.5, 0.99),
    DriftableParam("web_search.info_hunger_threshold",   2, 0.6,  0.2, 0.95),
]

_TIER3 = [
    DriftableParam("personality.introverted_bias",       3, 0.2,  0.0, 0.9, asymmetry=2.0),
    DriftableParam("personality.extroverted_bias",       3, 0.1,  0.0, 0.9, asymmetry=2.0),
    DriftableParam("personality.novelty_reward",         3, 0.5,  0.05, 0.95, asymmetry=1.8),
    DriftableParam("personality.recovery_rate",          3, 1.0,  0.1, 2.0, asymmetry=2.0),
]

for _p in _TIER1 + _TIER2 + _TIER3:
    register(_p)
