"""
Insights Schema — 数据结构与字段提取规则

供 insights_api.py 调用。
"""

from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class Insight:
    """显性知识条目。"""
    id: str
    type: str           # "user_preference" | "situation_pattern"
    content: str        # 可读描述
    situation: str      # 触发情境关键词
    wm_rule_ref: str   # 关联的 wm_rule ID
    confidence: float
    status: str         # "active" | "decayed"
    created_at: str


def _infer_type(rule: Dict[str, Any]) -> str:
    """
    从规则字段自动判定 insight type。

    规则：
        - context 含 "correction" / "用户纠正" / "纠正" → user_preference
        - context 含 "偏好" / "preference" → user_preference
        - context 含 "pattern" / "情境" / "模式" → situation_pattern
        - 否则默认 user_preference
    """
    context = rule.get("context", "").lower()
    content = rule.get("content", "").lower()

    preference_signals = {"correction", "纠正", "preference", "偏好", "用户", "不喜欢", "喜欢", "不要"}
    pattern_signals = {"pattern", "情境", "模式", "反复", "重复"}

    for sig in pattern_signals:
        if sig in context or sig in content:
            return "situation_pattern"

    for sig in preference_signals:
        if sig in context or sig in content:
            return "user_preference"

    return "user_preference"


def _extract_situation(rule: Dict[str, Any]) -> str:
    """
    从规则 trigger 字段提取触发情境关键词。

    格式：action_{type}_in_{context_label}
    示例：action_seek_in_high_energy → "high_energy"
    """
    trigger = rule.get("predicts", {}).get("trigger", "")
    if not trigger:
        return rule.get("context", "").lower()

    if "_in_" in trigger:
        return trigger.split("_in_", 1)[-1]
    return trigger.lower()


def _to_dict(rule: Any) -> Dict[str, Any]:
    """将 Rule 对象或字典统一转换为 dict。"""
    if isinstance(rule, dict):
        return rule
    if hasattr(rule, "to_dict"):
        return rule.to_dict()
    return {}
