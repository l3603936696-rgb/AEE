"""
BehaviorProfiler — 行为剖面 + 语言丰度指标（v7.0）

职责：
    - 维护行为历史记录，供行为签名和观测分析使用
    - 集成 LinguisticAbundanceMonitor，监测语言丰度
    - 在低丰度时触发热控升温

本文件是行为观测层的统一入口。
"""

from typing import Any, Dict, List, Optional

from ..language_system.abundance_monitor import LinguisticAbundanceMonitor


class BehaviorProfiler:
    """
    行为剖面 + 语言丰度监测器。

    维护近期行为历史，提供行为签名统计和语言丰度监测。
    """

    def __init__(self, window: int = 100) -> None:
        # 行为历史（action_type 序列）
        self._action_history: List[str] = []
        self._window = window

        # 语言丰度监测（委托给 LinguisticAbundanceMonitor）
        self._abundance_monitor = LinguisticAbundanceMonitor(window=window)

    # -------------------------------------------------------------------------
    # 行为记录
    # -------------------------------------------------------------------------

    def record_action(self, action_type: str, expression: Optional[str] = None) -> None:
        """
        记录一轮行为。

        参数：
            action_type: 行为类型
            expression: 本轮的表达（用于丰度监测）
        """
        if action_type:
            self._action_history.append(action_type)
            if len(self._action_history) > self._window:
                self._action_history = self._action_history[-self._window:]

        # 同时记录表达（用于语言丰度）
        if expression:
            self._abundance_monitor.record(expression)

    # -------------------------------------------------------------------------
    # 行为统计
    # -------------------------------------------------------------------------

    def get_action_distribution(self) -> Dict[str, int]:
        """返回行为类型分布（计数）。"""
        from collections import Counter
        counts = Counter(self._action_history)
        return dict(counts)

    def get_most_common_action(self) -> Optional[str]:
        """返回最常见的行为类型。"""
        dist = self.get_action_distribution()
        if not dist:
            return None
        return max(dist, key=dist.get)

    # -------------------------------------------------------------------------
    # 语言丰度（委托给 LinguisticAbundanceMonitor）
    # -------------------------------------------------------------------------

    def compute丰度(self) -> float:
        """计算语言丰度。"""
        return self._abundance_monitor.compute丰度()

    def should_heat_up(self) -> bool:
        """判断是否应该升温。"""
        return self._abundance_monitor.should_heat_up()

    def is_low丰度(self) -> bool:
        """返回当前是否处于低丰度状态。"""
        return self._abundance_monitor.is_low丰度()

    def check丰度_and_notify(
        self,
        thermal_controller: Any,
        param_snapshot: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        检查丰度并在必要时通知热控升温。

        参数：
            thermal_controller: ThermalController 实例
            param_snapshot   : 参数快照

        返回：
            True 表示触发了升温
        """
        return self._abundance_monitor.check_and_notify(thermal_controller, param_snapshot)

    def get丰度_stats(self) -> Dict[str, Any]:
        """返回丰度统计。"""
        return self._abundance_monitor.get_stats()

    # -------------------------------------------------------------------------
    # 序列化
    # -------------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """序列化。"""
        return {
            "action_history": self._action_history,
            "window": self._window,
            "abundance": self._abundance_monitor.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BehaviorProfiler":
        """从 dict 恢复。"""
        window = int(data.get("window", 100))
        profiler = cls(window=window)
        profiler._action_history = list(data.get("action_history", []))
        if "abundance" in data:
            profiler._abundance_monitor = LinguisticAbundanceMonitor.from_dict(data["abundance"])
        return profiler
