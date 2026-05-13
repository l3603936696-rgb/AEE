"""
Anti-Stuck Module (防卡死机制)

设计文档：ai_cognitive_system_v2.txt 第二章 第8节

位置：裁决系统之后、意图编码器之前。

职责：检测行为模式是否陷入死循环，必要时覆写 decision。

检测规则：
    1. 兜底逻辑：历史不足 N 轮时，直接原样返回
    2. 同源检测：最近 N 轮 context_id 完全一致
    3. 平稳检测：最近 N 轮 priority 极差小于阈值

覆写策略：
    同源检测 + 平稳检测 同时触发时，强制覆写为 comfort 模式

硬约束：
    - 纯函数，不修改任何外部状态
    - 异常时原样返回 decision，不抛异常
    - 任一检测失败跳过该检测，不触发死循环判定
"""

from typing import Any, List, Optional


# ============================================================================
# 参数默认值
# ============================================================================

DEFAULT_PARAMS = {
    "anti_stuck_lookback": 3,           # 回看轮数
    "anti_stuck_priority_variance": 0.2,  # 平稳检测阈值（极差）
    "anti_stuck_override_priority": 0.3,  # 覆写后的 priority
}


# ============================================================================
# 内部工具函数
# ============================================================================

def _safe_get(data: Any, key: str, default: Any = None) -> Any:
    """安全读取字典字段，异常时返回默认值。"""
    try:
        if isinstance(data, dict):
            return data.get(key, default)
        return default
    except Exception:
        return default


def _resolve_context_id(decision: Any) -> Optional[str]:
    """从 decision 中解析 context_id。"""
    try:
        if not isinstance(decision, dict):
            return None
        payload = decision.get("payload")
        if isinstance(payload, dict):
            return payload.get("context_id")
        # payload 不存在时，尝试直接取 context_id 字段
        return decision.get("context_id")
    except Exception:
        return None


def _resolve_priority(decision: Any) -> Optional[float]:
    """从 decision 中解析 priority。"""
    try:
        if not isinstance(decision, dict):
            return None
        val = decision.get("priority")
        if isinstance(val, (int, float)):
            return float(val)
        return None
    except Exception:
        return None


# ============================================================================
# 同源检测
# ============================================================================

def _check_same_source(
    current_decision: Any,
    recent_decisions: List[Any],
    lookback: int,
) -> bool:
    """
    同源检测：检查最近 N 轮决策（含当前轮）的触发源是否完全一致。

    触发源来自 decision.payload.context_id 字段。
    若当前决策或历史记录中没有 context_id 字段，跳过同源检测，返回 False。

    返回 True 表示触发死循环（同源）。
    """
    try:
        # 检查当前决策
        current_cid = _resolve_context_id(current_decision)
        if current_cid is None:
            return False

        # 收集最近 N-1 轮历史（+当前 = N 轮）
        history_ids: List[str] = []
        for dec in recent_decisions[-lookback + 1:]:
            cid = _resolve_context_id(dec)
            if cid is None:
                # 历史任意一条缺失 → 跳过同源检测
                return False
            history_ids.append(cid)

        # 合并当前 + 历史
        all_ids = [current_cid] + history_ids

        # 所有 context_id 完全一致 → 死循环
        return len(set(all_ids)) == 1

    except Exception:
        return False


# ============================================================================
# 平稳检测
# ============================================================================

def _check_flat_priority(
    current_decision: Any,
    recent_decisions: List[Any],
    lookback: int,
    variance_threshold: float,
) -> bool:
    """
    平稳检测：计算最近 N 轮（含当前轮）priority 的极差（最大值 - 最小值）。
    若极差小于 variance_threshold，判定为平稳（死循环）。

    返回 True 表示触发死循环（平稳）。
    """
    try:
        # 检查当前决策
        current_p = _resolve_priority(current_decision)
        if current_p is None:
            return False

        # 收集最近 N-1 轮历史（+当前 = N 轮）
        priorities: List[float] = [current_p]
        for dec in recent_decisions[-lookback + 1:]:
            p = _resolve_priority(dec)
            if p is None:
                return False
            priorities.append(p)

        if len(priorities) < 2:
            return False

        priority_range = max(priorities) - min(priorities)
        return priority_range < variance_threshold

    except Exception:
        return False


# ============================================================================
# 覆写决策
# ============================================================================

def _override_decision(params: dict) -> dict:
    """
    构建被覆写的 decision。

    action_type → comfort
    target → none
    priority → params.anti_stuck_override_priority（默认 0.3）
    payload.reason → 死循环说明
    """
    try:
        override_priority = float(
            params.get("anti_stuck_override_priority", DEFAULT_PARAMS["anti_stuck_override_priority"])
        )
    except (TypeError, ValueError):
        override_priority = DEFAULT_PARAMS["anti_stuck_override_priority"]

    return {
        "action_type": "comfort",
        "target": "none",
        "priority": override_priority,
        "payload": {
            "source": "anti_stuck",
            "context_id": "",
            "reason": "系统检测到行为死循环，自动降级为舒适模式",
        },
    }


# ============================================================================
# 主入口
# ============================================================================

def anti_stuck_check(
    decision: Any,
    decision_history: List[Any],
    state_snapshot: Any,
    params: Optional[dict] = None,
) -> dict:
    """
    防卡死机制主入口。

    裁决系统之后、意图编码器之前调用。

    参数：
        decision: 来自裁决系统的当前决策
            {
                "action_type": str,
                "target": str,
                "priority": float,
                "payload": {
                    "source": str,
                    "context_id": str,
                    "reason": str,
                }
            }
        decision_history: 最近 N 轮历史决策列表
            每个元素为历史 decision。
            如果历史不足 N 轮，传入已有全部记录。
        state_snapshot: 当前实体状态快照（当前版本预留，不参与判定）
        params: 防卡死参数表，包含：
            - anti_stuck_lookback: int，默认 3
            - anti_stuck_priority_variance: float，默认 0.2
            - anti_stuck_override_priority: float，默认 0.3

    返回：
        decision（可能被覆写）

    检测流程：
        1. 兜底：历史不足 N 轮 → 原样返回
        2. 同源检测：最近 N 轮 context_id 完全一致 → 标记
        3. 平稳检测：最近 N 轮 priority 极差 < 阈值 → 标记
        4. 同源 + 平稳同时触发 → 强制覆写为 comfort
        5. 否则 → 原样返回
    """
    try:
        # 边界检查
        if not isinstance(decision, dict):
            return decision  # 非字典时原样返回

        # 合并参数
        merged = {**DEFAULT_PARAMS, **(params or {})}
        lookback = int(merged.get("anti_stuck_lookback", DEFAULT_PARAMS["anti_stuck_lookback"]))
        variance = float(merged.get("anti_stuck_priority_variance", DEFAULT_PARAMS["anti_stuck_priority_variance"]))

        # 确保 decision_history 是列表
        history = decision_history if isinstance(decision_history, list) else []

        # ---- 兜底逻辑：历史不足 N 轮 → 原样返回 ----
        if len(history) < lookback:
            return decision.copy() if isinstance(decision, dict) else decision

        # ---- 同源检测 ----
        same_source = _check_same_source(decision, history, lookback)

        # ---- 平稳检测 ----
        flat_priority = _check_flat_priority(decision, history, lookback, variance)

        # ---- 覆写判定：同源 + 平稳同时触发 ----
        if same_source and flat_priority:
            return _override_decision(merged)

        # ---- 否则：原样返回 ----
        return decision.copy() if isinstance(decision, dict) else decision

    except Exception:
        # 任何异常 → 原样返回
        return decision.copy() if isinstance(decision, dict) else decision


# ============================================================================
# 测试入口
# ============================================================================

if __name__ == "__main__":
    import copy

    print("=" * 64)
    print("防卡死机制测试")
    print("=" * 64)

    # 标准参数
    default_params = {
        "anti_stuck_lookback": 3,
        "anti_stuck_priority_variance": 0.2,
        "anti_stuck_override_priority": 0.3,
    }

    # 测试用例
    test_cases = [
        {
            "name": "兜底：历史不足3轮",
            "decision": {"action_type": "seek", "target": "none", "priority": 0.8, "payload": {"source": "test", "context_id": "ctx1", "reason": "测试"}},
            "decision_history": [
                {"action_type": "seek", "target": "none", "priority": 0.8, "payload": {"source": "test", "context_id": "ctx1", "reason": "测试"}},
            ],
            "params": {},
            "expect_override": False,
            "expect_action": "seek",
        },
        {
            "name": "兜底：空历史",
            "decision": {"action_type": "seek", "target": "none", "priority": 0.8, "payload": {"source": "test", "context_id": "ctx1", "reason": "测试"}},
            "decision_history": [],
            "params": {},
            "expect_override": False,
            "expect_action": "seek",
        },
        {
            "name": "兜底：历史不足N轮（参数lookback=5）",
            "decision": {"action_type": "seek", "target": "none", "priority": 0.8, "payload": {"source": "test", "context_id": "ctx1", "reason": "测试"}},
            "decision_history": [
                {"action_type": "seek", "target": "none", "priority": 0.8, "payload": {"source": "test", "context_id": "ctx1", "reason": "测试"}},
                {"action_type": "seek", "target": "none", "priority": 0.85, "payload": {"source": "test", "context_id": "ctx1", "reason": "测试"}},
            ],
            "params": {"anti_stuck_lookback": 5},
            "expect_override": False,
            "expect_action": "seek",
        },
        {
            "name": "死循环触发：同源+平稳同时",
            "decision": {"action_type": "seek", "target": "none", "priority": 0.8, "payload": {"source": "test", "context_id": "ctx1", "reason": "测试"}},
            "decision_history": [
                {"action_type": "seek", "target": "none", "priority": 0.81, "payload": {"source": "test", "context_id": "ctx1", "reason": "测试"}},
                {"action_type": "seek", "target": "none", "priority": 0.82, "payload": {"source": "test", "context_id": "ctx1", "reason": "测试"}},
                {"action_type": "seek", "target": "none", "priority": 0.83, "payload": {"source": "test", "context_id": "ctx1", "reason": "测试"}},
            ],
            "params": {},
            "expect_override": True,
            "expect_action": "comfort",
            "expect_reason_contains": "死循环",
        },
        {
            "name": "仅同源触发：context_id变化",
            "decision": {"action_type": "seek", "target": "none", "priority": 0.8, "payload": {"source": "test", "context_id": "ctx1", "reason": "测试"}},
            "decision_history": [
                {"action_type": "seek", "target": "none", "priority": 0.81, "payload": {"source": "test", "context_id": "ctx1", "reason": "测试"}},
                {"action_type": "seek", "target": "none", "priority": 0.82, "payload": {"source": "test", "context_id": "ctx2", "reason": "测试"}},
                {"action_type": "seek", "target": "none", "priority": 0.83, "payload": {"source": "test", "context_id": "ctx1", "reason": "测试"}},
            ],
            "params": {},
            "expect_override": False,
            "expect_action": "seek",
        },
        {
            "name": "仅平稳触发：priority波动大",
            "decision": {"action_type": "seek", "target": "none", "priority": 0.9, "payload": {"source": "test", "context_id": "ctx1", "reason": "测试"}},
            "decision_history": [
                {"action_type": "seek", "target": "none", "priority": 0.3, "payload": {"source": "test", "context_id": "ctx1", "reason": "测试"}},
                {"action_type": "seek", "target": "none", "priority": 0.5, "payload": {"source": "test", "context_id": "ctx1", "reason": "测试"}},
                {"action_type": "seek", "target": "none", "priority": 0.7, "payload": {"source": "test", "context_id": "ctx1", "reason": "测试"}},
            ],
            "params": {},
            "expect_override": False,
            "expect_action": "seek",
        },
        {
            "name": "缺失context_id字段：跳过同源检测",
            "decision": {"action_type": "seek", "target": "none", "priority": 0.8, "payload": {"source": "test", "reason": "测试"}},
            "decision_history": [
                {"action_type": "seek", "target": "none", "priority": 0.81, "payload": {"source": "test", "context_id": "ctx1", "reason": "测试"}},
                {"action_type": "seek", "target": "none", "priority": 0.82, "payload": {"source": "test", "context_id": "ctx1", "reason": "测试"}},
                {"action_type": "seek", "target": "none", "priority": 0.83, "payload": {"source": "test", "context_id": "ctx1", "reason": "测试"}},
            ],
            "params": {},
            "expect_override": False,
            "expect_action": "seek",
        },
        {
            "name": "缺失priority字段：跳过平稳检测",
            "decision": {"action_type": "seek", "target": "none", "priority": 0.8, "payload": {"source": "test", "context_id": "ctx1", "reason": "测试"}},
            "decision_history": [
                {"action_type": "seek", "target": "none", "priority": 0.81, "payload": {"source": "test", "context_id": "ctx1", "reason": "测试"}},
                {"action_type": "seek", "target": "none", "priority": 0.82, "payload": {"source": "test", "context_id": "ctx1", "reason": "测试"}},
                {"action_type": "seek", "target": "none", "payload": {"source": "test", "context_id": "ctx1", "reason": "测试"}},  # 无 priority
            ],
            "params": {},
            "expect_override": False,
            "expect_action": "seek",
        },
        {
            "name": "平稳阈值调高：极差0.2不被判定",
            "decision": {"action_type": "seek", "target": "none", "priority": 0.85, "payload": {"source": "test", "context_id": "ctx1", "reason": "测试"}},
            "decision_history": [
                {"action_type": "seek", "target": "none", "priority": 0.60, "payload": {"source": "test", "context_id": "ctx1", "reason": "测试"}},
                {"action_type": "seek", "target": "none", "priority": 0.70, "payload": {"source": "test", "context_id": "ctx1", "reason": "测试"}},
                {"action_type": "seek", "target": "none", "priority": 0.80, "payload": {"source": "test", "context_id": "ctx1", "reason": "测试"}},
            ],
            "params": {"anti_stuck_priority_variance": 0.1},  # 阈值0.1，极差0.20不触发
            "expect_override": False,
            "expect_action": "seek",
        },
        {
            "name": "平稳阈值调低：极差0.05被判定",
            "decision": {"action_type": "seek", "target": "none", "priority": 0.83, "payload": {"source": "test", "context_id": "ctx1", "reason": "测试"}},
            "decision_history": [
                {"action_type": "seek", "target": "none", "priority": 0.80, "payload": {"source": "test", "context_id": "ctx1", "reason": "测试"}},
                {"action_type": "seek", "target": "none", "priority": 0.81, "payload": {"source": "test", "context_id": "ctx1", "reason": "测试"}},
                {"action_type": "seek", "target": "none", "priority": 0.85, "payload": {"source": "test", "context_id": "ctx1", "reason": "测试"}},
            ],
            "params": {"anti_stuck_priority_variance": 0.1},  # 阈值0.1，极差0.05触发
            "expect_override": True,
            "expect_action": "comfort",
        },
        {
            "name": "覆写后priority值正确",
            "decision": {"action_type": "seek", "target": "none", "priority": 0.8, "payload": {"source": "test", "context_id": "ctx1", "reason": "测试"}},
            "decision_history": [
                {"action_type": "seek", "target": "none", "priority": 0.81, "payload": {"source": "test", "context_id": "ctx1", "reason": "测试"}},
                {"action_type": "seek", "target": "none", "priority": 0.82, "payload": {"source": "test", "context_id": "ctx1", "reason": "测试"}},
                {"action_type": "seek", "target": "none", "priority": 0.83, "payload": {"source": "test", "context_id": "ctx1", "reason": "测试"}},
            ],
            "params": {"anti_stuck_override_priority": 0.5},
            "expect_override": True,
            "expect_action": "comfort",
            "expect_priority": 0.5,
        },
        {
            "name": "decision非字典：返回原始对象",
            "decision": "invalid",
            "decision_history": [],
            "params": {},
            "expect_override": False,
            "expect_raw": "invalid",
        },
        {
            "name": "空decision_history但有3条",
            "decision": {"action_type": "seek", "target": "none", "priority": 0.8, "payload": {"source": "test", "context_id": "ctx1", "reason": "测试"}},
            "decision_history": [
                {"action_type": "seek", "target": "none", "priority": 0.8, "payload": {"source": "test", "context_id": "ctx1", "reason": "测试"}},
                {"action_type": "seek", "target": "none", "priority": 0.8, "payload": {"source": "test", "context_id": "ctx1", "reason": "测试"}},
                {"action_type": "seek", "target": "none", "priority": 0.8, "payload": {"source": "test", "context_id": "ctx1", "reason": "测试"}},
            ],
            "params": {},
            "expect_override": True,
            "expect_action": "comfort",
        },
    ]

    passed = 0
    for i, tc in enumerate(test_cases, 1):
        result = anti_stuck_check(
            copy.deepcopy(tc["decision"]),
            copy.deepcopy(tc["decision_history"]),
            {},
            tc.get("params", {}),
        )

        # 非字典结果：仅比对原始值
        if not isinstance(result, dict):
            ok_raw = (
                "expect_raw" not in tc
                or result == tc["expect_raw"]
            )
            ok = ok_raw
            status = "✓" if ok else "✗"
            if ok:
                passed += 1
            print(f"\n【测试 {i}】{tc['name']}  {status}")
            print(f"  result (非字典): {result}")
        else:
            ok_override = result.get("action_type") == tc.get("expect_action", result.get("action_type"))
            ok_reason = (
                tc.get("expect_reason_contains") is None
                or tc["expect_reason_contains"] in str(result.get("payload", {}).get("reason", ""))
            )
            ok_priority = (
                tc.get("expect_priority") is None
                or abs(result.get("priority", -1) - tc["expect_priority"]) < 1e-6
            )
            ok = ok_override and ok_reason and ok_priority
            status = "✓" if ok else "✗"
            if ok:
                passed += 1
            print(f"\n【测试 {i}】{tc['name']}  {status}")
            print(f"  action_type : {result.get('action_type', 'N/A')}")
            print(f"  target      : {result.get('target', 'N/A')}")
            print(f"  priority    : {result.get('priority', 'N/A')}")
            reason = result.get("payload", {}).get("reason", "N/A")
            print(f"  reason      : {reason}")

    print(f"\n{'='*64}")
    print(f"通过率: {passed}/{len(test_cases)}")
    print("=" * 64)
