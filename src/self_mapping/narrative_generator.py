"""
NarrativeGenerator — 预测性内部叙事生成器

生成 XIA 的内部自我叙事（纯内部，不上报 LLM）。

预测性叙事格式：
    这一轮我感知到 {cause} {direction}了，
    基于我的经验（meta_confidence={conf:.2f}），
    {cause} 变化通常会导致我接下来 {effect} {effect_dir}。

下轮管线运行时，coherence_meta 对比预测和实际，更新 relation 置信度。

与 SelfBodyMap 的关系：
    NarrativeGenerator 使用 SelfBodyMap 的 parts 和 relations，
    生成叙事后写回 SelfBodyMap.last_narrative。
    verify_narrative() 在下一轮管线中调用 SelfBodyMap.verify_last_prediction()。
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


# ============================================================================
# NarrativeRecord — 叙事记录
# ============================================================================

@dataclass
class NarrativeRecord:
    """
    单条内部叙事记录（供 coherence_meta 验证使用）。

    字段：
        tick            : 生成时的 tick
        cause           : 变化的部位
        effect          : 预测的下游部位
        cause_direction : cause 变化方向（+1=上升，-1=下降）
        text            : 叙事文本（纯内部）
        confidence      : 该叙事的 meta_confidence
    """
    tick: int
    cause: str
    effect: str
    cause_direction: int  # +1 = 上升, -1 = 下降
    text: str
    confidence: float


# ============================================================================
# NarrativeGenerator
# ============================================================================

class NarrativeGenerator:
    """
    生成和验证预测性内部叙事。

    用法（每轮管线调用一次）：

        gen = NarrativeGenerator()

        # 1. 生成本轮叙事（基于变化 + relations）
        narrative = gen.generate(parts, changes, relations, tick)

        # 2. 下轮管线验证（对比预测和实际）
        verified = gen.verify(narrative, parts_after_verification)
    """

    def __init__(self) -> None:
        self._history: List[NarrativeRecord] = []
        self._last: Optional[NarrativeRecord] = None

    # ------------------------------------------------------------------ #
    # 生成
    # ------------------------------------------------------------------ #

    def generate(
        self,
        parts: Dict[str, tuple[float, float]],
        changes: Dict[str, float],
        relations: List[Any],
        tick: int,
    ) -> Optional[NarrativeRecord]:
        """
        基于本轮状态变化和关系图生成预测性叙事。

        参数：
            parts     : SelfBodyMap.parts {name: (prev, curr)}
            changes   : SelfBodyMap._changes {name: delta}
            relations : List[Relation]
            tick      : 当前 tick

        返回：
            NarrativeRecord 或 None（无变化或无匹配 relation）
        """
        if not changes:
            self._last = None
            return None

        candidates: List[tuple[NarrativeRecord, float]] = []

        for cause, delta in changes.items():
            direction = "上升" if delta > 0 else "下降"
            effect_dir = "增加" if delta > 0 else "减少"
            cause_dir_int = 1 if delta > 0 else -1

            for rel in relations:
                if rel.cause != cause:
                    continue
                if getattr(rel, "is_stale", False):
                    continue

                effect = rel.effect
                conf = float(getattr(rel, "meta_confidence", 0.5))

                text = (
                    f"这一轮我感知到 {cause} {direction}了，"
                    f"基于我的经验（meta_confidence={conf:.2f}），"
                    f"{cause} 变化通常会导致我接下来 {effect} {effect_dir}。"
                )

                record = NarrativeRecord(
                    tick=tick,
                    cause=cause,
                    effect=effect,
                    cause_direction=cause_dir_int,
                    text=text,
                    confidence=conf,
                )
                candidates.append((record, conf))

        if not candidates:
            self._last = None
            return None

        # 选 meta_confidence 最高的叙事
        best, _ = max(candidates, key=lambda x: x[1])
        self._last = best
        self._history.append(best)
        # 保留最近 30 条
        if len(self._history) > 30:
            self._history = self._history[-30:]

        return best

    # ------------------------------------------------------------------ #
    # 验证
    # ------------------------------------------------------------------ #

    def verify(
        self,
        narrative: Optional[NarrativeRecord],
        parts: Dict[str, tuple[float, float]],
        relation: Any,
    ) -> Optional[float]:
        """
        验证上轮叙事预测是否被本轮实际状态变化证实。

        参数：
            narrative  : 上轮生成的 NarrativeRecord
            parts      : 当前 SelfBodyMap.parts {name: (prev, curr)}
            relation   : 对应的 Relation 对象（用于更新置信度）

        返回：
            1.0  = 预测被验证（effect 方向与预测一致）
            -1.0 = 预测被推翻
            0.0  = 无法判断（effect 无变化）
            None = narrative 为空
        """
        if narrative is None:
            return None

        effect = narrative.effect
        effect_pair = parts.get(effect)
        if effect_pair is None:
            return None

        effect_prev, effect_curr = effect_pair
        actual_delta = effect_curr - effect_prev

        # 预测的 effect 方向
        if narrative.cause_direction > 0:
            predicted_effect_dir = 1  # cause 上升 → effect 应该增加
        else:
            predicted_effect_dir = -1  # cause 下降 → effect 应该减少

        if abs(actual_delta) < 1e-6:
            return 0.0  # effect 没变化，无法验证

        if (actual_delta > 0 and predicted_effect_dir > 0) or \
           (actual_delta < 0 and predicted_effect_dir < 0):
            relation.verify()
            return 1.0
        else:
            relation.falsify()
            return -1.0

    @property
    def last(self) -> Optional[NarrativeRecord]:
        return self._last

    @property
    def history(self) -> List[NarrativeRecord]:
        return self._history
