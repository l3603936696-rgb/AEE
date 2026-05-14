"""可观测性模块 — 结构化事件日志。"""

from .events import (
    DriftEvent,
    RuleLifecycleEvent,
    ShatteringEvent,
    TensionSnapshot,
)
from .event_log import emit_event, read_events, clear_events

__all__ = [
    "DriftEvent",
    "RuleLifecycleEvent",
    "ShatteringEvent",
    "TensionSnapshot",
    "emit_event",
    "read_events",
    "clear_events",
]
