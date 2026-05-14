"""
World Model Update — 模块入口

从实体的亲身经历（迭代快照和对话日志）中提炼有区分度的因果规律，
对已有规律进行验证、衰减和合并。

执行顺序（异步反思周期）：
    加载 → 归纳 → 合并 → 衰减 → 验证 → 持久化

持久化由外层调度器负责。

子模块：
    rules.py   — 规律和快照数据结构
    defaults.py — 默认参数和 get_param
    induct.py  — 归纳（v11.2 预测误差驱动学习）
    verify.py  — 验证（贝叶斯学习率）
    decay.py   — 衰减（内分泌调节 + 稳定性保护）
    merge.py   — 合并（O(N) 增量嵌入相似度）
    core.py    — 编排层 + 外部调度接口

resolve.py  — stress 生命周期：can_resolve 判断 surprise 是否被规则覆盖
"""

from .rules import Rule, Snap, Evidence, Predicts
from .defaults import DEFAULT_PARAMS, get_param
from .resolve import can_resolve, mark_unresolvable
from .core import (
    run_update_cycle,
    induct_only,
    merge_only,
    decay_only,
    verify_only,
    CycleStats,
)

# 四个核心纯函数（供外层调度器直接调用）
from . import induct as _induct
from . import verify as _verify
from . import decay as _decay
from . import merge as _merge

induct_rules = _induct.induct_rules
predict_action_effects = _induct.predict_action_effects
verify_pending = _verify.verify_pending
decay_rules = _decay.decay_rules
merge_rules = _merge.merge_rules

# 维度维护成本（奥卡姆剃刀动力学）
from .dimension_cost import compute_dimension_values, dimension_decay_modifier

# 矛盾检测
from .contradiction import detect_contradictions

__all__ = [
    # 数据结构
    "Rule",
    "Snap",
    "Evidence",
    "Predicts",
    # 核心纯函数
    "induct_rules",
    "predict_action_effects",
    "verify_pending",
    "decay_rules",
    "merge_rules",
    # stress 生命周期
    "can_resolve",
    "mark_unresolvable",
    # 编排层
    "run_update_cycle",
    "induct_only",
    "merge_only",
    "decay_only",
    "verify_only",
    "CycleStats",
    # 配置
    "DEFAULT_PARAMS",
    "get_param",
    # 维度维护成本
    "compute_dimension_values",
    "dimension_decay_modifier",
    # 矛盾检测
    "detect_contradictions",
]
