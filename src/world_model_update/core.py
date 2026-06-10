"""
Core — 编排层 (Orchestration Layer)

负责任务编排和外部调度接口。

执行顺序（异步反思周期）：
    加载 → 归纳 → 合并 → 衰减 → 验证 → 持久化

约束：
    - 所有核心函数（induct / merge / decay / verify）是纯函数，不写文件
    - 本模块也不写文件，所有 IO 由 entity_zero_iteration.py 的外层调度器负责
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from . import induct as _induct
from . import induct_input as _induct_input
from . import verify as _verify
from . import decay as _decay
from . import merge as _merge
from .defaults import get_param
from .rules import Rule, Snap


# ============================================================================
# 类型别名
# ============================================================================

EmbeddingProvider = Any  # 见 merge_rules 的 embedding_provider 参数说明


# ============================================================================
# 统计信息
# ============================================================================

@dataclass
class CycleStats:
    """反思周期统计信息"""
    inducted: int = 0
    merged: int = 0
    decayed: int = 0
    verified: int = 0
    protected: int = 0
    promoted: int = 0
    demoted: int = 0
    pruned: int = 0


# ============================================================================
# 辅助函数
# ============================================================================

def _safe_rules(rules: Any) -> List[Rule]:
    """将任意规律格式安全化"""
    if not rules:
        return []
    result: List[Rule] = []
    for r in rules:
        if isinstance(r, Rule):
            result.append(r)
        elif isinstance(r, dict):
            result.append(Rule.from_dict(r))
    return result


def _safe_snaps(snaps: Any) -> List[Snap]:
    """将任意快照格式安全化"""
    if not snaps:
        return []
    result: List[Snap] = []
    for s in snaps:
        if isinstance(s, Snap):
            result.append(s)
        elif isinstance(s, dict):
            result.append(Snap.from_dict(s))
    return result


def _safe_snap(snap: Any) -> Optional[Snap]:
    """将单个快照安全化"""
    if isinstance(snap, Snap):
        return snap
    if isinstance(snap, dict):
        return Snap.from_dict(snap)
    return None


# ============================================================================
# 核心编排函数
# ============================================================================

def run_update_cycle(
    old_rules: List[Any],
    snaps: List[Any],
    dialogue_log: Any,
    state_snapshot: Any,
    param_snapshot: Any,
    embedding_provider: Optional[EmbeddingProvider] = None,
) -> tuple[List[Rule], CycleStats]:
    """
    异步反思周期主入口（世界模型更新管线）。

    执行顺序：加载 → 归纳 → 合并 → 衰减 → 验证

    参数：
        old_rules        : 当前存储的规律列表
        snaps            : 最近 N 轮的迭代快照列表（每轮包含 action_type、状态变化量等字段）
        dialogue_log     : 最近 N 轮的对话日志（当前版本中用于占位，
                         未来可用于对话上下文的因果推断）
        state_snapshot   : 必须重新拉取的最新状态快照，
                         不能是异步入口处缓存的旧值。
                         期望字段：stress, fatigue 等
        param_snapshot   : 参数只读快照，所有阈值和数量从此读取
        embedding_provider: 可选，嵌入相似度计算器（见 merge_rules 说明）

    返回：
        (new_rules, stats) — 更新后的规律列表 + 本轮统计信息

    约束：
        - 纯函数（编排层本身），不写文件，不写数据库
        - 所有 IO 由外层调度器负责
    """
    # 初始化统计
    stats = CycleStats()

    # 安全化
    current_rules = _safe_rules(old_rules)
    all_snaps = _safe_snaps(snaps)
    latest_snap = _safe_snap(state_snapshot)

    # ---- Step 1: 归纳 ----
    # 1a. action 触发归纳（既有路径，零改动）
    new_rules = _induct.induct_rules(
        old_rules=current_rules,
        snaps=all_snaps,
        param_snapshot=param_snapshot,
    )
    # 1b. input 触发归纳（②c 旁路：带 input_class 的快照学「输入→后果」规则）
    #     与 action 规则合流，一起进 merge/decay/verify。verify 收到 event_snaps 后
    #     按 input_class 把 input 规则匹配到对应事件快照验证（见 verify_pending）。
    new_rules += _induct_input.induct_input_rules(
        old_rules=current_rules,
        snaps=all_snaps,
        param_snapshot=param_snapshot,
    )
    stats.inducted = len(new_rules)

    # ---- Step 2: 合并 ----
    merged_rules = _merge.merge_rules(
        rules=current_rules,
        new_rules=new_rules,
        embedding_provider=embedding_provider,
        param_snapshot=param_snapshot,
    )
    stats.merged = len(current_rules) + len(new_rules) - len(merged_rules)

    # ---- Step 3: 衰减（必须用最新快照） ----
    # state_snapshot 已是最新快照，直接使用
    # all_snaps 用于计算维度维护成本（奥卡姆剃刀动力学）
    decayed_rules = _decay.decay_rules(
        rules=merged_rules,
        state_snapshot=state_snapshot,
        param_snapshot=param_snapshot,
        snapshots=all_snaps,
    )

    # 统计被保护的规律
    protected_count = 0
    decayed_count = 0
    conf_before = {r.id: r.confidence for r in merged_rules}
    conf_after = {r.id: r.confidence for r in decayed_rules}
    for rid in conf_before:
        if rid in conf_after:
            delta = conf_before[rid] - conf_after[rid]
            if delta < 0.001:
                protected_count += 1
            else:
                decayed_count += 1
    stats.protected = protected_count
    stats.decayed = decayed_count

    # ---- Step 4: 验证 ----
    pending_rules: List[Rule] = []
    active_rules: List[Rule] = []
    for r in decayed_rules:
        if r.status == "pending":
            pending_rules.append(r)
        elif r.status == "active":
            active_rules.append(r)
        else:
            active_rules.append(r)

    verified_rules: List[Rule] = []
    if latest_snap is not None:
        verified_rules = _verify.verify_pending(
            rules=active_rules,
            pending=pending_rules,
            snap=latest_snap,
            param_snapshot=param_snapshot,
            event_snaps=all_snaps,
        )
    else:
        verified_rules = active_rules + pending_rules

    # 统计状态变化
    pending_ids = {r.id for r in pending_rules}
    active_ids = {r.id for r in active_rules}

    promoted = sum(1 for r in verified_rules if r.status == "active" and r.id in pending_ids)
    demoted = sum(1 for r in verified_rules if r.status == "pending" and r.id in active_ids)
    stats.promoted = promoted
    stats.demoted = demoted
    stats.verified = len(verified_rules)

    # ---- Step 5: 种群上限 ----
    max_rules = int(get_param(param_snapshot, "world_model_max_rules", 200))
    if len(verified_rules) > max_rules:
        # 按 confidence 排序，淘汰最低置信度的规律
        verified_rules.sort(key=lambda r: r.confidence, reverse=True)
        pruned = verified_rules[max_rules:]
        verified_rules = verified_rules[:max_rules]
        stats.pruned = len(pruned)

    return verified_rules, stats


# ============================================================================
# 便捷包装函数（供 entity_zero_iteration.py 调用）
# ============================================================================

def induct_only(
    old_rules: List[Any],
    snaps: List[Any],
    param_snapshot: Any,
) -> List[Rule]:
    """仅执行归纳步骤。供外层单独调试或测试用。"""
    return _induct.induct_rules(old_rules, snaps, param_snapshot)


def merge_only(
    rules: List[Any],
    new_rules: List[Any],
    embedding_provider: Optional[EmbeddingProvider] = None,
    param_snapshot: Any = None,
) -> List[Rule]:
    """仅执行合并步骤。"""
    return _merge.merge_rules(rules, new_rules, embedding_provider, param_snapshot)


def decay_only(
    rules: List[Any],
    state_snapshot: Any,
    param_snapshot: Any,
) -> List[Rule]:
    """仅执行衰减步骤。"""
    return _decay.decay_rules(rules, state_snapshot, param_snapshot)


def verify_only(
    rules: List[Any],
    pending: List[Any],
    snap: Any,
    param_snapshot: Any,
) -> List[Rule]:
    """仅执行验证步骤。"""
    return _verify.verify_pending(rules, pending, snap, param_snapshot)


# ============================================================================
# 测试入口
# ============================================================================

if __name__ == "__main__":
    import copy
    import time as _time

    from .defaults import DEFAULT_PARAMS

    print("=" * 64)
    print("World Model Update — 集成测试")
    print("=" * 64)

    now = _time.time()

    def make_snap(
        idx: int,
        action: str,
        energy: float = 0.8,
        info_gap: float = 0.7,
        loneliness: float = 0.3,
        fatigue: float = 0.2,
        stress: float = 0.1,
    ) -> Snap:
        return Snap(
            snap_index=idx,
            timestamp=now + idx,
            action_type=action,
            target="none",
            priority=0.5,
            pre_state={
                "energy": energy,
                "info_gap": info_gap,
                "loneliness": loneliness,
                "fatigue": fatigue,
                "stress": stress,
            },
            post_state={
                "energy": energy - 0.05,
                "info_gap": info_gap - 0.10,
                "loneliness": loneliness + 0.02,
                "fatigue": fatigue + 0.03,
                "stress": stress + 0.01,
            },
        )

    # ---- 测试 1: 全反思周期 ----
    print("\n【测试 1】run_update_cycle 全周期")
    full_snaps = [
        make_snap(0, "seek", energy=0.8, info_gap=0.7),
        make_snap(1, "seek", energy=0.8, info_gap=0.8),
        make_snap(2, "seek", energy=0.8, info_gap=0.6),
        make_snap(3, "seek", energy=0.7, info_gap=0.5),
        make_snap(4, "",  energy=0.8, info_gap=0.7),
        make_snap(5, "",  energy=0.8, info_gap=0.7),
        make_snap(6, "",  energy=0.3, info_gap=0.4),
        make_snap(7, "",  energy=0.3, info_gap=0.4),
    ]
    latest = make_snap(8, "seek", energy=0.8, info_gap=0.6)
    existing_rules = [
        Rule(
            id="er1",
            content="已知规律",
            confidence=0.7,
            source_experience_count=3,
            stability_score=0.5,
            stability_band=0.1,
            created_at=now,
            last_verified_at=now,
            last_decay_at=now - 100,
            status="active",
            context="test",
            predicts={"trigger": "old_trigger", "expect": "info_gap_decrease"},
            evidence=[],
        )
    ]

    class SimpleSim:
        def compute_similarity(self, a, b):
            return 0.9

    final_rules, stats = run_update_cycle(
        old_rules=existing_rules,
        snaps=full_snaps,
        dialogue_log=[],
        state_snapshot=latest.post_state,
        param_snapshot=DEFAULT_PARAMS,
        embedding_provider=SimpleSim(),
    )
    print(f"  输入规则: {len(existing_rules)}, 输出规则: {len(final_rules)}")
    print(f"  统计: inducted={stats.inducted}, merged={stats.merged}, "
          f"decayed={stats.decayed}, verified={stats.verified}")
    ok1 = len(final_rules) >= 1
    print(f"  {'✓' if ok1 else '✗'} 全周期输出有效规则")

    # ---- 测试 2: 空输入保护 ----
    print("\n【测试 2】空输入保护")
    result_empty = run_update_cycle([], [], [], None, DEFAULT_PARAMS)
    ok2 = isinstance(result_empty[0], list)
    print(f"  {'✓' if ok2 else '✗'} 空输入不抛异常，返回: {type(result_empty[0])}")

    # ---- 测试 3: 便捷包装函数 ----
    print("\n【测试 3】便捷包装函数")
    ind_result = induct_only([], full_snaps, DEFAULT_PARAMS)
    ok3a = isinstance(ind_result, list)
    dec_result = decay_only([existing_rules[0]], {"stress": 0.0, "fatigue": 0.0}, DEFAULT_PARAMS)
    ok3b = isinstance(dec_result, list)
    print(f"  {'✓' if ok3a else '✗'} induct_only: {len(ind_result)} 条")
    print(f"  {'✓' if ok3b else '✗'} decay_only: {len(dec_result)} 条")

    # ---- 测试 4: 纯函数验证（无文件IO）----
    print("\n【测试 4】纯函数验证（无文件IO）")
    import sys
    io_keywords = ["open(", "json.dump", "save(", "write(", ".to_file", "pickle.dump"]
    import inspect as _inspect
    modules_to_check = [
        (_induct, "induct"),
        (_verify, "verify"),
        (_decay, "decay"),
        (_merge, "merge"),
    ]
    all_clean = True
    for mod, name in modules_to_check:
        src = _inspect.getsource(mod)
        for kw in io_keywords:
            if kw in src:
                print(f"  ✗ {name} 源码包含 IO 关键字: {kw}")
                all_clean = False
    if all_clean:
        print("  ✓ 所有核心函数无文件IO")

    print("\n" + "=" * 64)
    print("World Model Update 集成测试完成")
    print("=" * 64)
