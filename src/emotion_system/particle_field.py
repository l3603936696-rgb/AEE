"""
ParticleField — 日常层粒子场（v10.0）

负责日常层的核心数据结构：
    - 粒子缓存区（固定容量，先进先出）
    - 粒子产生：驱动力场微小波动、记忆边缘激活、环境弱关联、惯性残余
    - 粒子衰减：极慢的对数衰减曲线
    - 查表插值：将粒子密度映射为表达层参数偏置

设计原则：
    - 状态驱动：所有衰减基于 elapsed_s，不依赖固定 tick 步长
    - 参数外置：所有数值参数从 param_snapshot 读取
    - 无阈值判断：查表插值全程连续
"""

import logging
import math
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class Particle:
    """
    单个情绪粒子。

    属性：
        dimension      : 情绪维度标签（如 "loneliness", "anger", "joy"）
        initial_density: 投入时的初始强度（[0, 1]）
        half_life     : 半衰期（秒），用于对数衰减计算
        timestamp     : 投入时的 unix timestamp
    """
    dimension: str
    initial_density: float
    half_life: float
    timestamp: float


class ParticleField:
    """
    日常层情绪粒子场。

    粒子产生于系统的日常运作：
        - 驱动力场的微小变化
        - 记忆检索的边缘激活（未达记忆层投影阈值）
        - 环境特征的弱关联唤醒
        - 主线情绪的惯性残余
        - 未预期的微小正向事件

    粒子衰减采用极慢的对数衰减曲线，而非指数级——
    确保日常纹理不会瞬间消失。

    属性：
        max_capacity    : 缓存最大容量（超出时移除最老粒子）
        half_life       : 默认半衰期（秒）
        min_density     : 密度下限（防止负值）
        _buffer         : 粒子队列（内部使用）
    """

    def __init__(
        self,
        max_capacity: int = 200,
        half_life: float = 1800.0,
        min_density: float = 0.0,
    ) -> None:
        self.max_capacity = max_capacity
        self.half_life = half_life
        self.min_density = min_density
        self._buffer: deque[Particle] = deque(maxlen=max_capacity)

    # -------------------------------------------------------------------------
    # 粒子操作
    # -------------------------------------------------------------------------

    def add_particle(
        self,
        dimension: str,
        intensity: float,
        half_life: Optional[float] = None,
    ) -> None:
        """
        向缓存添加一个粒子。

        参数：
            dimension  : 情绪维度标签
            intensity  : 粒子强度（[0, 1]），会被 clamp 到 [0, 1]
            half_life  : 半衰期（秒），若为 None 则使用默认值
        """
        intensity = max(0.0, min(1.0, intensity))
        if intensity <= 0.0:
            return

        particle = Particle(
            dimension=dimension,
            initial_density=intensity,
            half_life=half_life if half_life is not None else self.half_life,
            timestamp=time.time(),
        )
        self._buffer.append(particle)

    def add_inertia_particle(
        self,
        dimension: str,
        intensity: float,
        param_snapshot: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        专门用于主线情绪惯性残余产生的粒子。

        从 param_snapshot 读取 inertia_weight 和默认半衰期。
        """
        if param_snapshot is not None:
            weight = float(param_snapshot.get("emotion_particle.inertia_weight", 0.30))
            intensity = intensity * weight
        self.add_particle(dimension, intensity)

    def add_ambient_particle(
        self,
        dimension: str,
        intensity: float,
        param_snapshot: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        专门用于微小环境事件产生的粒子。

        从 param_snapshot 读取 ambient_weight。
        """
        if param_snapshot is not None:
            weight = float(param_snapshot.get("emotion_particle.ambient_weight", 0.50))
            intensity = intensity * weight
        self.add_particle(dimension, intensity)

    # -------------------------------------------------------------------------
    # 衰减
    # -------------------------------------------------------------------------

    @staticmethod
    def _decay_density(initial: float, elapsed_s: float, half_life: float) -> float:
        """
        对数衰减公式：

            density(t) = initial * log(half_life - t) / log(half_life)

        当 t >= half_life 时返回 0。

        参数：
            initial  : 初始密度
            elapsed_s: 经过的时间（秒）
            half_life: 半衰期（秒）

        返回：
            当前密度（可能为 0）
        """
        if elapsed_s >= half_life:
            return 0.0
        # log(half_life - t) / log(half_life) ∈ (0, 1]
        ratio = math.log(max(1.0, half_life - elapsed_s)) / math.log(max(1.0, half_life))
        return initial * ratio

    def tick(self, elapsed_s: float) -> int:
        """
        推进所有粒子的衰减，移除已耗尽的粒子。

        参数：
            elapsed_s : 从上次 tick 到现在经过的时间（秒）

        返回：
            移除的粒子数量
        """
        if elapsed_s <= 0 or not self._buffer:
            return 0

        removed = 0
        new_buffer: deque[Particle] = deque(maxlen=self.max_capacity)

        for p in self._buffer:
            current_density = self._decay_density(
                p.initial_density, elapsed_s, p.half_life
            )
            if current_density > self.min_density:
                new_buffer.append(p)

        removed = len(self._buffer) - len(new_buffer)
        self._buffer = new_buffer
        return removed

    # -------------------------------------------------------------------------
    # 密度查询
    # -------------------------------------------------------------------------

    def get_density(self, dimension: str) -> float:
        """
        返回某维度的当前累积粒子密度。

        密度 = Σ 当前有效密度（所有该维度粒子的瞬时密度之和）。
        """
        now = time.time()
        total = 0.0
        for p in self._buffer:
            if p.dimension == dimension:
                total += self._decay_density(p.initial_density, now - p.timestamp, p.half_life)
        return max(self.min_density, total)

    def get_all_densities(self) -> Dict[str, float]:
        """
        返回各维度的当前累积密度 dict。

        返回：
            {dimension: density, ...}
        """
        result: Dict[str, float] = {}
        now = time.time()
        for p in self._buffer:
            current = self._decay_density(p.initial_density, now - p.timestamp, p.half_life)
            if current > self.min_density:
                result[p.dimension] = result.get(p.dimension, 0.0) + current
        for dim in result:
            result[dim] = max(self.min_density, result[dim])
        return result

    def get_overall_density(self) -> float:
        """
        返回所有维度的总密度（加权平均密度，供输出调制使用）。

        计算方式：所有维度密度的平均值（归一化到粒子数量）。
        """
        densities = self.get_all_densities()
        if not densities:
            return 0.0
        return sum(densities.values()) / len(densities)

    # -------------------------------------------------------------------------
    # 查表插值：粒子密度 → 文字流速调制
    # -------------------------------------------------------------------------

    def interpolate_lookup(
        self,
        density: float,
        param_snapshot: Optional[Dict[str, Any]] = None,
    ) -> float:
        """
        在粒子密度锚点表上进行一维线性插值，返回文字流速偏置。

        锚点表（density → flow_rate）：
            0.00 → 1.00（正常流速）
            0.30 → 0.90（轻微迟滞）
            0.60 → 0.70（明显迟滞）
            1.00 → 0.40（碎片化）

        参数：
            density      : 当前粒子密度（[0, 1]）
            param_snapshot: 参数快照（含锚点值）

        返回：
            text_flow_rate 偏置（[0.4, 1.0]）
        """
        if param_snapshot is None:
            # 使用内置默认值
            density_anchors = [0.00, 0.30, 0.60, 1.00]
            flow_anchors =    [1.00, 0.90, 0.70, 0.40]
        else:
            density_anchors = [
                float(param_snapshot.get("emotion_particle.lookup_density_0", 0.00)),
                float(param_snapshot.get("emotion_particle.lookup_density_1", 0.30)),
                float(param_snapshot.get("emotion_particle.lookup_density_2", 0.60)),
                float(param_snapshot.get("emotion_particle.lookup_density_3", 1.00)),
            ]
            flow_anchors = [
                float(param_snapshot.get("emotion_particle.lookup_flow_0", 1.00)),
                float(param_snapshot.get("emotion_particle.lookup_flow_1", 0.90)),
                float(param_snapshot.get("emotion_particle.lookup_flow_2", 0.70)),
                float(param_snapshot.get("emotion_particle.lookup_flow_3", 0.40)),
            ]

        d = max(0.0, min(1.0, density))

        # 线性插值
        for i in range(len(density_anchors) - 1):
            d0, d1 = density_anchors[i], density_anchors[i + 1]
            if d0 <= d <= d1:
                t = (d - d0) / max(d1 - d0, 1e-9)
                return flow_anchors[i] + t * (flow_anchors[i + 1] - flow_anchors[i])

        # 边界外 clamp
        if d < density_anchors[0]:
            return flow_anchors[0]
        return flow_anchors[-1]

    def compute_flow_modulation(
        self,
        param_snapshot: Optional[Dict[str, Any]] = None,
    ) -> float:
        """
        计算当前粒子场对文字流速的调制系数。

        流程：
            1. 获取所有维度的总体密度
            2. 查表插值得到 flow_rate 偏置

        参数：
            param_snapshot: 参数快照

        返回：
            text_flow_rate 偏置（[0.4, 1.0]）
        """
        density = self.get_overall_density()
        return self.interpolate_lookup(density, param_snapshot)

    # -------------------------------------------------------------------------
    # 序列化
    # -------------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """将当前粒子场状态序列化为 dict（供 EntityCore 持久化）。"""
        now = time.time()
        particles_data = []
        for p in self._buffer:
            current_density = self._decay_density(
                p.initial_density, now - p.timestamp, p.half_life
            )
            if current_density > self.min_density:
                particles_data.append({
                    "dimension": p.dimension,
                    "initial_density": p.initial_density,
                    "half_life": p.half_life,
                    "timestamp": p.timestamp,
                })
        return {
            "max_capacity": self.max_capacity,
            "half_life": self.half_life,
            "min_density": self.min_density,
            "particles": particles_data,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ParticleField":
        """从 dict 恢复粒子场状态。"""
        max_cap = int(data.get("max_capacity", 200))
        half_life = float(data.get("half_life", 1800.0))
        min_d = float(data.get("min_density", 0.0))
        field = cls(max_capacity=max_cap, half_life=half_life, min_density=min_d)

        for pdata in data.get("particles", []):
            p = Particle(
                dimension=str(pdata.get("dimension", "")),
                initial_density=float(pdata.get("initial_density", 0.0)),
                half_life=float(pdata.get("half_life", half_life)),
                timestamp=float(pdata.get("timestamp", time.time())),
            )
            if p.initial_density > 0:
                field._buffer.append(p)

        return field
