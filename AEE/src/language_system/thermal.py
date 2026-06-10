"""
ThermalController — 自适应温控（v7.0）

职责：
    - 基于 energy 历史驱动温度在 [0.1, 2.0] 范围内自适应升降
    - 高能量时放大探索（温度升高）；低能量时收缩到舒适区（温度降低）
    - 自然衰减防止温度无限累积
    - 为 CandidateGenerator 提供探索窗口宽度

温控规则：
    - energy > energy_threshold → 升温（scale = high_energy_scale）
    - energy < energy_threshold → 降温（scale = low_energy_scale）
    - 每轮自然衰减 decay_rate

设计原则：
    - 参数外置：所有阈值从 param_snapshot 读取
    - 状态驱动：基于真实 energy 变化，不依赖固定 tick
"""

import logging
from collections import deque
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class ThermalController:
    """
    自适应温控器。

    温度范围：[0.1, 2.0]
    - temperature = 1.0  ：标准探索
    - temperature > 1.0  ：高探索，候选窗口宽，LLM 生成多样
    - temperature < 1.0  ：低探索，候选窗口窄，倾向已知策略

    属性：
        _temperature  : 当前温度
        _energy_history: energy 历史队列（用于趋势判断）
    """

    def __init__(
        self,
        initial_temperature: float = 1.0,
        high_energy_scale: float = 1.30,
        low_energy_scale: float = 0.60,
        energy_threshold: float = 0.40,
        decay_rate: float = 0.02,
    ) -> None:
        self._temperature = initial_temperature
        self.high_energy_scale = high_energy_scale
        self.low_energy_scale = low_energy_scale
        self.energy_threshold = energy_threshold
        self.decay_rate = decay_rate

        # energy_history：最多保留 10 轮
        self._energy_history: deque[float] = deque(maxlen=10)

    # -------------------------------------------------------------------------
    # tick
    # -------------------------------------------------------------------------

    def tick(
        self,
        energy: float,
        param_snapshot: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        每轮推进温控更新。

        更新流程：
            1. 记录当前 energy
            2. 用 param_snapshot 覆盖参数（若有）
            3. 基于 energy 与阈值的比较，决定升降方向
            4. 自然衰减

        参数：
            energy       : 当前能量值 [0, 1]
            param_snapshot: 参数快照
        """
        if param_snapshot is not None:
            self.high_energy_scale = float(
                param_snapshot.get("language.thermal.high_energy_scale", self.high_energy_scale)
            )
            self.low_energy_scale = float(
                param_snapshot.get("language.thermal.low_energy_scale", self.low_energy_scale)
            )
            self.energy_threshold = float(
                param_snapshot.get("language.thermal.energy_threshold", self.energy_threshold)
            )
            self.decay_rate = float(
                param_snapshot.get("language.thermal.decay_rate", self.decay_rate)
            )

        # 记录 energy 历史
        self._energy_history.append(energy)

        # 计算能量趋势（简单移动平均）
        energy_trend = self._compute_trend()

        # 温度更新
        if energy_trend > self.energy_threshold:
            # 高能量：放大探索
            self._temperature = max(
                self._temperature,
                self.high_energy_scale,
            )
        elif energy_trend < self.energy_threshold:
            # 低能量：收缩到舒适区
            self._temperature = min(
                self._temperature,
                self.low_energy_scale,
            )

        # 自然衰减（向 1.0 回归）
        self._temperature = self._temperature * (1.0 - self.decay_rate) + 1.0 * self.decay_rate

        # clamp 到范围
        self._temperature = max(0.1, min(2.0, self._temperature))

    def _compute_trend(self) -> float:
        """计算 energy 趋势值（简单均值）。"""
        if not self._energy_history:
            return 0.5
        return sum(self._energy_history) / len(self._energy_history)

    # -------------------------------------------------------------------------
    # 查询
    # -------------------------------------------------------------------------

    def get_temperature(self) -> float:
        """返回当前温度。"""
        return self._temperature

    def get_exploration_window(self) -> int:
        """
        返回候选窗口大小（用于 LLM 生成时的采样宽度）。

        规则：
            temperature ∈ [0.1, 2.0]
            window ∈ [1, 5]

            温度越高，窗口越大（探索更多候选）
            温度越低，窗口越小（倾向已知策略）
        """
        # 线性映射：0.1 → 1，2.0 → 5
        t = max(0.1, min(2.0, self._temperature))
        window = int(round(1 + (t - 0.1) / (2.0 - 0.1) * 4))
        return max(1, min(5, window))

    # -------------------------------------------------------------------------
    # 强制升温（丰度不足时调用）
    # -------------------------------------------------------------------------

    def force_heat(self, delta: float = 0.2) -> None:
        """
        强制升高温度（用于丰度不足时扩大候选窗口）。

        参数：
            delta: 升幅（默认 0.2）
        """
        self._temperature = min(2.0, self._temperature + delta)
        logger.debug(f"[ThermalController] force_heat: temperature -> {self._temperature:.3f}")

    def force_cool(self, delta: float = 0.1) -> None:
        """强制降低温度（用于高负荷时收缩）。"""
        self._temperature = max(0.1, self._temperature - delta)
        logger.debug(f"[ThermalController] force_cool: temperature -> {self._temperature:.3f}")

    # -------------------------------------------------------------------------
    # 序列化
    # -------------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """序列化。"""
        return {
            "temperature": self._temperature,
            "high_energy_scale": self.high_energy_scale,
            "low_energy_scale": self.low_energy_scale,
            "energy_threshold": self.energy_threshold,
            "decay_rate": self.decay_rate,
            "energy_history": list(self._energy_history),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ThermalController":
        """从 dict 恢复。"""
        ctrl = cls(
            initial_temperature=float(data.get("temperature", 1.0)),
            high_energy_scale=float(data.get("high_energy_scale", 1.30)),
            low_energy_scale=float(data.get("low_energy_scale", 0.60)),
            energy_threshold=float(data.get("energy_threshold", 0.40)),
            decay_rate=float(data.get("decay_rate", 0.02)),
        )
        for e in data.get("energy_history", []):
            ctrl._energy_history.append(float(e))
        return ctrl
