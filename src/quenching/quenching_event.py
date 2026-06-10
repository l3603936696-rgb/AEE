"""
Quenching Event — 消力事件数据层

含 QuenchingEvent dataclass 和 QuenchingJournal 跨通道消力日志。
"""

import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


@dataclass
class QuenchingEvent:
    """单次消力事件（跨通道统一记录）。"""
    channel: str           # expression / decision / social / behavioral / temporal / structural
    tick: int
    timestamp: float
    delta_unresolved: float      # 本轮 unresolved 实际下降量
    delta_loneliness: float      # loneliness 下降量
    delta_stress: float          # stress 下降量
    delta_fatigue: float         # fatigue 下降量（行为消力用）
    efficiency: float            # 消力效率 ∈ [0, 1]
    context: Dict[str, Any]


class QuenchingJournal:
    """
    跨通道消力日志。
    记录每条通道每次贡献，供效率分析和注意场回拉。
    """
    def __init__(self, maxlen: int = 200):
        self._events: List[QuenchingEvent] = []
        self._maxlen = maxlen

    def record(self, event: QuenchingEvent):
        self._events.append(event)
        if len(self._events) > self._maxlen:
            self._events = self._events[-self._maxlen:]

    def channel_efficiency(self, channel: str, window: int = 50) -> float:
        """某通道最近 N 条记录的平均效率。"""
        recent = [e for e in self._events[-window:] if e.channel == channel]
        if not recent:
            return 0.0
        return sum(e.efficiency for e in recent) / len(recent)

    def total_quenched(self, window: int = 50) -> float:
        """最近 N 条记录的总 Δunresolved。"""
        return sum(e.delta_unresolved for e in self._events[-window:])

    def to_list(self) -> List[Dict]:
        return [
            {
                "channel": e.channel,
                "tick": e.tick,
                "delta_unresolved": round(e.delta_unresolved, 4),
                "efficiency": round(e.efficiency, 4),
            }
            for e in self._events[-50:]
        ]
