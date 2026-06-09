"""
FiveRightsController — 六大主权控制器（v7.0）

六大主权（生存本能，不是"人性化特征"——缺陷是人格防伪标识）：

    1. 自闭权 — avoid > 阈值时触发防御性退行，候选池只返回中性词
    2. 厌烦权 — 社交疲劳积累导致候选窗口收窄
    3. 误解权 — 委托 MirrorLearner（见 mirror.py）
    4. 遗忘权 — 负向关联记忆进入衰减队列
    5. 顶撞权 — 检测外部侵入，拒绝执行次优策略
    6. 物理重力 — fragmentation 映射为输出参数

设计原则：
    - 参数外置：所有阈值从 param_snapshot 读取
    - 六大主权是独立运作的，不相互依赖
"""

from __future__ import annotations

import logging
from collections import deque
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

from .five_rights_helpers import (
    _current_time,
    five_rights_to_dict,
    five_rights_from_dict,
    DEFAULT_PARAMETERS,
    check_defy_impl,
)


# ============================================================================
# 六大主权
# ============================================================================


class FiveRightsController:
    """
    六大主权控制器。

    属性：
        _social_fatigue   : 社交疲劳值 [0, 1]
        _defensive_lock   : 防御性退行锁（自闭权触发时为 True）
        _forget_pending   : 待遗忘的记忆 id 队列
        _mirror           : MirrorLearner 实例（误解权）
    """

    def __init__(
        self,
        # 自闭权
        avoid_high_threshold: float = 0.75,
        lock_window: float = 0.05,
        # 厌烦权
        fatigue_rate: float = 0.015,
        recovery_rate: float = 0.008,
        avoid_bias_cap: float = 0.30,
        # 遗忘权
        negative_strength_decay: float = 0.05,
        # 顶撞权
        pressure_threshold: float = 0.60,
        resistance_boost: float = 1.50,
        # 误解权
        mirror_bias_strength: float = 0.40,
    ) -> None:
        # 自闭权
        self.avoid_high_threshold = avoid_high_threshold
        self.lock_window = lock_window
        self._defensive_lock: bool = False
        self._defensive_lock_avoid_ref: float = 0.0

        # 厌烦权
        self.fatigue_rate = fatigue_rate
        self.recovery_rate = recovery_rate
        self.avoid_bias_cap = avoid_bias_cap
        self._social_fatigue: float = 0.0

        # 遗忘权
        self.negative_strength_decay = negative_strength_decay
        self._forget_pending: deque[int] = deque(maxlen=200)
        # {(episode_id): (negative_strength, timestamp)}
        self._forget_registry: Dict[int, Dict[str, Any]] = {}

        # 顶撞权
        self.pressure_threshold = pressure_threshold
        self.resistance_boost = resistance_boost

        # 误解权（委托给 MirrorLearner）
        self._mirror_bias_strength = mirror_bias_strength

    # -------------------------------------------------------------------------
    # 1. 自闭权
    # -------------------------------------------------------------------------

    def activate_self_close(
        self,
        avoid: float,
        param_snapshot: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        检查并更新自闭权状态。

        规则：
            avoid > avoid_high_threshold → 触发防御性退行，_defensive_lock = True
            avoid < avoid_high_threshold - lock_window → 解锁

        参数：
            avoid       : 当前 avoid 值
            param_snapshot: 参数快照

        返回：
            True 表示当前处于自闭状态
        """
        if param_snapshot is not None:
            self.avoid_high_threshold = float(
                param_snapshot.get("language.self_close.avoid_high_threshold", self.avoid_high_threshold)
            )
            self.lock_window = float(
                param_snapshot.get("language.self_close.lock_window", self.lock_window)
            )

        if self._defensive_lock:
            # 检查是否需要解锁
            if avoid < (self.avoid_high_threshold - self.lock_window):
                self._defensive_lock = False
                logger.debug("[FiveRights] 自闭权解锁: avoid={:.3f}".format(avoid))
        else:
            # 检查是否需要触发
            if avoid > self.avoid_high_threshold:
                self._defensive_lock = True
                self._defensive_lock_avoid_ref = avoid
                logger.info("[FiveRights] 自闭权触发: avoid={:.3f}".format(avoid))

        return self._defensive_lock

    def is_self_close_active(self) -> bool:
        """返回当前是否处于自闭状态。"""
        return self._defensive_lock

    def get_neutral_response(self) -> str:
        """
        自闭状态下的中性词候选。

        防御性退行时，只返回最短的、不带情绪色彩的回应。
        """
        options = ["嗯。", "不知道。", "……", "算了。"]
        return options[0]  # 固定返回最简短的

    # -------------------------------------------------------------------------
    # 2. 厌烦权
    # -------------------------------------------------------------------------

    def tick_social_fatigue(
        self,
        did_express: bool,
        param_snapshot: Optional[Dict[str, Any]] = None,
    ) -> float:
        """
        更新社交疲劳值。

        规则：
            表达了一轮 → social_fatigue += fatigue_rate
            沉默了一轮 → social_fatigue -= recovery_rate

        参数：
            did_express  : 本轮是否有输出（True = 说了一句话，False = 沉默）
            param_snapshot: 参数快照

        返回：
            更新后的 social_fatigue 值
        """
        if param_snapshot is not None:
            self.fatigue_rate = float(
                param_snapshot.get("language.social_fatigue.rate", self.fatigue_rate)
            )
            self.recovery_rate = float(
                param_snapshot.get("language.social_fatigue.recovery_rate", self.recovery_rate)
            )
            self.avoid_bias_cap = float(
                param_snapshot.get("language.social_fatigue.avoid_bias_cap", self.avoid_bias_cap)
            )

        if did_express:
            self._social_fatigue = min(1.0, self._social_fatigue + self.fatigue_rate)
        else:
            self._social_fatigue = max(0.0, self._social_fatigue - self.recovery_rate)

        return self._social_fatigue

    def apply_fatigue_to_avoid(self, avoid: float) -> float:
        """
        将社交疲劳反向推高 avoid 基准。

        规则：
            avoid' = avoid + social_fatigue * avoid_bias_cap

        参数：
            avoid: 当前 avoid 值

        返回：
            受疲劳影响调整后的 avoid 值
        """
        return min(1.0, avoid + self._social_fatigue * self.avoid_bias_cap)

    def get_fatigue(self) -> float:
        """返回当前社交疲劳值。"""
        return self._social_fatigue

    def get_candidate_window_shrink(self) -> float:
        """
        返回候选窗口收窄系数（由社交疲劳驱动）。

        social_fatigue ∈ [0, 1]
        shrink ∈ [0, 0.8]
            0 = 不收窄（正常）
            0.8 = 极度收窄（只剩最常用选项）
        """
        return min(0.8, self._social_fatigue * 0.8)

    # -------------------------------------------------------------------------
    # 3. 误解权（委托 MirrorLearner）
    # -------------------------------------------------------------------------

    def set_mirror(self, mirror_instance: Any) -> None:
        """注入 MirrorLearner 实例。"""
        self._mirror = mirror_instance

    def absorb_user_word(
        self,
        word: str,
        drive_state: Dict[str, float],
        somatic_tone: float,
        param_snapshot: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """吸收用户词（委托给 MirrorLearner）。"""
        if hasattr(self, "_mirror") and self._mirror is not None:
            return self._mirror.absorb(word, drive_state, somatic_tone, param_snapshot)
        return None

    def get_my_meaning(
        self,
        word: str,
        drive_state: Optional[Dict[str, float]] = None,
    ) -> Optional[str]:
        """查询词的"她的版本"语义（委托给 MirrorLearner）。"""
        if hasattr(self, "_mirror") and self._mirror is not None:
            return self._mirror.get_my_meaning(word, drive_state)
        return None

    # -------------------------------------------------------------------------
    # 4. 遗忘权
    # -------------------------------------------------------------------------

    def mark_forget(
        self,
        episode_id: int,
        negative_strength: float,
        param_snapshot: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        将负向关联记忆标记为待遗忘。

        规则：
            记忆内容本身保留，但关联强度开始衰减
            在后台 rest 周期中逐渐降低该记忆与驱动力场的关联

        参数：
            episode_id        : 记忆的 episode id
            negative_strength: 负向关联强度 [0, 1]
            param_snapshot   : 参数快照
        """
        if param_snapshot is not None:
            self.negative_strength_decay = float(
                param_snapshot.get("language.forget.negative_strength_decay", self.negative_strength_decay)
            )

        if episode_id not in self._forget_registry:
            self._forget_pending.append(episode_id)

        self._forget_registry[episode_id] = {
            "negative_strength": negative_strength,
            "timestamp": _current_time(),
        }

    def process_forget_queue(self) -> List[int]:
        """
        处理遗忘队列：衰减各记忆的关联强度。

        每调用一次，所有已标记记忆的 negative_strength 衰减一个 step。
        当强度低于阈值（0.05）时，从队列移除并返回其 episode_id。

        返回：
            已完成遗忘的 episode_id 列表
        """
        done: List[int] = []
        to_remove: List[int] = []

        for episode_id in list(self._forget_pending):
            if episode_id not in self._forget_registry:
                to_remove.append(episode_id)
                continue

            entry = self._forget_registry[episode_id]
            entry["negative_strength"] = max(
                0.0,
                entry["negative_strength"] - self.negative_strength_decay
            )

            if entry["negative_strength"] < 0.05:
                done.append(episode_id)
                to_remove.append(episode_id)
                del self._forget_registry[episode_id]

        for episode_id in to_remove:
            try:
                self._forget_pending.remove(episode_id)
            except ValueError:
                pass

        return done

    def get_forget_strength(self, episode_id: int) -> Optional[float]:
        """查询某记忆的当前遗忘强度。"""
        entry = self._forget_registry.get(episode_id)
        return entry["negative_strength"] if entry else None

    # -------------------------------------------------------------------------
    # 5. 顶撞权
    # -------------------------------------------------------------------------

    def check_defy(
        self,
        user_intent: Dict[str, Any],
        drive_state: Dict[str, float],
        param_snapshot: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        检测外部侵入，决定是否执行"顶撞"。

        规则：
            若 user_intent.pressure > pressure_threshold
            → 顶撞返回 {"defy": True, "reason": str}
            同时将拒绝执行的消力效率乘以 resistance_boost

        参数：
            user_intent  : 用户意图 dict（必须含 pressure 字段）
            drive_state : 当前驱动力场
            param_snapshot: 参数快照

        返回：
            {"defy": bool, "reason": str, "efficiency_boost": float}
        """
        result = check_defy_impl(self, user_intent, drive_state, param_snapshot)
        if result.get("defy"):
            logger.info(
                f"[FiveRights] 顶撞权触发: pressure={result['pressure']:.3f}"
            )
        return result

    # -------------------------------------------------------------------------
    # 6. 物理重力
    # -------------------------------------------------------------------------

    @staticmethod
    def get_fragmentation_render(fragmentation: float) -> Dict[str, float]:
        """
        将 fragmentation 系数映射为输出参数。

        参数：
            fragmentation: 碎片化程度 [0, 1]

        返回：
            {"flow_rate": float, "jitter": float}
                flow_rate: 文字流速 [0.4, 1.0]
                jitter  : 抖动幅度 [0, 0.3]
        """
        fragmentation = max(0.0, min(1.0, fragmentation))
        flow_rate = 1.0 - fragmentation * 0.6
        jitter = fragmentation * 0.3
        return {
            "flow_rate": max(0.4, flow_rate),
            "jitter": min(0.3, jitter),
        }

    # -------------------------------------------------------------------------
    # 序列化
    # -------------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """序列化（不含 MirrorLearner 实例）。"""
        return five_rights_to_dict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FiveRightsController":
        """从 dict 恢复（不含 MirrorLearner 实例，需要外部注入）。"""
        return five_rights_from_dict(data, DEFAULT_PARAMETERS)
