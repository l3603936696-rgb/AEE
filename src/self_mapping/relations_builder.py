"""
RelationsBuilder — 从 wm_rules 自动归纳 XIA 内部因果关系图

核心函数：
    build_relations_from_wm(wm_rules) → List[Relation]

这不是设计者预设的因果图，而是从 XIA 自己积累的 wm_rules 里
用模式匹配自动抽取的。

算法：
    1. 扫描每条 wm_rule 的 content / context / predicts 字段
    2. 检测其中是否同时包含两个已知内部部位名
    3. 若包含，建立 (cause → effect) 关联，初始 meta_confidence = wm_rule.confidence
"""

from typing import Any, List, Optional, Tuple

from .self_body_map import Relation, INTERNAL_PARTS


# ============================================================================
# 关系方向推断关键词
# ============================================================================

# 关键词 → 方向（1=正相关，-1=负相关，0=未知）
_CAUSE_KEYWORDS = {
    # 原因侧关键词（表示某状态导致另一状态变化）
    "低": -1,       # "energy低 → ..." → energy 低作为原因
    "高": 1,        # "energy高 → ..." → energy 高作为原因
    "上升": 1,      # "loneliness上升 → ..."
    "下降": -1,     # "fatigue下降 → ..."
    "增加": 1,      # "info_gap增加 → ..."
    "减少": -1,     # "approach_drive减少 → ..."
}

_EFFECT_KEYWORDS = {
    "导致": 1,
    "使": 1,
    "促使": 1,
    "驱动": 1,
    "引发": 1,
    "上升": 1,
    "增加": 1,
    "下降": -1,
    "减少": -1,
    "抑制": -1,
    "降低": -1,
}


# ============================================================================
# 公共接口
# ============================================================================

def build_relations_from_wm(
    wm_rules: List[Any],
    current_tick: int = 0,
) -> List[Relation]:
    """
    从 wm_rules 列表归纳 XIA 内部因果关联。

    参数：
        wm_rules       : 世界模型规律列表（Rule dict 或 Rule 对象）
        current_tick   : 当前 tick（用于 Relation.created_at）

    返回：
        List[Relation]：去重后的内部因果关联列表
    """
    relations_map: dict[Tuple[str, str], Relation] = {}

    for rule in _safe_rules(wm_rules):
        if rule.get("status") not in ("active", "pending"):
            continue

        cause, effect = _extract_relation_pair(rule)
        if cause is None or effect is None:
            continue
        if cause == effect:
            continue

        key = (cause, effect)
        if key in relations_map:
            # 去重：用 confidence 均值更新
            existing = relations_map[key]
            existing.meta_confidence = (
                existing.meta_confidence * 0.8
                + float(rule.get("confidence", 0.5)) * 0.2
            )
        else:
            relations_map[key] = Relation(
                cause=cause,
                effect=effect,
                description=str(rule.get("content", "")),
                meta_confidence=float(rule.get("confidence", 0.5)),
                created_at=current_tick,
            )

    return list(relations_map.values())


# ============================================================================
# 私有函数
# ============================================================================

def _extract_relation_pair(rule: dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """
    从单条 wm_rule 中提取 XIA 内部部位之间的因果关系对。

    检查 content / context / predicts 字段中是否同时包含两个已知内部部位名。
    若找到，返回 (cause, effect)；否则返回 (None, None)。

    方向推断（次要）：优先返回"变化型"部位作为 cause。
    例如："loneliness 上升" → loneliness 作为 cause
          "somatic_tone 下降" → somatic_tone 作为 cause
    """
    content = str(rule.get("content", "")).lower()
    context = str(rule.get("context", "")).lower()
    combined = content + " " + context

    # 从 Predicts 字段提取
    predicts = rule.get("predicts", {})
    trigger = ""
    expect = ""
    if isinstance(predicts, dict):
        trigger = str(predicts.get("trigger", "")).lower()
        expect = str(predicts.get("expect", "")).lower()

    all_text = combined + " " + trigger + " " + expect

    # 找所有出现在文本中的部位
    found: list[tuple[str, str]] = []  # (part_name, position_hint)
    for part in INTERNAL_PARTS:
        if part in all_text:
            # 用关键词判断这是 cause 还是 effect
            # 搜索部位附近的关键词
            pos = all_text.find(part)
            window = all_text[max(0, pos - 5):pos + len(part) + 5]
            direction = _get_local_direction(window)
            found.append((part, direction))

    # 选择两个不同部位
    if len(found) >= 2:
        # 优先选择有明确方向提示的作为 cause
        found.sort(key=lambda x: (0 if x[1] != 0 else 1, abs(x[1])), reverse=True)
        cause = found[0][0]
        # effect：选择与 cause 不同的部位，优先选有方向提示的
        candidates = [(p, d) for p, d in found if p != cause]
        if candidates:
            candidates.sort(key=lambda x: (0 if x[1] != 0 else 1, abs(x[1])), reverse=True)
            effect = candidates[0][0]
            return (cause, effect)

    return (None, None)


def _get_local_direction(window: str) -> int:
    """从局部文本窗口判断方向（正/负/未知）。"""
    for kw, direction in _CAUSE_KEYWORDS.items():
        if kw in window:
            return direction
    return 0


def _safe_rules(rules: List[Any]) -> List[dict[str, Any]]:
    result: List[dict[str, Any]] = []
    for r in rules:
        if isinstance(r, dict):
            result.append(r)
        elif hasattr(r, "to_dict"):
            result.append(r.to_dict())
        elif hasattr(r, "content"):
            # dataclass Rule
            d = {
                "content": getattr(r, "content", ""),
                "context": getattr(r, "context", ""),
                "status": getattr(r, "status", "active"),
                "confidence": getattr(r, "confidence", 0.5),
                "predicts": {},
            }
            if hasattr(r, "predicts") and hasattr(r.predicts, "trigger"):
                d["predicts"] = {
                    "trigger": r.predicts.trigger,
                    "expect": r.predicts.expect,
                }
            result.append(d)
    return result
