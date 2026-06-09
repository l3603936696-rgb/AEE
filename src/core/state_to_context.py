"""
StateToContext — 状态 → 处境描述生成器（v4 扩展版）

将 EntityCore 的数字状态翻译为第一人称处境语言，
作为 LLM system_prompt 的动态素材。

重构后结构：
    - state_to_context_data.py     : 所有静态数据（bands、冲突规则、常量）
    - state_to_context_helpers.py  : 所有函数实现
    - state_to_context.py          : 入口重导出（向后兼容）
"""

from .state_to_context_data import (
    SYSTEM_PROMPT_FIXED,
    SYSTEM_PROMPT_CONSTRAINTS,
)
from .state_to_context_helpers import (
    generate_context_description,
    build_system_prompt,
    derive_rendering_params,
)

__all__ = [
    "SYSTEM_PROMPT_FIXED",
    "SYSTEM_PROMPT_CONSTRAINTS",
    "generate_context_description",
    "build_system_prompt",
    "derive_rendering_params",
]
