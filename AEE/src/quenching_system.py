"""
Quenching System — 六通道消力框架（v11.5）

向后兼容入口。
实际实现在 src.quenching 子包：
    src/quenching/__init__.py       — 主入口 apply_all_quenching
    src/quenching/quenching_event.py  — QuenchingEvent + QuenchingJournal
    src/quenching/quenching_channels.py — 6 条消力通道
"""

from .quenching import (
    apply_all_quenching,
    QuenchingEvent,
    QuenchingJournal,
    expression_quenching,
    temporal_quenching,
    decision_quenching,
    social_quenching,
    behavioral_quenching,
    structural_quenching,
)

__all__ = [
    "apply_all_quenching",
    "QuenchingEvent",
    "QuenchingJournal",
    "expression_quenching",
    "temporal_quenching",
    "decision_quenching",
    "social_quenching",
    "behavioral_quenching",
    "structural_quenching",
]
