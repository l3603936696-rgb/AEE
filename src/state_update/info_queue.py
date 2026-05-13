"""
info_queue.py — 后台信息队列模型（算力账本 v2.0）

定义待处理信息的种类、最小算力占用、消化速率和优先级。
不持久化——每轮根据当前状态重新推算。

五种信息维度：
    social     : 社交信息缺失（沉默时长驱动，有输入则归零）
    cognitive  : 预测误差/未解决问题（高 unresolved 时积累，有 rest 则消化）
    info       : 信息缺口（沉默时长驱动，有 explore 则消化）
    meta       : 基础元信息（每轮极微量增长，不可避免）
    emotional  : 负面情绪开销（somatic_tone 偏负时启动额外线程）

优先级（高→低）：
    stress_interrupt > social > cognitive > info > emotional > meta
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# ============================================================================
# 信息维度枚举
# ============================================================================

INFO_DIMENSIONS = ["social", "cognitive", "info", "meta", "emotional"]


# ============================================================================
# 信息项结构
# ============================================================================

@dataclass
class InfoItem:
    """
    单条待处理信息。
    """
    dimension: str          # social | cognitive | info | meta | emotional
    amount: float           # 该项占据的队列长度
    priority: float          # 处理优先级 [0, 1]
    created_at: float       # 创建时间戳（epoch 秒）
    source: str = ""        # 来源描述（用于调试）


# ============================================================================
# 默认算力占用参数（每轮）
# ============================================================================

# 各类信息的最小算力占用（归一化到总算力 1.0 的比例）
# 这些值代表"即使队列为空，这个维度的评估行为本身也要消耗多少"
DEFAULT_MIN_OCCUPANCY: Dict[str, float] = {
    "social":     0.0,   # 社交评估：有输入时归零，无输入时随沉默时长增长
    "cognitive":  0.02,  # 认知评估：始终有微小开销
    "info":       0.01,  # 信息评估：始终有微小开销
    "meta":       0.005, # 元信息：极低，不可消除
    "emotional":  0.0,   # 情绪开销：有负面情绪时才产生
}

# 每单位沉默时长（秒）产生的队列增量
# 仅 social 和 info 受沉默时长驱动
SILENCE_ACCUM_RATE: Dict[str, float] = {
    "social": 0.00005,   # 约 20000 秒（5.5小时）从 0 积到 1
    "info":   0.00003,   # 约 33000 秒（9小时）从 0 积到 1
}

# 每单位 unresolved（0~1）产生的队列增量
COGNITIVE_ACCUM_RATE: float = 0.03  # unresolved=1.0 时，每轮增加 0.03

# 每单位负面 somatic_tone（-1~0）产生的情绪开销
EMOTIONAL_ACCUM_RATE: float = 0.04  # tone=-1.0 时，每轮增加 0.04

# 各类信息每轮的消化速率（占当前队列的比例，rest 时乘以放大系数）
PROCESS_RATE: Dict[str, float] = {
    "social":     0.15,   # 社交信息消化较快
    "cognitive":  0.20,   # 认知信息需要时间处理
    "info":       0.10,   # 信息整合较慢
    "meta":       0.50,   # 元信息几乎不积累，随便消化
    "emotional":  0.25,   # 情绪开销需要时间平复
}

# rest 期间的消化放大系数（前台无对话，全部算力给后台）
REST_PROCESS_MULTIPLIER: float = 2.5

# stress 高优先级通道的算力分配比例
STRESS_PRIORITY_ALLOCATION: float = 0.20  # stress 占用总算力的 20%


# ============================================================================
# InfoQueue — 后台队列管理
# ============================================================================

@dataclass
class InfoQueue:
    """
    后台信息队列。

    不持久化——每轮根据当前状态重新推算积压量。
    通过 get_total_occupancy() 向 compute_load 报告总占用。
    """

    # 各维度的队列积压量（归一化到 [0, 1]）
    queues: Dict[str, float] = field(default_factory=lambda: {
        "social":     0.0,
        "cognitive":  0.0,
        "info":       0.0,
        "meta":       0.0,
        "emotional":  0.0,
    })

    # 各维度的最小算力占用（与 queues 独立，始终叠加）
    min_occupancy: Dict[str, float] = field(
        default_factory=lambda: dict(DEFAULT_MIN_OCCUPANCY)
    )

    # 当前是否处于社交输入状态（每轮由管线注入）
    has_social_input: bool = False

    # rest 标志（emergent_behavior 通知管线后，InfoQueue 在同一轮次生效）
    in_rest: bool = False

    # 运行记录（调试用）
    last_update: float = 0.0
    history: List[Dict[str, float]] = field(default_factory=list)  # 最近 N 轮记录

    # ---- Tick 标记（防止同一 tick 内重复积累）----
    _accumulated_tick: int = -1  # 已完成积累的 tick 编号

    # ---- 积累（每轮调用）----

    def accumulate(
        self,
        idle_seconds: float,
        loneliness: float,
        unresolved: float,
        somatic_tone: float,
        info_gap: float,
        has_social_input: bool,
        time_since_last_social: float,
        time_since_last_info: float,
        tick_index: int = 0,
    ) -> None:
        """
        计算本轮的队列增量。

        参数：
            idle_seconds           : 距上次状态更新的真实秒数
            loneliness             : 当前孤独感 [0, 1]
            unresolved             : 当前未解决感 [0, 1]
            somatic_tone           : 当前躯体基调 [-1, 1]
            info_gap               : 当前信息缺口 [0, 1]
            has_social_input       : 本轮是否有社交输入
            time_since_last_social : 距上次社交输入的秒数
            time_since_last_info   : 距上次信息获取的秒数
            tick_index             : 当前 tick 编号（用于防重）
        """
        # 防重：同一 tick 只积累一次
        if tick_index == self._accumulated_tick:
            return
        self._accumulated_tick = tick_index

        self.has_social_input = has_social_input
        dt = max(idle_seconds, 0.0)

        # ---- social：有输入则归零，无输入则随沉默时长增长 ----
        if has_social_input:
            # 正面社交输入 → 社交信息缺失被处理 → 队列清零
            self.queues["social"] = 0.0
        else:
            # 无社交输入 → 每秒积累，直到上限 1.0
            social_growth = self._silence_driven_growth(
                time_since_last_social, SILENCE_ACCUM_RATE["social"], dt
            )
            self.queues["social"] = min(1.0, self.queues["social"] + social_growth)

        # ---- cognitive：unresolved 高则积累，rest 时消化 ----
        if self.in_rest:
            # rest 期间全力消化（后面 process() 会处理，这里不主动减少）
            pass
        else:
            # 非 rest：unresolved 驱动积累（预测误差越大，待处理认知任务越多）
            cognitive_growth = unresolved * COGNITIVE_ACCUM_RATE * dt / 60.0
            self.queues["cognitive"] = min(1.0, self.queues["cognitive"] + cognitive_growth)

        # ---- info：info_gap 高则积累，explore 时消化 ----
        # info_gap 本身随沉默时长增长，explore 会清空（由管线通知）
        info_growth = self._silence_driven_growth(
            time_since_last_info, SILENCE_ACCUM_RATE["info"], dt
        )
        self.queues["info"] = min(1.0, self.queues["info"] + info_growth)

        # ---- meta：极低且不可消除 ----
        meta_growth = DEFAULT_MIN_OCCUPANCY["meta"] * dt / 60.0
        self.queues["meta"] = min(1.0, self.queues["meta"] + meta_growth)

        # ---- emotional：somatic_tone 偏负时产生额外线程 ----
        if somatic_tone < -0.1:
            emotional_growth = (-somatic_tone) * EMOTIONAL_ACCUM_RATE * dt / 60.0
            self.queues["emotional"] = min(1.0, self.queues["emotional"] + emotional_growth)
        else:
            # tone 改善时，情绪开销自然消退
            self.queues["emotional"] = max(0.0, self.queues["emotional"] - 0.01 * dt / 60.0)

    def _silence_driven_growth(
        self, silence_seconds: float, rate: float, dt: float
    ) -> float:
        """
        沉默驱动的线性积累（用于 social 和 info）。

        增长 = rate * dt（线性，非指数）
        dt 单位为秒，rate 是每秒的增长量（已校准到合理范围）。
        """
        return min(rate * dt, 0.05)  # 单轮最多增加 0.05，避免突变

    # ---- 消化（每轮调用，accumulate 之后）----

    def process(self, action_type: str) -> None:
        """
        根据本轮行为类型消化队列。

        参数：
            action_type : 本轮涌现的行为类型（rest / explore / seek / comfort / idle / avoid）
        """
        multiplier = REST_PROCESS_MULTIPLIER if self.in_rest else 1.0

        if action_type == "rest" or self.in_rest:
            # rest：全力消化所有队列
            for dim in INFO_DIMENSIONS:
                if dim == "meta":
                    continue  # meta 几乎不积累，不需要消化
                rate = PROCESS_RATE[dim] * multiplier
                self.queues[dim] = max(0.0, self.queues[dim] - rate)

        elif action_type == "explore":
            # explore：清空 info 队列（获取了新信息并整合）
            self.queues["info"] = max(0.0, self.queues["info"] - 0.80)

        elif action_type == "comfort":
            # comfort：清空 social 队列（社交信息缺失被处理）
            self.queues["social"] = max(0.0, self.queues["social"] - 0.80)

        elif action_type == "seek":
            # seek：部分消化 social 和 cognitive
            self.queues["social"] = max(0.0, self.queues["social"] - 0.30)
            self.queues["cognitive"] = max(0.0, self.queues["cognitive"] - 0.20)

        # idle / avoid：队列维持不变，自然积累

        # 记录历史（保留最近 5 轮）
        self.history.append(dict(self.queues))
        if len(self.history) > 5:
            self.history.pop(0)

    # ---- 外部通知 ----

    def notify_rest_start(self) -> None:
        """emergent_behavior 通知进入 rest，InfoQueue 在本轮立即生效。"""
        self.in_rest = True

    def notify_rest_end(self) -> None:
        """rest 结束，恢复正常消化倍率。"""
        self.in_rest = False

    def notify_explore(self) -> None:
        """explore 动作执行，清空 info 队列。"""
        self.queues["info"] = 0.0

    # ---- 读取接口（供 compute_load 和 emergent_behavior 使用）----

    def get_total_queue_occupancy(self) -> float:
        """
        返回队列积压总量（不含 min_occupancy）。
        用于计算 queue_growth_rate。
        """
        return sum(self.queues.values())

    def get_min_occupancy(self) -> float:
        """返回最小算力占用（各维度的 baseline 评估开销）。"""
        return sum(self.min_occupancy.values())

    def get_stress_occupancy(self, stress: float) -> float:
        """
        stress 作为高优先级中断通道的算力占用。
        直接占用总算力的一定比例，与队列无关。
        """
        return STRESS_PRIORITY_ALLOCATION * stress

    def get_dim_occupancy(self, dim: str) -> float:
        """返回指定维度的总占用（队列 + min_occupancy）。"""
        if dim not in INFO_DIMENSIONS:
            return 0.0
        return self.queues.get(dim, 0.0) + self.min_occupancy.get(dim, 0.0)

    def get_summary(self) -> Dict[str, float]:
        """返回队列摘要（供调试）。"""
        return dict(self.queues)

    # ---- 队列速率计算（供 emergent_behavior 的 rest 触发判断使用）----

    def compute_growth_rate(self) -> float:
        """
        估算当前队列的积累速率（简化版：基于当前 queues 值）。

        返回：积累速率 [0, 1]，代表每秒的队列增长量。
        """
        # 各维度当前积压量对应的增长率估算
        social_rate = self.queues["social"] * SILENCE_ACCUM_RATE["social"]
        cognitive_rate = self.queues["cognitive"] * 0.001  # unresolved=1 时约 0.001/s
        info_rate = self.queues["info"] * SILENCE_ACCUM_RATE["info"]
        emotional_rate = self.queues["emotional"] * 0.001
        return social_rate + cognitive_rate + info_rate + emotional_rate

    def compute_process_rate(self, available_capacity: float, in_rest: bool) -> float:
        """
        估算当前消化能力。

        参数：
            available_capacity : 当前可用算力（归一化 [0, 1]）
            in_rest           : 是否处于 rest 状态

        返回：消化能力（每秒可处理的队列量）
        """
        base = available_capacity * 0.1  # 基础消化能力与可用算力成正比
        if in_rest:
            base *= REST_PROCESS_MULTIPLIER
        return base
