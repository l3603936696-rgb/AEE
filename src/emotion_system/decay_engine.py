"""
DecayEngine — 情绪衰减引擎（v10.0）

负责所有核心情绪的时间衰减计算。

设计原则：
    - 状态驱动：衰减基于 elapsed_s，不依赖固定 tick 步长
    - 厌倦双根源独立衰减：
        - 绝望性倦怠（boredom_despair）：整个策略库跑不通，做什么都没用
        - 徒劳性倦怠（boredom_futility）：优化成本超过收益，越来越不值得
    - 参数外置：所有时间参数从 param_snapshot 读取
"""

import logging
import math
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class DecayEngine:
    """
    情绪衰减引擎。

    负责计算所有情绪维度的衰减后的当前强度。

    衰减公式（与 ParticleField 共用对数衰减）：
        intensity(t) = initial * log(half_life - t) / log(half_life)

    各情绪维度对应的半衰期：
        - joy              → emotion_decay.joy_t
        - fear             → emotion_decay.fear_t
        - anger            → emotion_decay.anger_t
        - sadness          → emotion_decay.sadness_t
        - surprise         → emotion_decay.surprise_t
        - boredom_despair   → emotion_decay.boredom_despair_t
        - boredom_futility  → emotion_decay.boredom_futility_t
        - inertia（惯性残余）→ emotion_decay.inertia_t
    """

    def __init__(self) -> None:
        pass

    # -------------------------------------------------------------------------
    # 衰减公式
    # -------------------------------------------------------------------------

    @staticmethod
    def _log_decay(initial: float, elapsed_s: float, half_life: float) -> float:
        """
        对数衰减公式。

        density(t) = initial * log(half_life - t) / log(half_life)

        当 t >= half_life 时返回 0。
        当 t <= 0 时返回 initial。
        """
        if elapsed_s <= 0:
            return initial
        if elapsed_s >= half_life:
            return 0.0
        ratio = math.log(max(1.0, half_life - elapsed_s)) / math.log(max(1.0, half_life))
        return initial * ratio

    def compute_decay(
        self,
        current_intensity: float,
        elapsed_s: float,
        half_life: float,
        param_snapshot: Optional[Dict[str, Any]] = None,
    ) -> float:
        """
        计算单维度情绪在经过 elapsed_s 后的衰减强度。

        参数：
            current_intensity: 当前强度（[0, 1]）
            elapsed_s        : 经过的时间（秒）
            half_life        : 半衰期（秒）
            param_snapshot   : 参数快照（当前未使用，预留扩展）

        返回：
            衰减后的强度（[0, current_intensity]）
        """
        if current_intensity <= 0 or elapsed_s <= 0:
            return current_intensity
        return max(0.0, self._log_decay(current_intensity, elapsed_s, half_life))

    # -------------------------------------------------------------------------
    # 批量衰减：entity 所有情绪维度
    # -------------------------------------------------------------------------

    @staticmethod
    def _get_half_life(
        dimension: str,
        param_snapshot: Optional[Dict[str, Any]],
    ) -> float:
        """从 param_snapshot 读取指定维度的衰减半衰期。"""
        # 厌倦双根源
        if dimension == "boredom_despair":
            key = "emotion_decay.boredom_despair_t"
        elif dimension == "boredom_futility":
            key = "emotion_decay.boredom_futility_t"
        # 核心情绪
        elif dimension == "joy":
            key = "emotion_decay.joy_t"
        elif dimension == "fear":
            key = "emotion_decay.fear_t"
        elif dimension == "anger":
            key = "emotion_decay.anger_t"
        elif dimension == "sadness":
            key = "emotion_decay.sadness_t"
        elif dimension == "surprise":
            key = "emotion_decay.surprise_t"
        # 惯性残余
        elif dimension == "inertia":
            key = "emotion_decay.inertia_t"
        else:
            # 未知维度使用默认值（1小时）
            return 3600.0

        if param_snapshot is None:
            # 内置默认值
            defaults = {
                "emotion_decay.boredom_despair_t": 7200.0,
                "emotion_decay.boredom_futility_t": 3600.0,
                "emotion_decay.joy_t": 3600.0,
                "emotion_decay.fear_t": 1800.0,
                "emotion_decay.anger_t": 2400.0,
                "emotion_decay.sadness_t": 5400.0,
                "emotion_decay.surprise_t": 600.0,
                "emotion_decay.inertia_t": 900.0,
            }
            return defaults.get(key, 3600.0)

        try:
            keys = key.split(".")
            value = param_snapshot
            for k in keys:
                if isinstance(value, dict):
                    value = value.get(k)
                else:
                    return defaults.get(key, 3600.0)
            if isinstance(value, (int, float)):
                return float(value)
        except Exception:
            pass

        return {
            "emotion_decay.boredom_despair_t": 7200.0,
            "emotion_decay.boredom_futility_t": 3600.0,
            "emotion_decay.joy_t": 3600.0,
            "emotion_decay.fear_t": 1800.0,
            "emotion_decay.anger_t": 2400.0,
            "emotion_decay.sadness_t": 5400.0,
            "emotion_decay.surprise_t": 600.0,
            "emotion_decay.inertia_t": 900.0,
        }.get(key, 3600.0)

    def tick_all(
        self,
        entity_state: Any,
        elapsed_s: float,
        param_snapshot: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, float]:
        """
        批量推进 entity 所有情绪维度的衰减。

        厌倦双根源独立衰减：
            - boredom_despair → emotion_decay.boredom_despair_t
            - boredom_futility → emotion_decay.boredom_futility_t

        其他情绪维度使用各自对应的半衰期。

        参数：
            entity_state   : EntityCore 实例（含各情绪维度属性）
            elapsed_s      : 经过的时间（秒）
            param_snapshot : 参数快照

        返回：
            各维度衰减后的新值 dict {dimension: new_value}
            注意：返回值仅供信息记录，entity 自身的字段由调用方更新
        """
        if elapsed_s <= 0:
            return {}

        # 定义需要衰减的情绪维度及其默认值
        emotion_dimensions = [
            ("boredom_despair", 0.0),
            ("boredom_futility", 0.0),
            ("joy", 0.0),
            ("fear", 0.0),
            ("anger", 0.0),
            ("sadness", 0.0),
            ("surprise", 0.0),
            ("inertia", 0.0),
        ]

        result: Dict[str, float] = {}

        for dim, default in emotion_dimensions:
            # 从 entity_state 读取当前值
            current = getattr(entity_state, dim, default)
            if current is None or current <= 0:
                result[dim] = default
                continue

            half_life = self._get_half_life(dim, param_snapshot)
            new_value = self.compute_decay(current, elapsed_s, half_life, param_snapshot)

            # 更新 entity_state（直接赋值，EntityState 可能无该字段声明）
            setattr(entity_state, dim, new_value)

            result[dim] = new_value

        # 更新时间戳（供下次 tick 计算 elapsed_s）
        if hasattr(entity_state, "last_emotion_tick"):
            import time as _time
            entity_state.last_emotion_tick = _time.time()

        return result

    # -------------------------------------------------------------------------
    # 单独衰减某维度（供管线中单独调用）
    # -------------------------------------------------------------------------

    def decay_dimension(
        self,
        entity_state: Any,
        dimension: str,
        elapsed_s: float,
        param_snapshot: Optional[Dict[str, Any]] = None,
    ) -> float:
        """
        衰减 entity 的单个情绪维度。

        参数：
            entity_state : EntityCore 实例
            dimension    : 维度名称
            elapsed_s    : 经过的时间（秒）
            param_snapshot: 参数快照

        返回：
            衰减后的新值
        """
        default = 0.0
        current = getattr(entity_state, dimension, default)
        if current is None or current <= 0 or elapsed_s <= 0:
            return current

        half_life = self._get_half_life(dimension, param_snapshot)
        new_value = self.compute_decay(current, elapsed_s, half_life, param_snapshot)

        if hasattr(entity_state, dimension):
            setattr(entity_state, dimension, new_value)

        return new_value
