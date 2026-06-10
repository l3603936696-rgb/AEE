"""construction_learning — 从输入中学习构式

职责（一句话）：从解析结果中提取已匹配或新发现的构式，
以打折效率（听到 ≠ 自己说）喂给 ConstructionLearner。
"""
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

# 听到别人说的构式，效率是自己说的这个比例
_HEARD_DISCOUNT = 0.3
# 完全听不懂时不学（理解度门槛，连续权重，低于此视为无效输入）
_MIN_COMPREHENSION = 0.2
# 构式前后缀不超过此长度才视为简单构式
_MAX_AFFIX_LEN = 6


def learn_constructions_from_input(
    text: str,
    entity: Any,
    parse_result: Dict[str, Any],
) -> None:
    """
    从输入中提取构式喂给 ConstructionLearner。

    两种来源：
        1. 已知构式匹配：输入匹配了她学过的构式 → 强化 + 记录实例
        2. 新构式发现：已知词周围的固定结构 → 记录为新实例

    权重低于自身表达（_HEARD_DISCOUNT），因为听到的话没经过消力验证。
    """
    cxg = getattr(entity, "_cxg_learner", None)
    if cxg is None:
        return

    comprehension = float(parse_result.get("comprehension", 0.0))
    # 连续权重：理解度越低，学习效率越低；低于门槛时权重趋近 0
    learn_weight = max(0.0, (comprehension - _MIN_COMPREHENSION) / (1.0 - _MIN_COMPREHENSION))
    if learn_weight < 1e-6:
        return

    drive_state = entity.to_state_snapshot() if hasattr(entity, "to_state_snapshot") else {}
    effective_efficiency = comprehension * _HEARD_DISCOUNT * learn_weight

    # ---- 1. 已匹配的构式：强化 + 记录实例 ----
    cx_match = parse_result.get("construction_match", "")
    cx_fillers = parse_result.get("construction_fillers", [])
    if cx_match and cx_fillers:
        # cx_match 使用 {0}/{1} 格式，record_instance 需要 {anchor}/{anchor2}
        template = cx_match.replace("{0}", "{anchor}", 1).replace("{1}", "{anchor2}", 1)
        try:
            cxg.record_instance(
                template_str=template,
                anchor=cx_fillers[0],
                drive_state=drive_state,
                efficiency=effective_efficiency,
                tick=getattr(entity, "tick", 0),
                second_anchor=cx_fillers[1] if len(cx_fillers) > 1 else "",
            )
        except Exception as e:
            logger.debug(f"[CxLearning] record matched cx failed: {e}")

    # ---- 2. 新构式发现：已知词在文本中的上下文 → 抽取结构 ----
    recognized = parse_result.get("recognized_words", [])
    if not recognized:
        return

    for word, score in recognized:
        if len(word) < 1 or score < 0.5:
            continue
        idx = text.find(word)
        if idx < 0:
            continue

        prefix = text[:idx]
        suffix = text[idx + len(word):]

        # 前后缀太长 → 不是简单构式
        if len(prefix) > _MAX_AFFIX_LEN or len(suffix) > _MAX_AFFIX_LEN:
            continue
        # 纯词（无前后缀）不是构式
        if not prefix.strip() and not suffix.strip():
            continue

        schema = f"{prefix}{{anchor}}{suffix}"

        # 已有构式跳过（上面已处理）
        if schema in getattr(cxg, "_constructions", {}):
            continue

        try:
            cxg.record_instance(
                template_str=schema,
                anchor=word,
                drive_state=drive_state,
                efficiency=effective_efficiency,
                tick=getattr(entity, "tick", 0),
            )
        except Exception as e:
            logger.debug(f"[CxLearning] record new cx failed: {e}")
