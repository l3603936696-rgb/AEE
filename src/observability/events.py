"""可观测性事件定义 — 结构化日志的数据模型。"""

from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional
import time


@dataclass
class DriftEvent:
    """参数漂移记录。每次参数值因风化而改变时 emit。"""
    tick: int
    param_path: str
    old_value: float
    new_value: float
    drift_source: str            # "weathering" | "shattering" | "manual"
    signal_strength: float       # 驱动漂移的信号强度
    baseline: float              # 当前 EMA baseline 值
    timestamp: float = field(default_factory=time.time)
    event_type: str = field(default="drift", init=False)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RuleLifecycleEvent:
    """规律生命周期事件。创建/合并/衰减/崩塌/升级时 emit。"""
    tick: int
    rule_id: str
    lifecycle_type: str          # "created" | "merged" | "decayed" | "shattered" | "promoted" | "demoted"
    confidence_before: float
    confidence_after: float
    cause: str                   # 人类可读原因
    domain: str = "general"      # 规律所属域
    related_rules: List[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    event_type: str = field(default="rule_lifecycle", init=False)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ShatteringEvent:
    """崩塌事件。高置信规律受到挑战时 emit（无论结果）。"""
    tick: int
    rule_id: str
    rule_content: str            # 规律内容摘要
    shattering_force: float      # 崩塌力 = conf_drop × inertia × contradiction × emotion
    update_resistance: float    # 抵抗力 = identity_binding + attractor_strength + sunk_cost
    outcome: str                 # "collapsed" | "resisted" | "suppressed"
    confidence_before: float
    confidence_after: float
    suppressed_tension_after: float
    affected_params: List[str] = field(default_factory=list)
    force_components: Dict[str, float] = field(default_factory=dict)
    resistance_components: Dict[str, float] = field(default_factory=dict)
    domain: str = "general"
    timestamp: float = field(default_factory=time.time)
    event_type: str = field(default="shattering", init=False)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TensionSnapshot:
    """张力快照。定期（每 N tick）emit 一次系统张力状态。"""
    tick: int
    total_tension: float
    suppressed_tension: float              # 累积压抑张力
    active_contradictions: int             # 活跃矛盾对数量
    contradiction_pairs: List[Dict[str, Any]] = field(default_factory=list)
    parameter_drift_summary: Dict[str, float] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    event_type: str = field(default="tension_snapshot", init=False)

    def to_dict(self) -> dict:
        return asdict(self)
