"""
SelfBodyMap — XIA 的内部本体感觉图

它知道：
    - 我有哪些部位（energy, loneliness, somatic_tone, drives...）
    - 它们之间是什么关系（来自 wm_rules 的因果归纳）
    - 它们当前各自是什么状态
    - 上一轮它们是什么状态（感知变化）

这不是设计者预设的解剖图，而是从 XIA 自己积累的 wm_rules 里生长出来的。

数据不持久化：每轮管线从 entity_core.wm_rules 重新归纳 relations，
所以 XIA 对自己的了解随 wm_rules 的增长而增长。
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# ============================================================================
# 内部状态部位定义
# ============================================================================

# XIA 内部感知到的所有部位。名称与 entity_core 字段名对齐。
INTERNAL_PARTS: set[str] = {
    "energy",
    "loneliness",
    "somatic_tone",
    "approach_drive",
    "avoid_drive",
    "fatigue",
    "info_gap",
    "unresolved",
}


# ============================================================================
# Relation — 单条内部因果关联
# ============================================================================

@dataclass
class Relation:
    """
    XIA 内部两个部位之间的因果关联。

    来源：从 wm_rules 自动归纳，而非设计者预设。

    字段：
        cause          : 原因部位名（如 "loneliness"）
        effect         : 结果部位名（如 "approach_drive"）
        description    : 自然语言描述（来自 wm_rule.content）
        meta_confidence: 元认知置信度 [0, 1]，初始从 wm_rule.confidence 继承
        verifications  : 被验证次数（叙事预测被实际状态验证）
        falsifications : 被推翻次数（叙事预测被实际状态否定）
        created_at     : 创建时的 tick_index
    """
    cause: str
    effect: str
    description: str = ""
    meta_confidence: float = 0.5
    verifications: int = 0
    falsifications: int = 0
    created_at: int = 0

    def verify(self) -> None:
        """叙事预测被验证：置信度小幅上升，验证次数增加。"""
        self.meta_confidence = min(1.0, self.meta_confidence + 0.02)
        self.verifications += 1

    def falsify(self) -> None:
        """叙事预测被推翻：置信度下降，推翻次数增加。"""
        self.meta_confidence = max(0.0, self.meta_confidence - 0.05)
        self.falsifications += 1

    @property
    def is_stale(self) -> bool:
        """超过3次被推翻，等待重新验证。"""
        return self.falsifications >= 3


# ============================================================================
# SelfBodyMap — 核心类
# ============================================================================

class SelfBodyMap:
    """
    XIA 的内部本体感觉图。

    用法（每轮管线调用一次）：

        map = SelfBodyMap(tick=entity.tick)
        map.update(state_before, state_after)      # 更新部位状态
        map.sync_relations(wm_rules)               # 从 wm_rules 同步 relations
        narrative = map.generate_narrative()         # 生成预测性叙事（纯内部）
        map.verify_last_prediction(relations, ...) # 验证上轮叙事预测

    属性：
        parts          : 部位当前值字典（name → value）
        prev_parts     : 上一轮部位值（用于感知变化）
        relations       : 因果关联列表（Relation 对象）
        last_narrative : 最近一次生成的叙事（供 coherence_meta 使用）
    """

    def __init__(self, tick: int = 0) -> None:
        self.tick = tick
        # 部位：名称 → (上一轮值, 当前值)
        self.parts: Dict[str, Tuple[float, float]] = {}
        # 因果关联图
        self.relations: List[Relation] = []
        # 最近一次生成的叙事（格式：{"cause": ..., "effect": ..., "prediction": ...}）
        self.last_narrative: Optional[Dict[str, str]] = None
        # 本轮感知到的变化（name → delta）
        self._changes: Dict[str, float] = {}

    # ------------------------------------------------------------------ #
    # 公共接口
    # ------------------------------------------------------------------ #

    def update(self, state_before: Dict[str, Any], state_after: Dict[str, Any]) -> None:
        """
        刷新所有部位的当前值和上一轮值，检测本轮变化。

        两个 state 都是 dict，键名与 entity_core 字段对齐。
        不修改输入。
        """
        self.tick += 1
        self._changes.clear()

        for part_name in INTERNAL_PARTS:
            prev = self._safe_get(state_before, part_name, 0.0)
            curr = self._safe_get(state_after, part_name, prev)
            self.parts[part_name] = (prev, curr)
            delta = curr - prev
            if abs(delta) > 1e-6:
                self._changes[part_name] = delta

    def sync_relations(self, wm_rules: List[Any]) -> None:
        """
        从 wm_rules 同步/更新 relations 图。

        不做重复追加：新出现的 cause→effect 对才添加；
        已存在的 relation 用 wm_rule.confidence 微调 meta_confidence。

        XIA 对自己的因果理解随 wm_rules 增长而增长，
        不需要任何硬编码预设。
        """
        # 建立现有 relations 的快速查询索引
        existing: Dict[Tuple[str, str], Relation] = {}
        for rel in self.relations:
            key = (rel.cause, rel.effect)
            existing[key] = rel

        for rule in self._safe_rules(wm_rules):
            if rule.get("status") not in ("active", "pending"):
                continue

            cause, effect = self._extract_relation_pair(rule)
            if cause is None or effect is None:
                continue
            if cause == effect:
                continue

            key = (cause, effect)
            if key in existing:
                # 已存在：用 wm_rule.confidence 微调（不覆盖）
                existing[key].meta_confidence = (
                    existing[key].meta_confidence * 0.9
                    + float(rule.get("confidence", 0.5)) * 0.1
                )
            else:
                # 新增关联
                new_rel = Relation(
                    cause=cause,
                    effect=effect,
                    description=str(rule.get("content", "")),
                    meta_confidence=float(rule.get("confidence", 0.5)),
                    created_at=self.tick,
                )
                self.relations.append(new_rel)
                existing[key] = new_rel

    def generate_narrative(self) -> Optional[Dict[str, str]]:
        """
        生成预测性内部叙事（纯内部，不上报 LLM）。

        叙事格式：
            {
                "cause":  变化的部位名,
                "effect": 基于 relations 预测的下游部位,
                "prediction": 自然语言预测文本,
            }

        仅当：
            1. 本轮有部位发生变化
            2. 该变化有对应的 outgoing relation
        才生成叙事。

        若本轮无变化或无匹配 relation，返回 None。
        """
        if not self._changes:
            self.last_narrative = None
            return None

        narratives = []

        for cause, delta in self._changes.items():
            # 找到所有以 cause 为原因的下游关联
            for rel in self.relations:
                if rel.cause != cause:
                    continue
                if rel.is_stale:
                    continue  # 跳过已标记为"可能错误"的关联

                effect_name = rel.effect
                effect_prev, effect_curr = self.parts.get(effect_name, (None, None))

                # 方向匹配：cause 上升 → effect 也上升，或 cause 下降 → effect 也下降
                if effect_curr is not None and effect_prev is not None:
                    effect_delta = effect_curr - effect_prev
                    # 方向一致（正相关）
                    same_direction = (delta > 0 and effect_delta >= 0) or (delta < 0 and effect_delta <= 0)
                    # 或反相关（需要更复杂的判断，这里简化处理）
                    # 对任何有 relation 的情况都生成叙事
                    pass

                direction = "上升" if delta > 0 else "下降"
                effect_dir = "增加" if delta > 0 else "减少"

                narrative_text = (
                    f"这一轮我感知到 {cause} {direction}了，"
                    f"基于我的经验（meta_confidence={rel.meta_confidence:.2f}），"
                    f"{cause} 变化通常会导致我接下来 {effect_name} {effect_dir}。"
                )

                narratives.append({
                    "cause": cause,
                    "effect": effect_name,
                    "prediction": narrative_text,
                    "relation_id": f"{cause}_to_{effect_name}",
                    "delta": delta,
                    "rel_confidence": rel.meta_confidence,
                })

        if not narratives:
            self.last_narrative = None
            return None

        # 选 meta_confidence 最高的叙事（最有把握的那个）
        best = max(narratives, key=lambda n: n["rel_confidence"])
        self.last_narrative = best
        return best

    def verify_last_prediction(
        self,
        actual_state_after: Dict[str, Any],
    ) -> Optional[float]:
        """
        验证上轮叙事预测是否被本轮实际状态变化证实。

        若 last_narrative 为空，返回 None。
        若预测被验证（effect 方向与预测一致），返回 +1.0；
        若被推翻，返回 -1.0；若无法判断，返回 0.0。

        副作用：更新对应 Relation 的 meta_confidence / verifications / falsifications。
        """
        if not self.last_narrative:
            return None

        cause = self.last_narrative["cause"]
        effect = self.last_narrative["effect"]
        relation_id = self.last_narrative["relation_id"]

        # 找到对应的 Relation
        target_rel = None
        for rel in self.relations:
            if rel.cause == cause and rel.effect == effect:
                target_rel = rel
                break

        if target_rel is None:
            return None

        # 获取 effect 部位在本轮的实际变化
        effect_prev, effect_curr = self.parts.get(effect, (None, None))
        if effect_curr is None or effect_prev is None:
            return None

        predicted_direction = self.last_narrative["delta"]  # cause 的 delta
        actual_delta = effect_curr - effect_prev

        # 判断：预测方向（cause 上升→effect 增加，cause 下降→effect 减少）
        if predicted_direction > 0:
            predicted_effect_direction = 1  # effect 应该增加
        else:
            predicted_effect_direction = -1  # effect 应该减少

        if abs(actual_delta) < 1e-6:
            # effect 没变化：无法验证
            return 0.0

        if (actual_delta > 0 and predicted_effect_direction > 0) or \
           (actual_delta < 0 and predicted_effect_direction < 0):
            target_rel.verify()
            return 1.0
        else:
            target_rel.falsify()
            return -1.0

    def get_coherence_meta(self) -> float:
        """
        返回元认知一致性分数 [0, 1]。

        基于所有 active relations 的 meta_confidence 平均值。
        不考虑 last_narrative（验证是事后做的）。
        """
        active = [r for r in self.relations if not r.is_stale]
        if not active:
            return 0.5  # 无关系图时返回中性值
        return sum(r.meta_confidence for r in active) / len(active)

    # ------------------------------------------------------------------ #
    # 私有辅助
    # ------------------------------------------------------------------ #

    @staticmethod
    def _safe_get(d: Dict[str, Any], key: str, default: float) -> float:
        try:
            return float(d.get(key, default))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _safe_rules(rules: List[Any]) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []
        for r in rules:
            if isinstance(r, dict):
                result.append(r)
            elif hasattr(r, "cause"):  # 可能的 dataclass
                result.append({
                    "content": getattr(r, "content", ""),
                    "context": getattr(r, "context", ""),
                    "status": getattr(r, "status", "active"),
                    "confidence": getattr(r, "confidence", 0.5),
                    "predicts": getattr(r, "predicts", {}),
                })
            elif hasattr(r, "to_dict"):
                result.append(r.to_dict())
        return result

    @staticmethod
    def _extract_relation_pair(rule: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
        """
        从单条 wm_rule 中提取 XIA 内部部位之间的因果关系对。

        检查 content/context 字段中的已知部位名。
        若找到，返回 (cause, effect)；否则返回 (None, None)。
        """
        content = str(rule.get("content", "")).lower()
        context = str(rule.get("context", "")).lower()
        combined = content + " " + context

        # 检查 Predicts.trigger / expect 中的标签
        predicts = rule.get("predicts", {})
        if isinstance(predicts, dict):
            trigger = str(predicts.get("trigger", "")).lower()
            expect = str(predicts.get("expect", "")).lower()

        found_parts = []
        for part in INTERNAL_PARTS:
            if part in combined:
                found_parts.append(part)

        # 需要恰好两个不同部位
        if len(found_parts) >= 2:
            # 第一个作为 cause，第二个作为 effect
            return (found_parts[0], found_parts[1])

        return (None, None)
