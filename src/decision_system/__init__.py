"""
Decision System — 决策系统（九模块并行感知 + 决策装配）

功能：
    汇聚驱动力场、情绪、记忆、世界模型等多维信号，
    通过九个子模块并行感知，直接修改实体状态，
    最终装配出决策（action_type、target、priority）。

核心函数：
    perceive_all(entity_core, semantic_packet, concept_tags, wm_context, drive_vector, ...)
        → 修改 entity_core 的状态变量（approach_drive, avoid_drive, somatic_tone 等）
        → 返回 None（in-place 修改）

子模块注册表（MODULE_REGISTRY）：
    SituationAssessment  → approach_drive
    ContextAwareness     → loneliness, approach_drive, avoid_drive, danger_level
    ThoughtIntegration   → approach_drive, avoid_drive
    SignalActivation    → avoid_drive, approach_drive, somatic_tone
    MainlineConstraint  → avoid_drive, approach_drive
    TemporalPressure    → fatigue, approach_drive
    SelfState          → avoid_drive, somatic_tone
    Preference          → approach_drive, avoid_drive
    WorldModel          → curiosity, approach_drive, avoid_drive
    WebSearch           → （无直接修改）
    ToolSelfCheck       → （无直接修改）

设计原则：
    - 连续信号，无 if-else 硬阈值
    - 模块注册表驱动，动态加载（增删文件即生效）
    - 单模块失败不影响其他模块
"""

from .decision_system import perceive_all, DEFAULT_PARAMS, MODULE_REGISTRY
from .decision_comparator import DecisionComparator, compare_signals
from .submodules.base import DriveSignal

__all__ = [
    "perceive_all",
    "DEFAULT_PARAMS",
    "MODULE_REGISTRY",
    "DecisionComparator",
    "compare_signals",
    "DriveSignal",
]
