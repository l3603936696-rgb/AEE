"""
Core — 细菌主体核心模块

包含：
    entity_core       : 细菌主体状态容器（跨轮次持久化）
    somatic_signals   : 感质信号与 DoS 保护
    emergent_behavior : 行为涌现机制
    state_to_context  : 状态 → 处境描述生成器
"""

from .entity_core import EntityCore
from .somatic_signals import (
    SomaticSignals,
    DosProtector,
    compute_somatic_intensity,
    compute_overall_tone,
    dominant_feeling,
)
from .emergent_behavior import (
    EmergentBehavior,
    compute_tension,
    compute_tension_raw,
    emerge_behavior,
    derive_rendering_params,
)
from .state_to_context import (
    build_system_prompt,
    generate_context_description,
)

__all__ = [
    "EntityCore",
    "SomaticSignals",
    "DosProtector",
    "compute_somatic_intensity",
    "compute_overall_tone",
    "dominant_feeling",
    "EmergentBehavior",
    "compute_tension",
    "compute_tension_raw",
    "emerge_behavior",
    "build_system_prompt",
    "generate_context_description",
]
