"""
LinguisticAbundanceMonitor — 语言丰度监测（v7.0）

职责：
    - 监测语言策略库的活跃程度
    - 计算公式：丰度 = 策略库活跃条目数 / 单位时间内重复率
    - 丰度 < 阈值时，触发 thermal.force_heat() 强制升温

设计文档定义：
    LinguisticAbundance = unique_expressions / repeat_rate
        repeat_rate = 1 - (unique_count / total_count)

等价实现：
    abundance = unique / max(1, repeat_rate * total)
           ≈ unique / max(1, total - unique)
           ≈ unique / max(1, duplicate_count)
"""

import logging
from collections import deque
from typing import Any, Deque, Dict, List, Optional

logger = logging.getLogger(__name__)


class LinguisticAbundanceMonitor:
    """
    语言丰度监测器。

    属性：
        _strategy_history: 策略表达历史队列（不持久化，每轮重建）
        _window        : 监测窗口大小（默认 100）
        _threshold     : 丰度下限阈值
        _is_low丰度   : 当前是否处于低丰度状态
    """

    def __init__(
        self,
        window: int = 100,
        low_threshold: float = 0.60,
    ) -> None:
        self._window = window
        self._threshold = low_threshold
        self._strategy_history: Deque[str] = deque(maxlen=window)
        self._is_low丰度 = False
        self._low丰度_streak = 0  # 连续低丰度轮数

    # -------------------------------------------------------------------------
    # 记录
    # -------------------------------------------------------------------------

    def record(self, expression: str) -> None:
        """记录一轮的表达。"""
        if expression:
            self._strategy_history.append(expression.strip())

    # -------------------------------------------------------------------------
    # 丰度计算
    # -------------------------------------------------------------------------

    def compute丰度(self) -> float:
        """
        计算当前语言丰度。

        丰度 = unique_expressions / total

        含义：
            - 全部重复 → unique=1, total=100 →丰度=0.01（极度匮乏）
            - 全部不同 → unique=total →丰度=1.0（极度丰富）
        """
        recent: List[str] = list(self._strategy_history)
        if not recent:
            return 1.0

        total = len(recent)
        unique = len(set(recent))

        return unique / max(1, total)

    def should_heat_up(self,丰度: Optional[float] = None) -> bool:
        """
        判断是否应该升温。

        参数：
           丰度: 丰度值（若为 None，则重新计算）

        返回：
            True 表示丰度低于阈值，需要升温
        """
        if 丰度 is None:
            丰度 = self.compute丰度()

        self._is_low丰度 = 丰度 < self._threshold

        if self._is_low丰度:
            self._low丰度_streak += 1
        else:
            self._low丰度_streak = 0

        # 连续 3 轮低丰度才触发（防止误触发）
        return self._low丰度_streak >= 3

    def is_low丰度(self) -> bool:
        """返回当前是否处于低丰度状态。"""
        return self._is_low丰度

    def get_low丰度_streak(self) -> int:
        """返回连续低丰度轮数。"""
        return self._low丰度_streak

    # -------------------------------------------------------------------------
    # 与热控联动
    # -------------------------------------------------------------------------

    def check丰度_and_notify(
        self,
        thermal_controller: Any,
        param_snapshot: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        检查丰度，若不足则通知热控升温。

        参数：
            thermal_controller: ThermalController 实例
            param_snapshot   : 参数快照

        返回：
            True 表示触发了升温
        """
        if param_snapshot is not None:
            self._threshold = float(
                param_snapshot.get("language丰度.low_threshold", self._threshold)
            )

        丰度 = self.compute丰度()
        should = self.should_heat_up(丰度)

        if should and thermal_controller is not None:
            thermal_controller.force_heat(delta=0.15)
            logger.info(f"[LinguisticAbundance] 丰度不足({丰度:.3f}<{self._threshold})，强制升温")
            return True

        return False

    # -------------------------------------------------------------------------
    # 统计
    # -------------------------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        """返回当前丰度统计信息。"""
        当前丰度 = self.compute丰度()
        recent = list(self._strategy_history)
        return {
            "丰度": round(当前丰度, 4),
            "unique_count": len(set(recent)) if recent else 0,
            "total_count": len(recent),
            "is_low丰度": self._is_low丰度,
            "low丰度_streak": self._low丰度_streak,
        }
