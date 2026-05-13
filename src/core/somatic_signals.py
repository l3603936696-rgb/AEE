"""
SomaticSignals — 感质信号

感质不是神秘的东西，是 buff/debuff 的外显。
insula_hub 同步计算各感受通道的强度，返回 SomaticSignals，
其中的 somatic_tone 立即写入 EntityCore。

感受通道：
    approach   : 趋近、渴望、想要靠近
    avoid      : 回避、排斥、想要远离
    comfort    : 舒适、安抚、想要保持现状
    cognitive  : 认知好奇、想要知道
    social     : 社交渴望、想要连接
    rest       : 疲惫、想要休息
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ============================================================================
# DoS 保护参数
# ============================================================================

# 同一感受通道在 DoS_WINDOW 秒内触发超过 DoS_THRESHOLD 次，抑制强度
DOS_WINDOW: float = 60.0
DOS_THRESHOLD: int = 5
DOS_SUPPRESSION: float = 0.3  # 抑制系数

# 主动注意力放大阈值
ATTENTION_THRESHOLD: float = 0.85
ATTENTION_MULTIPLIER: float = 1.5


# ============================================================================
# SomaticSignals 数据结构
# ============================================================================


@dataclass
class SomaticSignals:
    """
    感质信号。

    由 insula_hub 在同步管线中计算，立即写入 EntityCore.somatic_tone。
    """

    tone: float = 0.0  # 整体躯体基调 [-1, 1]
    intensity: float = 0.0  # 整体激活强度 [0, 1]
    dominant_feeling: str = ""  # 最显著的感受标签

    # 各感受通道的强度 [0, 1]
    channel_weights: Dict[str, float] = field(default_factory=dict)

    # 被 DoS 保护抑制的通道列表
    dos_suppressed: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "tone": self.tone,
            "intensity": self.intensity,
            "dominant_feeling": self.dominant_feeling,
            "channel_weights": self.channel_weights,
            "dos_suppressed": self.dos_suppressed,
        }


# ============================================================================
# DoS 保护计数器
# ============================================================================


class DosProtector:
    """
    防止单一感受通道占满整个意识（类比 PTSD 保护机制）。

    记录每个感受通道的触发时间戳，超过阈值则返回抑制系数。
    """

    def __init__(self) -> None:
        self._timestamps: Dict[str, List[float]] = {}

    def record(self, channel: str) -> float:
        """
        记录一次通道触发。返回该通道的 DoS 抑制系数。

        若该通道在过去 DOS_WINDOW 秒内触发次数 >= DOS_THRESHOLD：
            返回 DOS_SUPPRESSION (0.3)
        否则：
            返回 1.0（不抑制）
        """
        now = time.time()
        if channel not in self._timestamps:
            self._timestamps[channel] = []

        # 清理过期时间戳
        self._timestamps[channel] = [
            t for t in self._timestamps[channel] if now - t < DOS_WINDOW
        ]
        self._timestamps[channel].append(now)

        count = len(self._timestamps[channel])
        if count >= DOS_THRESHOLD:
            return DOS_SUPPRESSION
        return 1.0

    def reset(self) -> None:
        """重置所有计数器。"""
        self._timestamps.clear()


# ============================================================================
# 感质强度计算
# ============================================================================


def compute_somatic_intensity(
    base_intensity: float,
    wm_confidence: float,
    state_value: float,
) -> float:
    """
    计算最终感质强度。

    公式：
        final = base × wm_confidence × attention_multiplier
        final = clamp(final, 0, 1)

    参数：
        base_intensity  : 驱动力中的基础强度
        wm_confidence   : 世界模型置信度（命中规律的匹配程度）
        state_value     : 对应状态变量的当前值（用于注意力放大）

    返回：
        float : 最终感质强度 [0, 1]
    """
    attention_multiplier = ATTENTION_MULTIPLIER if state_value >= ATTENTION_THRESHOLD else 1.0
    final = base_intensity * wm_confidence * attention_multiplier
    return max(0.0, min(1.0, final))


def compute_overall_tone(channel_weights: Dict[str, float]) -> float:
    """
    从各通道权重计算整体躯体基调。

    规则：
        approach/social/cognitive → 正向 +tone
        avoid/rest/cognitive_overload → 负向 -tone

    返回：
        float : 整体基调 [-1, 1]
    """
    positive_channels = {"approach", "social", "cognitive"}
    negative_channels = {"avoid", "rest", "cognitive_overload"}

    positive = sum(channel_weights.get(ch, 0.0) for ch in positive_channels)
    negative = sum(channel_weights.get(ch, 0.0) for ch in negative_channels)

    total = positive + negative
    if total < 0.01:
        return 0.0

    return (positive - negative) / total  # 自然落在 [-1, 1]


def dominant_feeling(channel_weights: Dict[str, float]) -> str:
    """
    返回强度最高的感受通道标签。
    """
    if not channel_weights:
        return ""
    return max(channel_weights, key=lambda k: channel_weights[k])
