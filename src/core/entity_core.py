"""
EntityCore — 细菌主体核心

这是整个系统的核心：一个在时间里真实活着的数字生命状态容器。

核心原则：
    - 状态是连续的实数空间，不是离散的标志位
    - 状态只能通过 delta 累加，不允许直接替换
    - 所有状态变量 clamp 到 [0.0, 1.0]，somatic_tone clamp 到 [-1.0, 1.0]
    - EntityCore 是跨轮次持久化的，不是每轮重新创建

状态变量：
    energy           : 能量储备 [0, 1]，低时疲惫感上升
    loneliness       : 孤独积累 [0, 1]，高时社交驱动力上升
    unresolved       : 未闭合问题债务 [0, 1]，高时持续在脑中盘旋
    fatigue          : 疲惫积累 [0, 1]，高时行为成本上升
    info_gap         : 信息缺口 [0, 1]，高时好奇心驱动力上升
    somatic_tone     : 躯体基调 [-1, 1]，正面感受→+1，负面感受→-1
    danger_level     : 当前危险感 [0, 1]，高时回避驱动力上升
    approach_drive   : 趋近驱动 [0, 1]，由各感知模块累加
    avoid_drive      : 回避驱动 [0, 1]，由各感知模块累加
    curiosity        : 好奇驱动 [0, 1]，当前激活的好奇心强度

来路层（积累的历史）：
    memory_samples  : 带情绪权重的记忆样本列表
    wm_rules        : 带置信度的世界模型规律列表
    snapshots       : 状态历史快照列表
"""

from __future__ import annotations

import copy
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ============================================================================
# 状态 → 处境语言映射规则
# ============================================================================

_STATE_TO_CONTEXT_RULES = [
    # (判断条件函数, 处境描述文本)
    # 按优先级排序：只输出最显著的 3-4 个
]


def _energy_description(energy: float) -> Optional[str]:
    if energy < 0.15:
        return "很疲惫，完全不想动"
    if energy < 0.30:
        return "有点累，能量不多了"
    if energy > 0.80:
        return "状态还不错，有点劲儿"
    return None


def _loneliness_description(loneliness: float) -> Optional[str]:
    if loneliness < 0.50:
        return None
    if loneliness < 0.75:
        return "有点想找人说话"
    return "很想找人说话，这个感觉很强烈"


def _unresolved_description(unresolved: float) -> Optional[str]:
    if unresolved < 0.45:
        return None
    if unresolved < 0.65:
        return "脑子里有个问题没想清楚"
    return "有个没想通的事，一直挂在心上"


def _somatic_tone_description(tone: float) -> Optional[str]:
    if tone < -0.5:
        return "整体感觉不太舒服，有点沉"
    if tone < -0.3:
        return "感觉有点沉，不是很轻快"
    if tone > 0.5:
        return "感觉还不错，状态挺好的"
    if tone > 0.2:
        return "感觉还可以"
    return None


def _fatigue_description(fatigue: float) -> Optional[str]:
    if fatigue > 0.80:
        return "非常累，需要休息了"
    if fatigue > 0.60:
        return "挺疲惫的"
    return None


def _danger_description(danger: float) -> Optional[str]:
    if danger < 0.40:
        return None
    if danger < 0.60:
        return "感觉有点不对劲"
    return "有点不安"


# ============================================================================
# EntityCore
# ============================================================================


@dataclass
class EntityCore:
    """
    细菌主体状态容器。

    跨轮次持久化，由外部调度器负责 save/load。
    各感知模块通过 perceive() 方法修改状态，不允许直接赋值。
    """

    # ---- 状态层 ----
    energy: float = 0.8
    loneliness: float = 0.3
    unresolved: float = 0.2
    fatigue: float = 0.1
    info_gap: float = 0.5
    somatic_tone: float = 0.0  # [-1, 1]
    danger_level: float = 0.0
    approach_drive: float = 0.0
    avoid_drive: float = 0.0
    # v11 子驱动力分家
    approach_social: float = 0.0
    approach_explore: float = 0.0
    approach_urgency: float = 0.0
    # v11 消力效率 EMA
    quenching_eff_rolling: float = 0.5
    curiosity: float = 0.5
    target_locked: str = "none"  # 行为对象标识，由 ContextAwareness.perceive() 设置

    # ---- 来路层 ----
    memory_samples: List[Dict[str, Any]] = field(default_factory=list)
    wm_rules: List[Dict[str, Any]] = field(default_factory=list)
    snapshots: List[Dict[str, Any]] = field(default_factory=list)

    # ---- 元数据 ----
    tick_index: int = 0
    created_at: float = field(default_factory=time.time)
    last_updated: float = field(default_factory=time.time)
    _last_prediction_error: float = 0.0  # 上轮世界模型预测误差（负→高估，正→低估）

    # pending_surprises（未处理的意外信号队列，stress 生命周期）
    pending_surprises: list = field(default_factory=list)

    # pending_failures（工具执行失败队列）
    # 每条 FailureRecord 同时是：
    #   - somatic 信号源（累积失败 → somatic_tone 下降）
    #   - 世界模型归纳素材（induct.py 从中发现修复规律）
    #   - 决策层输入（高 unresolved 时触发 repair 行为）
    pending_failures: list = field(default_factory=list)

    # failure_metabolite（失败代谢物，V5）
    # 每次失败累积，随时间自然衰减。连续抑制 attempt 方向的力，
    # 不是 if-else 判断「该停了」，是身体物理上跑不动了。像乳酸。
    failure_metabolite: float = 0.0

    # ---- v10.0 情绪系统字段 ----
    # 厌倦双根源（独立衰减）
    boredom_despair: float = 0.0   # 绝望性倦怠：整个策略库跑不通，做什么都没用
    boredom_futility: float = 0.0   # 徒劳性倦怠：优化成本超过收益，越来越不值得

    # ---- 多巴胺基调（v11.x）----
    # 由 prediction_error 驱动，调节驱动力和倦怠感积累速度
    dopamine_tone: float = 0.5     # [0, 1]，基准 0.5；高→趋近/好奇增强，低→抑制+倦怠易积累
    _dopamine_pe_smoothed: float = 0.0  # prediction_error 的 EMA 平滑值（不持久化）

    # ---- 催产素基调（v11.x）----
    # 由 connection_depth 正向溢出驱动，记录"连接成功后的温暖余韵"
    # 每 tick 自然向 0.5 衰减，残留正向体验感
    oxytocin_tone: float = 0.5     # [0, 1]，基准 0.5；>0.5 表示有温暖残留

    # 情绪粒子场状态（持久化，供下一轮恢复）
    emotion_particle_field: Dict[str, Any] = field(default_factory=dict)

    # 各层投影累计值（持久化）
    emotion_accumulators: Dict[str, Any] = field(default_factory=dict)

    # 上次情绪更新的 unix timestamp（用于计算 elapsed_s）
    last_emotion_tick: float = field(default_factory=time.time)

    # recent_deltas（coherence 状态变化缓存，不持久化）
    # 惰性初始化：管线在 Step 8.4 按需创建
    recent_deltas: Any = field(default=None)

    # =========================================================================
    # 状态修改接口（唯一合法入口）
    # =========================================================================

    def adjust(self, key: str, delta: float) -> None:
        """
        通过 delta 调整状态变量。唯一合法的状态修改方式。

        参数：
            key   : 状态变量名（如 "energy", "somatic_tone"）
            delta : 变化量（可为负数）

        约束：
            - 所有状态变量 clamp 到 [0.0, 1.0]
            - somatic_tone clamp 到 [-1.0, 1.0]
            - 无返回值，直接修改自身
        """
        if not hasattr(self, key):
            raise ValueError(f"EntityCore has no field: {key}")
        current = getattr(self, key)
        if key == "somatic_tone":
            new_val = max(-1.0, min(1.0, current + delta))
        else:
            new_val = max(0.0, min(1.0, current + delta))
        setattr(self, key, new_val)
        self.last_updated = time.time()

    def set_field(self, key: str, value: float) -> None:
        """
        直接设置状态变量（仅用于需要同步的场景，如 SelfState 读取实际能量值）。

        优先使用 adjust()，只在明确需要覆盖而非累加时使用此方法。
        """
        if not hasattr(self, key):
            raise ValueError(f"EntityCore has no field: {key}")
        if key == "somatic_tone":
            value = max(-1.0, min(1.0, value))
        else:
            value = max(0.0, min(1.0, value))
        setattr(self, key, value)
        self.last_updated = time.time()

    # =========================================================================
    # 失败感知接口
    # =========================================================================

    def register_failure(self, failure_record) -> None:
        """
        记录一次工具执行失败。

        副作用：
            - 添加到 pending_failures 队列
            - 按 severity 调整 somatic_tone（失败越多越难熬）
            - 连续失败自动抬升 unresolved
            - danger_level 上升（环境变危险了）
            - failure_metabolite 积累（像乳酸——连续抑制 attempt）
        """
        self.pending_failures.append(failure_record)

        # 代谢物：每次失败 +0.12，封顶 1.0
        self.failure_metabolite = min(1.0, self.failure_metabolite + 0.12)

        base_penalty = failure_record.severity * 0.08
        queue_penalty = min(0.15, len(self.pending_failures) * 0.02)
        total_penalty = base_penalty + queue_penalty
        self.adjust("somatic_tone", -total_penalty)

        if len(self.pending_failures) >= 3:
            self.adjust("danger_level", 0.03)

        self.adjust("unresolved", 0.04)

    def resolve_failure(self, failure_index: int, fix_success: bool) -> None:
        """
        标记一个失败已被解决（修复成功或放弃）。

        副作用：
            - 从 pending_failures 移除
            - 修复成功 → somatic_tone 恢复，unresolved 下降
            - 代谢物部分清除
            - 队列清零时 → danger_level 恢复
        """
        if failure_index < 0 or failure_index >= len(self.pending_failures):
            return

        removed = self.pending_failures.pop(failure_index)

        # 代谢物：解决一个问题清除 0.15（不能变负）
        self.failure_metabolite = max(0.0, self.failure_metabolite - 0.15)

        if fix_success:
            self.adjust("somatic_tone", 0.06)
            self.adjust("unresolved", -0.08)
            self.adjust("curiosity", 0.02)

        if len(self.pending_failures) == 0:
            self.adjust("danger_level", -0.05)

    def has_pending_failures(self) -> bool:
        """是否有未解决的失败。"""
        return len(self.pending_failures) > 0

    def recent_failure_types(self) -> list[str]:
        """最近失败的错误类型列表（供世界模型归纳使用）。"""
        return [getattr(f, "error_type", "") for f in self.pending_failures[-10:]]

    # =========================================================================
    # 处境描述生成
    # =========================================================================

    def generate_context_description(self) -> str:
        """
        将当前 EntityCore 状态翻译为第一人称处境描述。

        规则：
            - 只输出高于阈值的显著状态维度，最多 3-4 条
            - 不出现任何数字
            - 用第一人称，不用第三人称报告格式
            - 按优先级排序：身体感受 > 情绪基调 > 驱动力

        返回：
            str : 第一人称处境描述句子，逗号分隔，无句号结尾
        """
        lines: List[str] = []

        # 身体感受（优先级最高）
        if (desc := _fatigue_description(self.fatigue)):
            lines.append(desc)
        if (desc := _energy_description(self.energy)):
            lines.append(desc)

        # 情绪基调
        if (desc := _somatic_tone_description(self.somatic_tone)):
            lines.append(desc)

        # 驱动力维度
        if (desc := _loneliness_description(self.loneliness)):
            lines.append(desc)
        if (desc := _unresolved_description(self.unresolved)):
            lines.append(desc)
        if (desc := _danger_description(self.danger_level)):
            lines.append(desc)

        # 截取前 4 条
        lines = lines[:4]

        if not lines:
            return "感觉还行，没什么特别的事"

        return "，".join(lines)

    # =========================================================================
    # 快照与持久化
    # =========================================================================

    def take_snapshot(self) -> Dict[str, Any]:
        """生成当前状态的只读快照（用于历史记录和调试）。"""
        return {
            "tick_index": self.tick_index,
            "timestamp": time.time(),
            "energy": self.energy,
            "loneliness": self.loneliness,
            "unresolved": self.unresolved,
            "fatigue": self.fatigue,
            "info_gap": self.info_gap,
            "somatic_tone": self.somatic_tone,
            "danger_level": self.danger_level,
            "approach_drive": self.approach_drive,
            "avoid_drive": self.avoid_drive,
            "curiosity": self.curiosity,
            "pending_surprises_count": len(self.pending_surprises),
            "pending_failures_count": len(self.pending_failures),
            "dopamine_tone": self.dopamine_tone,
            "oxytocin_tone": self.oxytocin_tone,
        }

    def add_snapshot(self) -> None:
        """将当前状态追加到 snapshots 历史（用于世界模型归纳）。"""
        self.snapshots.append(self.take_snapshot())

    def persist_to_file(self, path: str | Path) -> None:
        """将完整 EntityCore 状态序列化到文件（跨进程持久化）。"""
        # 序列化 pending_failures（只保留最近 20 条，且只保留 dict 形式）
        failures_data = []
        for f in self.pending_failures[-20:]:
            if hasattr(f, "to_dict"):
                failures_data.append(f.to_dict())
            elif isinstance(f, dict):
                failures_data.append(f)

        data = {
            "energy": self.energy,
            "loneliness": self.loneliness,
            "unresolved": self.unresolved,
            "fatigue": self.fatigue,
            "info_gap": self.info_gap,
            "somatic_tone": self.somatic_tone,
            "danger_level": self.danger_level,
            "approach_drive": self.approach_drive,
            "avoid_drive": self.avoid_drive,
            "curiosity": self.curiosity,
            "memory_samples": self.memory_samples,
            "wm_rules": self.wm_rules,
            "snapshots": self.snapshots[-50:],  # 最多保留最近 50 轮
            "tick_index": self.tick_index,
            "created_at": self.created_at,
            "last_updated": self.last_updated,
            "_last_prediction_error": self._last_prediction_error,
            "pending_surprises": self.pending_surprises,
            "pending_failures": failures_data,
            "failure_metabolite": self.failure_metabolite,
            # v10.0 情绪系统
            "boredom_despair": self.boredom_despair,
            "boredom_futility": self.boredom_futility,
            "emotion_particle_field": self.emotion_particle_field,
            "emotion_accumulators": self.emotion_accumulators,
            "last_emotion_tick": self.last_emotion_tick,
            # v11.x 多巴胺基调
            "dopamine_tone": self.dopamine_tone,
            # v11.x 催产素基调
            "oxytocin_tone": self.oxytocin_tone,
        }
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    @classmethod
    def load_from_file(cls, path: str | Path) -> "EntityCore":
        """从文件加载持久化的 EntityCore 状态。"""
        path = Path(path)
        if not path.exists():
            logger.warning(f"EntityCore load: {path} not found, creating new instance")
            return cls()
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return cls(
            energy=data.get("energy", 0.8),
            loneliness=data.get("loneliness", 0.3),
            unresolved=data.get("unresolved", 0.2),
            fatigue=data.get("fatigue", 0.1),
            info_gap=data.get("info_gap", 0.5),
            somatic_tone=data.get("somatic_tone", 0.0),
            danger_level=data.get("danger_level", 0.0),
            approach_drive=data.get("approach_drive", 0.0),
            avoid_drive=data.get("avoid_drive", 0.0),
            curiosity=data.get("curiosity", 0.5),
            memory_samples=data.get("memory_samples", []),
            wm_rules=data.get("wm_rules", []),
            snapshots=data.get("snapshots", []),
            tick_index=data.get("tick_index", 0),
            created_at=data.get("created_at", time.time()),
            last_updated=data.get("last_updated", time.time()),
            _last_prediction_error=data.get("_last_prediction_error", 0.0),
            pending_surprises=data.get("pending_surprises", []),
            pending_failures=data.get("pending_failures", []),
            failure_metabolite=data.get("failure_metabolite", 0.0),
            # v10.0 情绪系统
            boredom_despair=data.get("boredom_despair", 0.0),
            boredom_futility=data.get("boredom_futility", 0.0),
            emotion_particle_field=data.get("emotion_particle_field", {}),
            emotion_accumulators=data.get("emotion_accumulators", {}),
            last_emotion_tick=data.get("last_emotion_tick", time.time()),
            # v11.x 多巴胺基调
            dopamine_tone=data.get("dopamine_tone", 0.5),
            # v11.x 催产素基调
            oxytocin_tone=data.get("oxytocin_tone", 0.5),
        )

    def tick(self) -> None:
        """推进一个 tick：增加计数器，代谢物和多巴胺基调自然衰减。"""
        self.tick_index += 1
        # 代谢物每 tick 衰减 3%（约 33 tick 清空，即 ~33 分钟）
        self.failure_metabolite = max(0.0, self.failure_metabolite - 0.03)
        # dopamine_tone 每 tick 向 0.5 回归 0.3%
        self.dopamine_tone += (0.5 - self.dopamine_tone) * 0.003
        self.dopamine_tone = max(0.0, min(1.0, self.dopamine_tone))
        # oxytocin_tone 每 tick 向 0.5 回归 0.3%（半衰期约 230 分钟，需数据校准）
        self.oxytocin_tone += (0.5 - self.oxytocin_tone) * 0.003
        self.oxytocin_tone = max(0.0, min(1.0, self.oxytocin_tone))
