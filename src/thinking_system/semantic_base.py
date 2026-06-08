"""
Semantic Base — 思考系统的语义底座

给维度名、行动名附上含义，让思考系统不再只操作裸数字。

这不是行为路由——不告诉她"该做什么"。
这是解读工具——让她知道"这些数字代表什么"，
从而能问出有意义的问题、做出有根据的推断。

使用方式：
    思考系统引用这里的数据来：
    - 生成可读的问题（不再是"这条规则可靠吗"而是"explore 减少好奇心的代价值得吗"）
    - 解读规则（知道 delta 方向的含义）
    - 发现规则与因果种子的矛盾（更有价值的问题）

子模块：
    semantic_tables.py — DIMENSION_SEMANTICS / ACTION_SEMANTICS / CAUSAL_SEEDS 常量表
"""

from .semantic_tables import (
    DIMENSION_SEMANTICS,
    ACTION_SEMANTICS,
    CAUSAL_SEEDS,
)
from typing import Dict, List, Any, Optional


def get_dim_meaning(dim: str) -> str:
    """查维度含义，找不到返回维度名本身。"""
    info = DIMENSION_SEMANTICS.get(dim)
    return info["meaning"] if info else dim


def get_dim_polarity(dim: str) -> str:
    """查维度极性。positive/negative/neutral，未知返回 neutral。"""
    info = DIMENSION_SEMANTICS.get(dim)
    return info["polarity"] if info else "neutral"


def get_action_essence(action: str) -> str:
    """查行动本质描述。"""
    info = ACTION_SEMANTICS.get(action)
    return info["essence"] if info else action


def interpret_delta(dim: str, delta: float) -> str:
    """
    把一个 delta 翻译成可读的描述。

    例如：interpret_delta("fatigue", 0.05) → "疲惫加重了一点（累积的消耗感）"
          interpret_delta("info_gap", -0.15) → "好奇心被满足了一些（还有多少没搞懂的东西）"
    """
    info = DIMENSION_SEMANTICS.get(dim)
    if not info:
        direction = "上升" if delta > 0 else "下降"
        return f"{dim}{direction}了{abs(delta):.2f}"

    meaning = info["meaning"]
    polarity = info["polarity"]

    if delta > 0:
        if polarity == "negative":
            tone = "加重了"
        elif polarity == "positive":
            tone = "增强了"
        else:
            tone = "上升了"
    else:
        if polarity == "negative":
            tone = "减轻了"
        elif polarity == "positive":
            tone = "减弱了"
        else:
            tone = "下降了"

    magnitude = "一点" if abs(delta) < 0.05 else ("不少" if abs(delta) > 0.15 else "一些")
    return f"{dim}{tone}{magnitude}（{meaning}）"


def find_causal_path(from_dim: str, to_dim: str) -> Optional[Dict]:
    """找两个维度之间的因果种子，找不到返回 None。"""
    for seed in CAUSAL_SEEDS:
        if seed["from"] == from_dim and seed["to"] == to_dim:
            return seed
        if seed["direction"] == "bidirectional":
            if seed["from"] == to_dim and seed["to"] == from_dim:
                return seed
    return None


def find_related_seeds(dim: str) -> List[Dict]:
    """找和某个维度相关的所有因果种子。"""
    result = []
    for seed in CAUSAL_SEEDS:
        if seed["from"] == dim or seed["to"] == dim:
            result.append(seed)
    return result


def check_rule_against_seeds(rule: dict) -> Optional[Dict[str, Any]]:
    """
    拿一条 wm_rule 和因果种子对照。

    返回：
        None — 没有可对照的种子
        {"status": "consistent", ...} — 规则和种子一致
        {"status": "contradicts", ...} — 规则和种子矛盾（值得追问）
        {"status": "novel", ...} — 规则发现了种子没有的关系（值得记住）
    """
    deltas = rule.get("expected_deltas")
    if not deltas or not isinstance(deltas, dict):
        return None

    # 从 trigger 提取 action
    trigger = ""
    predicts = rule.get("predicts")
    if isinstance(predicts, dict):
        trigger = str(predicts.get("trigger", ""))
    action = ""
    for a in ACTION_SEMANTICS:
        if a in trigger:
            action = a
            break

    if not action:
        return None

    # 对每个显著 delta，查因果种子
    for dim, delta_val in deltas.items():
        try:
            d = float(delta_val)
        except (TypeError, ValueError):
            continue
        if abs(d) < 0.01:
            continue

        seed = find_causal_path(action, dim)
        if seed:
            expected_inverse = seed["direction"] == "inverse"
            actual_inverse = d < 0
            if expected_inverse == actual_inverse:
                return {
                    "status": "consistent",
                    "rule_id": rule.get("id", "?"),
                    "seed": seed,
                    "dim": dim,
                    "delta": d,
                    "interpretation": f"{action}{'减少' if d < 0 else '增加'}了{dim}，"
                                      f"和预期一致（{seed['reason']}）",
                }
            else:
                return {
                    "status": "contradicts",
                    "rule_id": rule.get("id", "?"),
                    "seed": seed,
                    "dim": dim,
                    "delta": d,
                    "interpretation": f"{action}本应{'减少' if expected_inverse else '增加'}{dim}，"
                                      f"但实际{'增加' if d > 0 else '减少'}了——为什么？",
                }

        # 没有种子 → 新发现
        if abs(d) > 0.03:
            return {
                "status": "novel",
                "rule_id": rule.get("id", "?"),
                "dim": dim,
                "delta": d,
                "action": action,
                "interpretation": f"发现{action}会{'增加' if d > 0 else '减少'}{dim}"
                                  f"（{get_dim_meaning(dim)}），这是新的",
            }

    return None
