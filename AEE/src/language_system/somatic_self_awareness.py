"""
Somatic Self-Awareness — 体感自我觉察（v1）

核心哲学：
    "我感到冷" vs "我正在感到冷"——后者是元觉察。
    体感自我觉察让 XIA 能对自身状态进行反思性命名，
    而不是仅仅被状态驱动着反应。

三层架构：
    1. 体感解码（SomatoDecoder）  — 从当前驱动力场解码出可命名的体感描述
    2. 自我参照生成（SelfRefGenerator） — 把体感描述注入自我参照框架
    3. 觉察强度调制（AwarenessScaler） — 根据元觉察置信度调制输出强度

零 LLM 依赖：纯规则 + BGE + 连续函数。
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# =============================================================================
# 可调参数
# =============================================================================

# 元觉察基准：状态偏离中性多少时开始触发自我觉察表达
AWARENESS_NEUTRAL = {
    "energy": 0.5, "loneliness": 0.3, "fatigue": 0.1, "stress": 0.1,
    "somatic_tone": 0.0, "curiosity": 0.5, "boredom": 0.2,
    "approach_drive": 0.5, "avoid_drive": 0.5,
}
AWARENESS_SENSITIVITY: float = 2.5  # sigmoid 陡峭度，越高越只在极端状态时触发
AWARENESS_MIN_SCORE: float = 0.30  # 低于此分数的体感描述不参与元觉察

# 维度偏离权重（影响自我觉察描述的优先级）
DIM_DEVIATION_WEIGHT: Dict[str, float] = {
    "loneliness":    1.4,  # 孤独是最核心的自我感知维度
    "somatic_tone":   1.3,  # 体感基调是躯体自我
    "fatigue":        1.2,  # 疲倦感强烈影响自我感知
    "boredom":       1.1,
    "stress":         1.0,
    "curiosity":      1.0,
    "approach_drive": 0.9,
    "avoid_drive":    0.9,
    "energy":         0.8,
}


# =============================================================================
# 体感解码器 — 把状态向量翻译成体感描述
# =============================================================================

# 体感描述表：从体感词到偏差方向和强度描述
# 格式：(体感词, 正向偏差词, 负向偏差词, 中性区宽度)
# 正向偏差 = 状态值 > 基准值
_SOMATIC_DESCRIPTIONS: Dict[str, Tuple[str, str, str, float]] = {
    "loneliness":    ("孤独",        "孤独",    "不孤独",    0.10),
    "fatigue":       ("累",          "累",      "精神",      0.08),
    "somatic_tone":  ("体感基调",    "舒服",    "难受",      0.10),
    "boredom":       ("无聊",        "无聊",    "有劲",      0.08),
    "stress":        ("紧张",        "紧张",    "放松",      0.08),
    "curiosity":     ("好奇",        "好奇",    "没兴趣",    0.10),
    "approach_drive":("想靠近",      "想靠近",  "想退开",    0.12),
    "avoid_drive":   ("想回避",      "想回避",  "不想躲",    0.12),
    "energy":        ("有精神",      "有精神",  "没劲",      0.10),
}


@dataclass
class SomatoDecoder:
    """
    体感解码器。

    输入：驱动力场字典 {dim: value}
    输出：按觉察强度加权的体感描述列表 [(desc, score, signed_deviation), ...]

    设计：
        - 偏差连续调制（continuous），不设硬阈值门
        - 所有维度并行参与，按 score 排序
        - 自我觉察 = Σ(score_i × DIM_WEIGHT_i)
    """

    def decode(
        self,
        drive_state: Dict[str, float],
        neutral_map: Optional[Dict[str, float]] = None,
    ) -> List[Tuple[str, float, float]]:
        """
        解码当前体感状态。

        参数：
            drive_state : 状态字典
            neutral_map : 中性基准值，默认为 AWARENESS_NEUTRAL

        返回：
            [(体感描述, 觉察强度_score, 有符号偏差_signed_dev), ...]
            按 score 降序排列
        """
        if neutral_map is None:
            neutral_map = AWARENESS_NEUTRAL

        results: List[Tuple[str, float, float]] = []

        for dim, (pos_label, pos_word, neg_word, neutral_width) in _SOMATIC_DESCRIPTIONS.items():
            current = float(drive_state.get(dim, neutral_map.get(dim, 0.5)))
            neutral = float(neutral_map.get(dim, 0.5))

            # 映射到 [-1, 1] 便于统一处理
            if dim == "somatic_tone":
                mapped_current = current  # 已经是 [-1, 1]
                mapped_neutral = neutral
            else:
                mapped_current = current * 2.0 - 1.0  # [0, 1] → [-1, 1]
                mapped_neutral = neutral * 2.0 - 1.0

            signed_dev = mapped_current - mapped_neutral  # 正=偏高，负=偏低
            abs_dev = abs(signed_dev)

            # sigmoid 调制：偏差越大，描述越强烈
            awareness_score = 1.0 / (1.0 + math.exp(-AWARENESS_SENSITIVITY * (abs_dev - neutral_width)))

            if awareness_score < AWARENESS_MIN_SCORE:
                continue

            # 选择描述词（正值用 pos_word，负值用 neg_word）
            desc = pos_word if signed_dev > 0.0 else neg_word

            # 乘以维度权重
            weight = DIM_DEVIATION_WEIGHT.get(dim, 1.0)
            final_score = awareness_score * weight

            results.append((desc, final_score, signed_dev))

        results.sort(key=lambda x: x[1], reverse=True)
        return results


# =============================================================================
# 自我参照生成器 — 把体感描述注入"我"框架
# =============================================================================

# 元觉察前缀词：注入自我参照框架
_AWARENESS_PREFIXES: Dict[str, Tuple[str, str]] = {
    # format: (高强度前缀, 低强度前缀)
    "loneliness":    ("好孤独",     "有点孤独"),
    "fatigue":       ("好累",       "有点累"),
    "somatic_tone":  ("体感",        ""),
    "boredom":       ("好无聊",     "有点无聊"),
    "stress":        ("紧张",       "有点紧张"),
    "curiosity":     ("好奇",        "有点好奇"),
    "approach_drive":("想靠近",      "想靠近"),
    "avoid_drive":   ("想退开",      "想躲"),
    "energy":        ("有精神",     "没劲"),
}

# 体感状态到躯体词的映射（躯体自我）
_TONE_TO_SOMATIC: Dict[str, Tuple[str, str]] = {
    # 格式: (正面词, 负面词)
    "somatic_tone":  ("舒服", "难受"),
    "fatigue":       ("不累", "累"),
    "loneliness":    ("被陪伴", "孤独"),
    "stress":        ("放松", "紧绷"),
    "energy":        ("有力", "没力"),
}


@dataclass
class SelfRefGenerator:
    """
    自我参照生成器。

    将体感解码结果注入"我"框架，生成元觉察表达候选。

    两种表达模式：
        - 描述模式："我感到孤独"（自我觉察层）
        - 躯体模式："胸口闷闷的"（体感直接映射，更原始）
    """

    def generate_self_ref(
        self,
        decoded: List[Tuple[str, float, float]],
        min_score: float = 0.40,
        top_k: int = 3,
    ) -> List[Tuple[str, float, str]]:
        """
        生成自我参照表达候选。

        参数：
            decoded  : SomatoDecoder.decode() 的输出
            min_score: 最低觉察强度阈值
            top_k    : 最多返回 k 个候选

        返回：
            [(表达文本, 觉察强度, 表达模式), ...]
            模式： "self_ref"（我感到…） | "somatic"（体感描述）
        """
        candidates: List[Tuple[str, float, str]] = []

        for desc, score, signed_dev in decoded:
            if score < min_score:
                continue

            # ---- 模式 A：自我觉察描述 "我感到X" ----
            # 用 sigmoid 决定用哪个强度前缀
            prefix_high, prefix_low = self._get_prefix(desc)
            if prefix_high and prefix_low:
                # sigmoid(score - 0.5) 在 score=0.5 时≈0.5，score=0.8 时≈0.82
                high_w = 1.0 / (1.0 + math.exp(-10.0 * (score - 0.55)))
                low_w = 1.0 - high_w
                prefix = (
                    prefix_high if high_w > low_w else prefix_low
                )
            else:
                prefix = prefix_high or prefix_low

            self_ref_text = f"我{prefix}"
            candidates.append((self_ref_text, score, "self_ref"))

            # ---- 模式 B：躯体直接描述 ----
            somatic_text = self._get_somatic(desc, signed_dev)
            if somatic_text:
                somatic_score = score * 0.75  # 躯体描述权重略低
                candidates.append((somatic_text, somatic_score, "somatic"))

        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates[:top_k]

    def _get_prefix(self, desc: str) -> Tuple[str, str]:
        """查询自我觉察前缀。"""
        return _AWARENESS_PREFIXES.get(desc, (f"{desc}", f"有点{desc}"))

    def _get_somatic(self, desc: str, signed_dev: float) -> Optional[str]:
        """查询躯体直接描述（正值=正面词，负值=负面词）。"""
        if desc not in _TONE_TO_SOMATIC:
            return None
        pos_word, neg_word = _TONE_TO_SOMATIC[desc]
        return pos_word if signed_dev > 0.0 else neg_word


# =============================================================================
# 觉察强度调制器 — 控制元觉察表达的出现频率和强度
# =============================================================================

@dataclass
class AwarenessScaler:
    """
    觉察强度调制器。

    防止元觉察过度占用语言输出。
    基于以下因素调制最终强度：
        1. 状态偏离强度（deviation）
        2. 表达历史冷却（recent 表达过则降低）
        3. 驱动力场拮抗程度（高拮抗→低输出）

    所有调制用连续乘积。
    """

    def scale(
        self,
        base_score: float,
        entity,
        decay_factor: float = 0.60,
    ) -> float:
        """
        调制自我觉察表达的最终强度。

        参数：
            base_score  : 原始觉察强度（0~1）
            entity      : EntityCore 实例
            decay_factor: 历史冷却衰减系数

        返回：
            调制后的强度（0~1）
        """
        scaled = base_score

        # 历史冷却：近期表达过则降低强度
        recent_awareness = getattr(entity, "_recent_self_awareness_ticks", [])
        current_tick = getattr(entity, "tick", 0)
        if recent_awareness:
            ticks_since = current_tick - max(recent_awareness)
            cooldown = math.exp(-ticks_since * 0.20)  # ~5 tick 恢复到 90%
            scaled *= decay_factor * (1.0 - cooldown) + cooldown

        # 拮抗抑制：高拮抗（alpha 高）时降低输出
        alpha = float(getattr(entity, "_behavior_alpha", 0.0))
        antagonism_suppression = 1.0 - alpha * 0.5
        scaled *= max(0.1, antagonism_suppression)

        return max(0.0, min(1.0, scaled))

    def record_expression(self, entity) -> None:
        """记录本次自我觉察表达，供下次冷却计算。"""
        current_tick = getattr(entity, "tick", 0)
        recent = list(getattr(entity, "_recent_self_awareness_ticks", []))
        recent.append(current_tick)
        entity._recent_self_awareness_ticks = recent[-5:]  # 保留最近 5 次


# =============================================================================
# 主接口 — 每 tick 调用一次
# =============================================================================

@dataclass
class SelfAwarenessSnapshot:
    """单次元觉察快照。"""
    tick: int = 0
    top_descriptions: List[str] = field(default_factory=list)
    dominant_feeling: str = ""
    awareness_intensity: float = 0.0
    expressions_generated: List[str] = field(default_factory=list)


class SomaticSelfAwareness:
    """
    体感自我觉察总控。

    组合 Decoder + Generator + Scaler，每 tick 提供元觉察候选表达。

    用法：
        aw = SomaticSelfAwareness()
        ctx = awareness.observe(entity.drive_state, entity)
        # ctx.expressions_generated → 注入语言系统候选池
    """

    def __init__(self) -> None:
        self._decoder = SomatoDecoder()
        self._generator = SelfRefGenerator()
        self._scaler = AwarenessScaler()
        self._history: List[SelfAwarenessSnapshot] = []

    def observe(
        self,
        drive_state: Dict[str, float],
        entity: Any,
    ) -> SelfAwarenessSnapshot:
        """
        执行一次元觉察观察。

        参数：
            drive_state : 驱动力场字典（通常是 drive_vector 或 state_snapshot）
            entity      : EntityCore 实例

        返回：
            SelfAwarenessSnapshot（含表达候选和觉察强度）
        """
        tick = getattr(entity, "tick", 0)

        # Step 1: 解码体感状态
        decoded = self._decoder.decode(drive_state)

        # Step 2: 生成自我参照表达
        raw_exprs = self._generator.generate_self_ref(decoded)

        # Step 3: 强度调制
        final_exprs: List[Tuple[str, float]] = []
        for text, score, mode in raw_exprs:
            scaled_score = self._scaler.scale(score, entity)
            if scaled_score > AWARENESS_MIN_SCORE:
                final_exprs.append((text, scaled_score))

        # Step 4: 打包快照
        top_descs = [d for d, _, _ in decoded[:3]]
        dominant = top_descs[0] if top_descs else ""
        top_intensity = decoded[0][1] if decoded else 0.0
        final_texts = [text for text, _ in final_exprs]

        snapshot = SelfAwarenessSnapshot(
            tick=tick,
            top_descriptions=top_descs,
            dominant_feeling=dominant,
            awareness_intensity=top_intensity,
            expressions_generated=final_texts,
        )

        self._history.append(snapshot)
        self._history[:] = self._history[-20:]  # 保留最近 20 个快照

        # 如果产生了表达，记录冷却
        if final_texts:
            self._scaler.record_expression(entity)

        logger.debug(
            f"[SelfAwareness] t={tick} dominant='{dominant}' "
            f"intensity={top_intensity:.2f} exprs={final_texts[:2]}"
        )

        return snapshot

    def get_dominant_feeling(self, entity: Any, drive_state: Dict[str, float]) -> str:
        """
        便捷接口：返回当前主导体感描述（最短形式）。
        用于直接注入锚点词候选池。
        """
        decoded = self._decoder.decode(drive_state)
        if not decoded:
            return ""
        return decoded[0][0]

    def get_awareness_candidates(
        self,
        drive_state: Dict[str, float],
        entity: Any,
        top_k: int = 2,
    ) -> List[str]:
        """
        返回最高质量的自我觉察表达候选列表。

        用于注入 s06a_candidates 的候选词池。
        """
        decoded = self._decoder.decode(drive_state)
        raw_exprs = self._generator.generate_self_ref(decoded)

        results: List[Tuple[str, float]] = []
        for text, score, mode in raw_exprs:
            scaled = self._scaler.scale(score, entity)
            if scaled > AWARENESS_MIN_SCORE:
                results.append((text, scaled))

        results.sort(key=lambda x: x[1], reverse=True)
        return [text for text, _ in results[:top_k]]

    def to_dict(self) -> dict:
        return {
            "history": [
                {
                    "tick": s.tick,
                    "top_descriptions": s.top_descriptions,
                    "dominant_feeling": s.dominant_feeling,
                    "awareness_intensity": round(s.awareness_intensity, 3),
                    "expressions_generated": s.expressions_generated,
                }
                for s in self._history
            ]
        }


# =============================================================================
# 快速单次调用接口
# =============================================================================

def get_self_awareness_exprs(
    drive_state: Dict[str, float],
    entity: Any,
    top_k: int = 2,
) -> List[str]:
    """
    快速接口：给定驱动力场和 entity，返回自我觉察表达候选。

    用于管线中快速注入候选词。
    """
    awareness = SomaticSelfAwareness()
    return awareness.get_awareness_candidates(drive_state, entity, top_k=top_k)
