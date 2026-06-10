"""
Emotion System — 三层情绪投影模块（v10.0 / v11.0）

三层情绪模型：
    主线层（mainline）  — 十个核心情绪大类，决定行为方向
    日常层（daily）    — 情绪粒子场，提供背景纹理
    记忆层（memory）   — 高情绪冲击事件的固化与投影

导出：
    ParticleField          — 日常层粒子场
    ProjectionController    — 三层投影阻尼控制
    DecayEngine            — 情绪衰减引擎
    InsightWriter           — 惊讶→Insights 写入
"""

from .particle_field import ParticleField
from .projection_controller import ProjectionController
from .decay_engine import DecayEngine
from .insight_writer import InsightWriter
from .emotion_compute import compute_emotions

__all__ = [
    "ParticleField",
    "ProjectionController",
    "DecayEngine",
    "InsightWriter",
    "compute_emotions",
]
