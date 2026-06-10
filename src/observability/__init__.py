"""可观测性模块 — 结构化事件日志 + 模块可观测性层。"""

from .events import (
    DriftEvent,
    RuleLifecycleEvent,
    ShatteringEvent,
    TensionSnapshot,
)
from .event_log import emit_event, read_events, clear_events
from .registry import (
    get_registry,
    observe,
    record_failure,
    record_success,
    observe_block,
    classify_llm_result,
)
from .llm_wrapper import create_wrapped_llm, create_wrapped_llm_chain

__all__ = [
    # 事件
    "DriftEvent",
    "RuleLifecycleEvent",
    "ShatteringEvent",
    "TensionSnapshot",
    "emit_event",
    "read_events",
    "clear_events",
    # 模块可观测性
    "get_registry",
    "observe",
    "record_failure",
    "record_success",
    "observe_block",
    "classify_llm_result",
    "create_wrapped_llm",
    "create_wrapped_llm_chain",
]
