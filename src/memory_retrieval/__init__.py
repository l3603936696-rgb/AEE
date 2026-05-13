"""
Memory Retrieval — 双通道记忆检索系统

双通道：
    mainline : 基于当前输入语义，从 episodes_db 检索相关历史经验
    branch   : 后台随机采样，计算契合度，浮现意外联想
"""

from .mainline import mainline_retrieval, get_recent_summaries
from .branch import branch_retrieval
from .state_modulation import compute_state_sensitive_weight
from .summary import generate_turn_summary

__all__ = [
    "mainline_retrieval",
    "get_recent_summaries",
    "branch_retrieval",
    "compute_state_sensitive_weight",
    "generate_turn_summary",
]
