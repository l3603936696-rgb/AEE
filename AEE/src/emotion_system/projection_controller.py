"""
ProjectionController — 三层情绪投影阻尼控制（v11.0）

负责三层情绪模型中层间投影的调度与阻尼：

    主线层 → 日常层：主线情绪惯性残余注入日常粒子场
    日常层 → 主线层：粒子场纹理影响主线基调
    记忆层 → 主线层：记忆匹配时激活情绪投影（含冷却与降频）
    记忆层 → 日常层：记忆激活时向粒子场撒入历史粒子

防死锁设计：
    - damping × cap × cooldown 三重保障
    - 同一记忆短期内降频（repeat_decay）
    - 所有投影值受对应层 cap 截断
"""

import logging
import time
from typing import Any, Dict, List, Optional

from .particle_field import ParticleField

logger = logging.getLogger(__name__)


class ProjectionController:
    """
    三层情绪投影控制器。

    负责管理三个投影通道的发射、累计和衰减：
        - mainline_to_daily: 主线惯性残余 → 日常层
        - daily_to_mainline: 日常纹理 → 主线层（不修改 entity，输出偏置）
        - memory_to_mainline: 记忆情绪激活 → 主线层
        - memory_to_daily   : 记忆粒子撒入 → 日常层

    属性：
        mainline_acc : 主线层累计器（各情绪维度的当前强度）
        daily_acc    : 日常层累计器（整体纹理强度）
        memory_acc   : 记忆层累计器（按记忆 ID 分别记录）
        _memory_cooldowns: 记忆冷却记录 {memory_id: last_activated_ts}
        _memory_repeat_weights: 记忆降频权重 {memory_id: weight}
    """

    def __init__(
        self,
        mainline_cap: float = 1.0,
        daily_cap: float = 0.6,
        memory_cap: float = 0.8,
        mainline_to_daily_damping: float = 0.70,
        daily_to_mainline_damping: float = 0.40,
        memory_to_mainline_damping: float = 0.50,
        memory_to_daily_damping: float = 0.30,
        memory_cooldown_s: float = 300.0,
        memory_repeat_decay: float = 0.50,
    ) -> None:
        self.mainline_cap = mainline_cap
        self.daily_cap = daily_cap
        self.memory_cap = memory_cap

        self.mainline_to_daily_damping = mainline_to_daily_damping
        self.daily_to_mainline_damping = daily_to_mainline_damping
        self.memory_to_mainline_damping = memory_to_mainline_damping
        self.memory_to_daily_damping = memory_to_daily_damping

        self.memory_cooldown_s = memory_cooldown_s
        self.memory_repeat_decay = memory_repeat_decay

        # 运行时累计器（不持久化）
        self._mainline_acc: Dict[str, float] = {}   # {dimension: intensity}
        self._daily_acc: float = 0.0               # 整体纹理强度
        self._memory_acc: Dict[int, float] = {}    # {memory_id: intensity}

        # 记忆层元数据
        self._memory_cooldowns: Dict[int, float] = {}   # {memory_id: last_activation_ts}
        self._memory_repeat_weights: Dict[int, float] = {}  # {memory_id: weight}

    # -------------------------------------------------------------------------
    # 主线 → 日常层
    # -------------------------------------------------------------------------

    def apply_mainline_to_daily(
        self,
        mainline_emotions: Dict[str, float],
        particle_field: ParticleField,
        param_snapshot: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        将主线情绪的惯性残余注入日常层粒子场。

        计算方式：
            emission = mainline_intensity × mainline_to_daily_damping
            particle_field.add_inertia_particle(dimension, emission)

        参数：
            mainline_emotions: 当前主线情绪 dict {dimension: intensity}
            particle_field   : 目标粒子场实例
            param_snapshot   : 参数快照（覆盖构造时的 damping 值）
        """
        damping = self._get_param(param_snapshot, "emotion_projection.mainline_to_daily_damping",
                                  self.mainline_to_daily_damping)

        for dimension, intensity in mainline_emotions.items():
            if intensity <= 0.0:
                continue
            emission = intensity * damping
            particle_field.add_inertia_particle(dimension, emission, param_snapshot)

            # 同时更新 daily 累计器
            self._daily_acc = min(
                self.daily_cap,
                self._daily_acc + emission,
            )

    # -------------------------------------------------------------------------
    # 日常层 → 主线层
    # -------------------------------------------------------------------------

    def apply_daily_to_mainline(
        self,
        particle_field: ParticleField,
        param_snapshot: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, float]:
        """
        将日常层粒子场纹理投影到主线基调。

        计算方式：
            densities = particle_field.get_all_densities()
            overall = 加权和 / 维度数量
            mainline_influence = overall × daily_to_mainline_damping × daily_cap

        返回：
            各情绪维度的日常层影响值 dict {dimension: influence}
            （调用方负责将影响值应用到 entity 的情绪状态）
        """
        densities = particle_field.get_all_densities()
        if not densities:
            return {}

        # 计算平均密度（归一化）
        avg_density = sum(densities.values()) / len(densities)

        damping = self._get_param(param_snapshot, "emotion_projection.daily_to_mainline_damping",
                                  self.daily_to_mainline_damping)
        cap = self._get_param(param_snapshot, "emotion_projection.daily_cap", self.daily_cap)

        overall_influence = min(cap, avg_density * damping)

        # 将影响值按各维度密度比例分配
        result: Dict[str, float] = {}
        for dim, density in densities.items():
            weight = density / sum(densities.values())
            result[dim] = overall_influence * weight

        # 更新 daily 累计器
        self._daily_acc = max(0.0, self._daily_acc - overall_influence * 0.1)

        return result

    # -------------------------------------------------------------------------
    # 记忆层 → 主线层 + 日常层
    # -------------------------------------------------------------------------

    def check_memory_projection(
        self,
        memory_context: Dict[str, Any],
        current_state: Optional[Dict[str, Any]] = None,
        param_snapshot: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        检查当前情境是否触发记忆层投影（不执行投影，只返回投影信息）。

        触发条件：
            1. memory_context 中存在匹配的强烈情绪记忆
            2. 记忆不在冷却中，或冷却已过期
            3. 记忆强度超过激活阈值

        参数：
            memory_context: 记忆检索结果（含 matched_memories 等）
            current_state : 当前驱动力场状态（用于相似度匹配）
            param_snapshot: 参数快照

        返回：
            投影信息 dict，包含：
                - memory_id: 记忆 ID
                - emotion_intensity: 情绪强度
                - emotion_dimension: 情绪维度
                - projection_type: "mainline" | "daily" | "both"
            若不触发，返回 None
        """
        memories = memory_context.get("matched_memories", [])
        if not memories:
            return None

        now = time.time()
        cooldown = self._get_param(param_snapshot, "emotion_projection.memory_cooldown_s",
                                  self.memory_cooldown_s)
        repeat_decay = self._get_param(param_snapshot, "emotion_projection.memory_repeat_decay",
                                       self.memory_repeat_decay)
        damping_m2m = self._get_param(param_snapshot, "emotion_projection.memory_to_mainline_damping",
                                       self.memory_to_mainline_damping)
        damping_m2d = self._get_param(param_snapshot, "emotion_projection.memory_to_daily_damping",
                                       self.memory_to_daily_damping)
        cap = self._get_param(param_snapshot, "emotion_projection.memory_cap", self.memory_cap)

        for memory in memories:
            mem_id = int(memory.get("id", 0))
            if mem_id == 0:
                continue

            # 检查冷却
            last_ts = self._memory_cooldowns.get(mem_id, 0.0)
            if now - last_ts < cooldown:
                # 冷却中：尝试降频
                weight = self._memory_repeat_weights.get(mem_id, 1.0)
                if weight * damping_m2m < 0.05:
                    continue  # 降频后强度太低，跳过
                self._memory_repeat_weights[mem_id] = weight * repeat_decay
            else:
                # 冷却已过，重置降频权重
                self._memory_repeat_weights[mem_id] = 1.0

            # 情绪强度
            emotion_intensity = float(memory.get("emotion_intensity", 0.0))
            if emotion_intensity <= 0.0:
                continue

            # 应用降频权重
            weight = self._memory_repeat_weights.get(mem_id, 1.0)
            effective_intensity = emotion_intensity * weight

            # 确定投影类型
            projection_type = "both"
            dim = memory.get("emotion_dimension", "unknown")

            return {
                "memory_id": mem_id,
                "emotion_intensity": effective_intensity,
                "emotion_dimension": dim,
                "projection_type": projection_type,
                "memory_data": memory,
            }

        return None

    def apply_memory_projection(
        self,
        memory_context: Dict[str, Any],
        current_state: Optional[Dict[str, Any]],
        particle_field: ParticleField,
        param_snapshot: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, float]:
        """
        执行记忆层投影（主线 + 日常）。

        返回：
            主线层投影结果 dict {dimension: intensity}
            （调用方负责应用到 entity）
        """
        projection_info = self.check_memory_projection(
            memory_context, current_state, param_snapshot
        )

        if projection_info is None:
            return {}

        now = time.time()
        mem_id = projection_info["memory_id"]
        intensity = projection_info["emotion_intensity"]
        dim = projection_info["emotion_dimension"]

        damping_m2m = self._get_param(param_snapshot, "emotion_projection.memory_to_mainline_damping",
                                       self.memory_to_mainline_damping)
        damping_m2d = self._get_param(param_snapshot, "emotion_projection.memory_to_daily_damping",
                                       self.memory_to_daily_damping)
        cap = self._get_param(param_snapshot, "emotion_projection.memory_cap", self.memory_cap)

        # 更新冷却
        self._memory_cooldowns[mem_id] = now

        # 主线层投影
        mainline_emission = min(cap, intensity * damping_m2m)

        # 更新内存累计器
        self._memory_acc[mem_id] = self._memory_acc.get(mem_id, 0.0) + mainline_emission

        # 日常层投影：向粒子场撒入记忆粒子
        daily_emission = min(self.daily_cap, intensity * damping_m2d)
        particle_field.add_particle(dim, daily_emission)

        result = {dim: mainline_emission}

        logger.debug(
            f"[ProjectionController] memory projection: mem_id={mem_id}, "
            f"dim={dim}, mainline={mainline_emission:.3f}, daily={daily_emission:.3f}"
        )

        return result

    # -------------------------------------------------------------------------
    # 累计器衰减
    # -------------------------------------------------------------------------

    def tick(self, elapsed_s: float) -> None:
        """
        推进所有累计器的隐性衰减（缓慢自然消退）。

        参数：
            elapsed_s: 经过的时间（秒）
        """
        if elapsed_s <= 0:
            return

        decay_rate = 0.01  # 每秒衰减 1%

        # daily 累计器衰减
        self._daily_acc = max(0.0, self._daily_acc * (1.0 - decay_rate * elapsed_s))

        # memory 累计器衰减
        memory_keys = list(self._memory_acc.keys())
        for mem_id in memory_keys:
            self._memory_acc[mem_id] = max(0.0, self._memory_acc[mem_id] * (1.0 - decay_rate * elapsed_s))
            if self._memory_acc[mem_id] <= 0.001:
                del self._memory_acc[mem_id]

    # -------------------------------------------------------------------------
    # 辅助方法
    # -------------------------------------------------------------------------

    def _get_param(self, param_snapshot: Optional[Dict[str, Any]], key: str, default: float) -> float:
        """安全读取参数。"""
        if param_snapshot is None:
            return default
        try:
            keys = key.split(".")
            value = param_snapshot
            for k in keys:
                if isinstance(value, dict):
                    value = value.get(k)
                else:
                    return default
            if isinstance(value, (int, float)):
                return float(value)
            return default
        except Exception:
            return default

    def get_accumulators(self) -> Dict[str, Any]:
        """返回当前累计器状态（供调试和持久化参考）。"""
        return {
            "mainline_acc": dict(self._mainline_acc),
            "daily_acc": self._daily_acc,
            "memory_acc": dict(self._memory_acc),
        }

    def to_dict(self) -> Dict[str, Any]:
        """
        序列化投影控制器状态（不含运行时累计器）。

        供 EntityCore 持久化使用。
        """
        return {
            "mainline_cap": self.mainline_cap,
            "daily_cap": self.daily_cap,
            "memory_cap": self.memory_cap,
            "mainline_to_daily_damping": self.mainline_to_daily_damping,
            "daily_to_mainline_damping": self.daily_to_mainline_damping,
            "memory_to_mainline_damping": self.memory_to_mainline_damping,
            "memory_to_daily_damping": self.memory_to_daily_damping,
            "memory_cooldown_s": self.memory_cooldown_s,
            "memory_repeat_decay": self.memory_repeat_decay,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProjectionController":
        """从 dict 恢复投影控制器配置（不含运行时累计器）。"""
        return cls(
            mainline_cap=float(data.get("mainline_cap", 1.0)),
            daily_cap=float(data.get("daily_cap", 0.6)),
            memory_cap=float(data.get("memory_cap", 0.8)),
            mainline_to_daily_damping=float(data.get("mainline_to_daily_damping", 0.70)),
            daily_to_mainline_damping=float(data.get("daily_to_mainline_damping", 0.40)),
            memory_to_mainline_damping=float(data.get("memory_to_mainline_damping", 0.50)),
            memory_to_daily_damping=float(data.get("memory_to_daily_damping", 0.30)),
            memory_cooldown_s=float(data.get("memory_cooldown_s", 300.0)),
            memory_repeat_decay=float(data.get("memory_repeat_decay", 0.50)),
        )
