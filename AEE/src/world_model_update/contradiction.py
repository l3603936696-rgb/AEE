"""
Contradiction Detection — 规律矛盾检测

扫描规律库，找出结构性矛盾对：
    同域 + expected_deltas 中至少一个维度符号相反 + 双方置信度 > 阈值

纯函数，不写文件，不修改规律。
矛盾强度 = min(conf_a, conf_b) × opposition_score。

O(N²) 但 N ≤ 200 且每次比较仅为 dict 查找 + 符号检查，总耗时 <1ms。
"""

from __future__ import annotations

from typing import Any, Dict, List


# ============================================================================
# 辅助函数
# ============================================================================

def _get_field(rule: Any, field: str, default: Any = None) -> Any:
    if isinstance(rule, dict):
        return rule.get(field, default)
    return getattr(rule, field, default)


def _get_expected_deltas(rule: Any) -> Dict[str, float]:
    d = _get_field(rule, "expected_deltas", {})
    return d if isinstance(d, dict) else {}


def _domains_overlap(a: str, b: str) -> bool:
    """
    判断两个 domain 是否重叠。

    - "general" 与任何域重叠
    - 相同域重叠
    - 层级匹配："social" 与 "social.intimate" 重叠
    """
    if a == "general" or b == "general":
        return True
    if a == b:
        return True
    return a.startswith(b + ".") or b.startswith(a + ".")


def _compute_opposition(deltas_a: Dict[str, float], deltas_b: Dict[str, float]):
    """
    计算两条规律 expected_deltas 的对立程度。

    返回 (opposition_score, opposing_dimensions):
        opposition_score: 对立维度的平均对立强度 (0 ~ 1)
        opposing_dimensions: 符号相反的维度名列表
    """
    opposing = []
    total_opposition = 0.0

    for dim in deltas_a:
        if dim not in deltas_b:
            continue
        va = deltas_a[dim]
        vb = deltas_b[dim]
        # 符号相反（两边都非零）
        if va * vb < 0:
            opposing.append(dim)
            total_opposition += min(abs(va), abs(vb))

    if not opposing:
        return 0.0, []

    score = total_opposition / len(opposing)
    return score, opposing


# ============================================================================
# 主入口
# ============================================================================

def detect_contradictions(
    rules: List[Any],
    min_confidence: float = 0.3,
) -> List[Dict[str, Any]]:
    """
    扫描规律库，检测结构性矛盾对。

    参数：
        rules: 规律列表（Rule 对象或 dict）
        min_confidence: 双方置信度至少达到此值才检测

    返回：
        List[dict]，每个元素：
        {
            "rule_a": str,        # 规律 A 的 id
            "rule_b": str,        # 规律 B 的 id
            "strength": float,    # 矛盾强度 = min(conf) × opposition
            "opposing_dimensions": list,  # 对立的维度名列表
            "domain": str,        # 两者共享的域（取更具体的一方）
        }
    """
    # 预过滤：只保留有 expected_deltas 且置信度足够的规律
    candidates = []
    for r in rules:
        conf = float(_get_field(r, "confidence", 0.0))
        if conf < min_confidence:
            continue
        deltas = _get_expected_deltas(r)
        if not deltas:
            continue
        candidates.append(r)

    pairs: List[Dict[str, Any]] = []

    for i in range(len(candidates)):
        a = candidates[i]
        domain_a = str(_get_field(a, "domain", "general"))
        deltas_a = _get_expected_deltas(a)
        conf_a = float(_get_field(a, "confidence", 0.0))

        for j in range(i + 1, len(candidates)):
            b = candidates[j]
            domain_b = str(_get_field(b, "domain", "general"))

            if not _domains_overlap(domain_a, domain_b):
                continue

            deltas_b = _get_expected_deltas(b)
            conf_b = float(_get_field(b, "confidence", 0.0))

            score, opposing = _compute_opposition(deltas_a, deltas_b)
            if score <= 0:
                continue

            strength = min(conf_a, conf_b) * score

            # 取更具体的 domain
            domain = domain_a if len(domain_a) >= len(domain_b) else domain_b

            pairs.append({
                "rule_a": str(_get_field(a, "id", "")),
                "rule_b": str(_get_field(b, "id", "")),
                "strength": round(strength, 4),
                "opposing_dimensions": opposing,
                "domain": domain,
            })

    return pairs
