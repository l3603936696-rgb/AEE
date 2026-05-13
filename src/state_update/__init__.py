"""
State Update Module (状态更新引擎)

职责：计算内部状态的自然衰减、行为反馈和状态间的相互作用。
是实体产生"身体感"和"状态惯性"的物理底座。

子模块：
    - update_engine.py : 状态更新主引擎
"""

from .update_engine import update_state, reset_info_queue, get_info_queue
from .info_queue import InfoQueue
from .compute_load import compute_queue_trigger_rest
from .compute_coherence import compute_coherence, append_delta as append_coherence_delta
from .compute_connection import compute_connection_depth, compute_loneliness_target

__all__ = [
    "update_state",
    "reset_info_queue",
    "get_info_queue",
    "InfoQueue",
    "compute_queue_trigger_rest",
    "compute_coherence",
    "append_coherence_delta",
    "compute_connection_depth",
    "compute_loneliness_target",
]
