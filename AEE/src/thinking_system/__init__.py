"""
Thinking System Module (思考系统)

src/thinking_system/

组件：
    thinking_system    — 受限思考主引擎（模板 + 感质调制 + 注意力调制）
    covariance_tracker — 跨 tick 协方差追踪器（分析齿轮·关联层）
    mental_simulation  — 心智模拟（分析齿轮·因果层）
"""

from .thinking_system import think, ThoughtPacket, THOUGHT_PACKET_EMPTY
from .covariance_tracker import CovarianceTracker
from .mental_simulation import simulate_suggestions, compute_analysis_willingness

__all__ = [
    "think", "ThoughtPacket", "THOUGHT_PACKET_EMPTY",
    "CovarianceTracker",
    "simulate_suggestions", "compute_analysis_willingness",
]
