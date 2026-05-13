"""
Verification Module (验证模块)

使用贝叶斯学习率，对 pending 状态的规律进行验证，更新其置信度。

核心公式：
    effective_delta = base_delta × (1 / sqrt(source_experience_count))
    confidence += effective_delta（验证成功）
    confidence -= effective_delta（验证失败）
    clamp 范围：[confidence_floor, confidence_ceiling]
    单次最大变化量：绝对值不超过 verification_max_delta

触发条件：
    - pending 规律 confidence >= pending_threshold 时升为 active
    - active 规律 confidence < low_confidence_threshold 时降为 pending
    - confidence <= confidence_floor 时标记为 decayed
"""

import time
import math
from typing import Any, Dict, List

from .defaults import get_param, get_raw_value
from .rules import Rule


# ============================================================================
# 辅助函数
# ============================================================================

def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _extract_state(state: Any) -> Dict[str, float]:
    """安全提取状态向量"""
    if not isinstance(state, dict):
        return {}
    return {k: _safe_float(v) for k, v in state.items()}


def _state_delta(post: Dict[str, float], pre: Dict[str, float]) -> Dict[str, float]:
    """计算状态差分"""
    all_keys = set(pre.keys()) | set(post.keys())
    return {k: post.get(k, 0.0) - pre.get(k, 0.0) for k in all_keys}


def _safe_rules(items: Any) -> List[Rule]:
    """将任意规律格式安全化"""
    if not items:
        return []
    result: List[Rule] = []
    for r in items:
        if isinstance(r, Rule):
            result.append(r)
        elif isinstance(r, dict):
            result.append(Rule.from_dict(r))
    return result


def _safe_snap(snap: Any) -> tuple[Dict[str, float], Dict[str, float]]:
    """安全提取快照的前后状态"""
    if isinstance(snap, dict):
        snap_pre = snap.get("pre_state", {})
        snap_post = snap.get("post_state", {})
    else:
        snap_pre = getattr(snap, "pre_state", {})
        snap_post = getattr(snap, "post_state", {})
    return _extract_state(snap_pre), _extract_state(snap_post)


# ============================================================================
# 核心逻辑
# ============================================================================

def _compute_bayesian_delta(experience_count: int, base_delta: float) -> float:
    """
    贝叶斯学习率：
        effective_delta = base_delta × (1 / sqrt(source_experience_count))

    经验越多，单次更新幅度越小。
    """
    try:
        return base_delta * (1.0 / math.sqrt(max(1, experience_count)))
    except Exception:
        return base_delta


def _verify_single_rule(
    rule: Rule,
    snap_pre: Dict[str, float],
    snap_post: Dict[str, float],
    base_delta: float,
    max_delta: float,
) -> tuple[bool, float]:
    """
    对单条规律执行验证。

    根据规律的 predicts.expect 解析预期状态变化，与实际快照对比。

    返回 (verified: bool, delta: float)
    """
    try:
        expect = rule.predicts.expect
        if not expect:
            return False, 0.0

        # 解析 expect 格式："{field}_{direction}"
        parts = expect.rsplit("_", 1)
        if len(parts) != 2:
            return False, 0.0
        field, direction = parts

        delta_val = snap_post.get(field, 0.0) - snap_pre.get(field, 0.0)

        if direction == "increase":
            success = delta_val > 0.005
        elif direction == "decrease":
            success = delta_val < -0.005
        else:  # stable
            success = abs(delta_val) < 0.005

        delta = _compute_bayesian_delta(rule.source_experience_count, base_delta)
        delta = min(abs(delta), max_delta)  # 限制单次最大变化量绝对值
        delta = delta if success else -delta

        return success, delta

    except Exception:
        return False, 0.0


# ============================================================================
# 主入口：verify_pending
# ============================================================================

def verify_pending(
    rules: List[Any],
    pending: List[Any],
    snap: Any,
    param_snapshot: Any,
) -> List[Rule]:
    """
    验证模块主入口。

    参数：
        rules          : 当前全部规律列表（active + pending）
        pending        : 待验证的 pending 规律列表
        snap           : 最新经验快照（Snap 或 dict）
        param_snapshot : 参数只读快照（来自 parameter_system）

    返回：
        List[Rule] — 更新后的规律列表

    约束：
        - 纯函数，不写文件，不写数据库
        - 仅修改 confidence / status / last_verified_at / source_experience_count
    """
    try:
        # ---- 参数读取（严禁 default=None）----
        base_delta = get_raw_value(
            param_snapshot,
            "world_model.verification_base_delta",
            0.08,
        )
        max_delta = get_raw_value(
            param_snapshot,
            "world_model.verification_max_delta",
            0.15,
        )
        pending_threshold = get_raw_value(
            param_snapshot,
            "world_model.verification_pending_threshold",
            0.5,
        )
        low_conf_threshold = get_raw_value(
            param_snapshot,
            "world_model.verification_low_confidence_threshold",
            0.15,
        )
        conf_floor = get_raw_value(
            param_snapshot,
            "world_model.verification_confidence_floor",
            0.05,
        )
        conf_ceiling = get_raw_value(
            param_snapshot,
            "world_model.verification_confidence_ceiling",
            0.95,
        )

        # ---- 快照安全化 ----
        snap_pre, snap_post = _safe_snap(snap)

        # ---- 规则安全化 ----
        safe_rules = _safe_rules(rules)
        safe_pending = _safe_rules(pending)

        # 合并去重（以 rules 为准）
        rules_map: Dict[str, Rule] = {}
        for r in safe_rules:
            rules_map[r.id] = r
        for r in safe_pending:
            if r.id not in rules_map:
                rules_map[r.id] = r

        now = time.time()
        result_rules: List[Rule] = []

        for rule in rules_map.values():
            # 仅验证有 predicts.expect 的规律
            if not rule.predicts.expect:
                result_rules.append(rule)
                continue

            # 执行验证
            verified, delta = _verify_single_rule(
                rule, snap_pre, snap_post, base_delta, max_delta
            )

            if delta == 0.0:
                result_rules.append(rule)
                continue

            # 更新置信度
            new_conf = rule.confidence + delta
            new_conf = max(conf_floor, min(conf_ceiling, new_conf))
            rule.confidence = new_conf

            # 更新经验计数
            rule.source_experience_count += 1
            rule.last_verified_at = now

            # 状态流转
            if rule.status == "pending":
                if rule.confidence >= pending_threshold:
                    rule.status = "active"
            elif rule.status == "active":
                if rule.confidence < low_conf_threshold:
                    rule.status = "pending"
            elif rule.status == "decayed":
                if new_conf > low_conf_threshold:
                    rule.status = "pending"

            # 置信度降到地板 → decayed
            if rule.confidence <= conf_floor:
                rule.status = "decayed"

            result_rules.append(rule)

        return result_rules

    except Exception:
        # 验证失败时返回原始规则，不抛异常
        return _safe_rules(rules)


# ============================================================================
# 测试入口
# ============================================================================

if __name__ == "__main__":
    from .defaults import DEFAULT_PARAMS

    print("=" * 64)
    print("验证模块测试")
    print("=" * 64)

    now = time.time()

    def make_rule(
        rid: str, conf: float, status: str, expect: str, exp_count: int = 1
    ) -> Rule:
        from .rules import Predicts
        return Rule(
            id=rid,
            content=f"Test rule {rid}",
            confidence=conf,
            source_experience_count=exp_count,
            stability_score=0.5,
            stability_band=0.1,
            created_at=now,
            last_verified_at=now,
            last_decay_at=now,
            status=status,
            context="test",
            predicts=Predicts(trigger=f"trigger_{rid}", expect=expect),
            evidence=[],
            _debug_meta={},
        )

    # 测试 1: 验证成功（info_gap 下降）
    print("\n【测试 1】验证成功 - info_gap 下降")
    rule = make_rule("v1", 0.5, "pending", "info_gap_decrease")
    snap = {
        "pre_state": {"info_gap": 0.7, "energy": 0.8},
        "post_state": {"info_gap": 0.6, "energy": 0.7},
    }
    result = verify_pending([rule], [], snap, DEFAULT_PARAMS)
    r = result[0]
    ok1 = r.confidence > 0.5 and r.source_experience_count == 2
    print(f"  {'✓' if ok1 else '✗'} conf: 0.5 → {r.confidence:.4f}, count: 1 → {r.source_experience_count}")
    print(f"  status: {r.status}（期望 active，conf 0.58 >= 0.5）")

    # 测试 2: 验证失败（预期下降但实际上升）
    print("\n【测试 2】验证失败 - info_gap 预期下降但实际上升")
    rule2 = make_rule("v2", 0.5, "pending", "info_gap_decrease")
    snap2 = {
        "pre_state": {"info_gap": 0.7, "energy": 0.8},
        "post_state": {"info_gap": 0.8, "energy": 0.7},
    }
    result2 = verify_pending([rule2], [], snap2, DEFAULT_PARAMS)
    r2 = result2[0]
    ok2 = r2.confidence < 0.5
    print(f"  {'✓' if ok2 else '✗'} conf: 0.5 → {r2.confidence:.4f}（应下降）")

    # 测试 3: max_delta 限制
    print("\n【测试 3】单次最大变化量限制")
    rule3 = make_rule("v3", 0.9, "active", "info_gap_decrease", exp_count=1)
    snap3 = {
        "pre_state": {"info_gap": 0.7, "energy": 0.8},
        "post_state": {"info_gap": 0.1, "energy": 0.7},
    }
    result3 = verify_pending([rule3], [], snap3, DEFAULT_PARAMS)
    r3 = result3[0]
    delta3 = r3.confidence - 0.9
    ok3 = abs(delta3) <= 0.15 + 1e-9
    print(f"  {'✓' if ok3 else '✗'} |delta| = {abs(delta3):.4f}（应 ≤ 0.15）")

    # 测试 4: 贝叶斯学习率
    print("\n【测试 4】贝叶斯学习率 — 经验越多 delta 越小")
    rule4a = make_rule("v4a", 0.5, "active", "info_gap_decrease", exp_count=1)
    rule4b = make_rule("v4b", 0.5, "active", "info_gap_decrease", exp_count=4)
    snap4 = {
        "pre_state": {"info_gap": 0.7, "energy": 0.8},
        "post_state": {"info_gap": 0.5, "energy": 0.7},
    }
    result4a = verify_pending([rule4a], [], snap4, DEFAULT_PARAMS)
    result4b = verify_pending([rule4b], [], snap4, DEFAULT_PARAMS)
    delta4a = result4a[0].confidence - 0.5
    delta4b = result4b[0].confidence - 0.5
    ok4 = abs(delta4b) < abs(delta4a)
    print(f"  {'✓' if ok4 else '✗'} exp=1: delta={delta4a:.4f}, exp=4: delta={delta4b:.4f}（后者应更小）")

    # 测试 5: 空规则列表
    print("\n【测试 5】空规则列表 → 原样返回")
    result5 = verify_pending([], [], {}, DEFAULT_PARAMS)
    ok5 = result5 == []
    print(f"  {'✓' if ok5 else '✗'} 空输入 → {result5}")

    # 测试 6: 无 expect 字段 → 跳过
    print("\n【测试 6】无 expect 字段 → 跳过验证")
    rule6 = make_rule("v6", 0.5, "active", "")
    snap6 = {"pre_state": {"info_gap": 0.7}, "post_state": {"info_gap": 0.5}}
    result6 = verify_pending([rule6], [], snap6, DEFAULT_PARAMS)
    r6 = result6[0]
    ok6 = r6.confidence == 0.5 and r6.source_experience_count == 1
    print(f"  {'✓' if ok6 else '✗'} 无 expect → conf={r6.confidence}, count={r6.source_experience_count}")

    print("\n" + "=" * 64)
    print("验证模块测试完成")
    print("=" * 64)
