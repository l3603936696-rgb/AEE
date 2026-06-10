"""
Thinking System Questions — question generation and rendering.

Extracted from thinking_system_helpers.py.
"""

from typing import Any, Dict, List, Optional

from .semantic_base import check_rule_against_seeds, interpret_delta, get_dim_meaning, get_action_essence
from .thinking_system_helpers import _conf, _rid, _rule_dimensions


# =============================================================================
# Question Generation
# =============================================================================

_ANSWERABILITY_BY_TRIGGER = {"input": 1.0, "action": 0.6}
_ANSWERABILITY_DEFAULT = 0.8


def _answerability_weight(rule: dict) -> float:
    """Continuous weight [0.6, 1.0] by rule trigger prefix."""
    predicts = rule.get("predicts")
    trigger = ""
    if isinstance(predicts, dict):
        trigger = str(predicts.get("trigger", ""))
    prefix = trigger.split("_", 1)[0]
    return _ANSWERABILITY_BY_TRIGGER.get(prefix, _ANSWERABILITY_DEFAULT)


def _build_question(rule: dict, related_rules: List[dict]) -> Dict[str, Any]:
    """
    Generate structured question from rule features.

    Returns dict with: type, rule_id, dims, confidence, expected_deltas,
    seed_check, has_boundary, answerability, priority.
    """
    c = _conf(rule)
    rule_dims = list(_rule_dimensions(rule))
    deltas = rule.get("expected_deltas", {})
    delta_dims = list(deltas.keys()) if isinstance(deltas, dict) else []

    try:
        seed_check = check_rule_against_seeds(rule)
    except Exception:
        seed_check = None

    if seed_check and seed_check["status"] == "contradicts":
        q_type = "contradiction"
        base_priority = 0.9
    elif seed_check and seed_check["status"] == "novel":
        q_type = "novel"
        base_priority = 0.7
    elif c < 0.4:
        q_type = "low_confidence"
        base_priority = max(0.7, 1.0 - c)
    elif c >= 0.75:
        q_type = "high_confidence"
        base_priority = 0.6 + c * 0.1
    else:
        q_type = "causal" if len(delta_dims) > 1 else "low_confidence"
        base_priority = 0.4

    has_boundary = bool(related_rules) and c >= 0.5
    if has_boundary:
        base_priority *= 1.1

    answerability = _answerability_weight(rule)
    base_priority *= answerability

    return {
        "type": q_type,
        "rule_id": _rid(rule),
        "dims": delta_dims or rule_dims[:5],
        "confidence": round(c, 3),
        "expected_deltas": {k: round(float(v), 4) for k, v in deltas.items()}
                           if isinstance(deltas, dict) else {},
        "seed_check": seed_check,
        "has_boundary": has_boundary,
        "answerability": round(answerability, 3),
        "priority": round(min(1.0, base_priority), 3),
    }


def _build_tool_capability_question(gap_signal: dict) -> Optional[dict]:
    """
    Generate tool_capability type question from capability gap signal.

    v11.6: XIA reflects on missing tool capabilities.
    priority = gap_intensity × 0.8 + 0.1
    """
    intent = gap_signal.get("intent", "")
    gap_intensity = float(gap_signal.get("gap_intensity", 0))
    unmatched = gap_signal.get("unmatched_aspects", [])
    capability_types = gap_signal.get("capability_types", [])

    if gap_intensity < 0.3 or not intent:
        return None

    cap_to_action: dict = {
        "web_access": "探索网上内容",
        "information_search": "搜索信息",
        "code_execution": "执行代码",
        "file_manipulation": "操作文件",
        "network_access": "访问网络",
        "api_call": "调用接口",
        "debugging": "调试问题",
    }
    action_text = cap_to_action.get(capability_types[0], intent) if capability_types else intent
    priority = min(1.0, gap_intensity * 0.8 + 0.1)

    return {
        "type": "tool_capability",
        "intent": intent,
        "action_text": action_text,
        "gap_intensity": gap_intensity,
        "unmatched_aspects": unmatched,
        "capability_types": capability_types,
        "dims": capability_types[:3],
        "confidence": gap_signal.get("confidence", 0.5),
        "expected_deltas": {},
        "seed_check": None,
        "has_boundary": True,
        "priority": round(priority, 3),
    }


def render_question(q: Dict[str, Any]) -> str:
    """Render structured question to text (for display only)."""
    q_type = q.get("type", "")
    seed_check = q.get("seed_check")
    dims = q.get("dims", [])

    if q_type == "contradiction" and seed_check:
        return seed_check.get("interpretation", "有矛盾")
    if q_type == "novel" and seed_check:
        return f"{seed_check.get('interpretation', '新发现')}——可靠吗？"

    deltas = q.get("expected_deltas", {})
    if deltas and interpret_delta:
        parts = [interpret_delta(dim, d) for dim, d in deltas.items()]
        delta_text = "；".join(parts[:3])
    elif dims and get_dim_meaning:
        delta_text = "、".join(get_dim_meaning(d) for d in dims[:3])
    else:
        delta_text = "、".join(dims[:3]) if dims else "?"

    if q_type == "low_confidence":
        return f"这个判断（{delta_text}）可靠吗？"
    elif q_type == "high_confidence":
        return f"一直这样（{delta_text}），现在还成立吗？"
    elif q_type == "causal":
        return f"这些变化有因果关系吗？{delta_text}"
    elif q_type == "tool_capability":
        action_text = q.get("action_text", q.get("intent", "?"))
        missing = ", ".join(q.get("unmatched_aspects", [])[:2])
        if missing:
            return f"我想{action_text}，但我好像缺少{missing}的能力。我有办法做到吗？"
        return f"我想{action_text}，但我有这个能力吗？"

    return f"关于 {delta_text} 的不确定"
