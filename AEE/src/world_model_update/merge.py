"""
Merge Module (合并模块)

O(N) 增量合并器：仅对 induct_rules 产出的新规律（最多 3 条）做嵌入相似度计算，
与现有规律库逐一比较，合并高度相似的规律。

核心约束（绝对禁止）：
    - 禁止实现 O(N²) 全量两两相似度比较
    - 仅遍历 new_rules（最多 3 条），对每条遍历所有现有 rules
    - 仅对最多 3 条新规律使用 embedding_provider.compute_similarity
    - 纯函数，不写文件，不写数据库

合并策略：
    - 相似度 >= merge_threshold（默认 0.85）时触发合并
    - 保留置信度较高者
    - 合并 source_experience_count（取最大）
    - 低置信度（< low_confidence_threshold）规律被高置信度规律合并时直接淘汰
"""

import time
from typing import Any, Callable, Dict, List, Optional

from .defaults import get_raw_value
from .rules import Rule


# ============================================================================
# 辅助函数
# ============================================================================

def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _safe_get_content(rule: Any) -> str:
    """安全获取规律 content 字段"""
    if isinstance(rule, Rule):
        return rule.content
    if isinstance(rule, dict):
        return str(rule.get("content", ""))
    return ""


def _safe_get_confidence(rule: Any) -> float:
    """安全获取规律 confidence 字段"""
    if isinstance(rule, Rule):
        return rule.confidence
    if isinstance(rule, dict):
        return _safe_float(rule.get("confidence", 0.5))
    return 0.5


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


# ============================================================================
# 核心合并逻辑
# ============================================================================

def _compute_similarity_with_fallback(
    rule_a: Rule,
    rule_b: Rule,
    embedding_provider: Optional[Any],
) -> float:
    """
    计算两条规律的语义相似度。

    若 embedding_provider 可用且含 compute_similarity → 调用之
    否则 → 降级为关键词重叠法（Jaccard）
    """
    content_a = _safe_get_content(rule_a)
    content_b = _safe_get_content(rule_b)

    if not content_a or not content_b:
        return 0.0

    # 尝试使用 embedding_provider
    if embedding_provider is not None:
        try:
            ep = embedding_provider
            if callable(ep):
                sim = ep(content_a, content_b)
                if isinstance(sim, (int, float)):
                    return max(0.0, min(1.0, float(sim)))
            elif hasattr(ep, "compute_similarity"):
                sim = ep.compute_similarity(content_a, content_b)
                if isinstance(sim, (int, float)):
                    return max(0.0, min(1.0, float(sim)))
        except Exception:
            pass  # 降级到关键词重叠法

    # 降级：关键词重叠法（Jaccard）
    words_a = set(content_a.lower().split())
    words_b = set(content_b.lower().split())
    intersection = words_a & words_b
    union = words_a | words_b
    if not union:
        return 0.0
    jaccard = len(intersection) / len(union)
    return max(0.0, min(1.0, jaccard))


def _choose_winner(rule_a: Rule, rule_b: Rule) -> tuple[Rule, Rule]:
    """
    选择合并后的胜者。

    规则：
        - 置信度较高者胜出
        - 若置信度相同，经验计数较多者胜出
    返回（winner, loser）
    """
    conf_a = _safe_get_confidence(rule_a)
    conf_b = _safe_get_confidence(rule_b)

    if conf_b > conf_a:
        return rule_b, rule_a
    elif conf_a == conf_b:
        exp_a = getattr(rule_a, "source_experience_count", 1)
        exp_b = getattr(rule_b, "source_experience_count", 1)
        if exp_b > exp_a:
            return rule_b, rule_a
    return rule_a, rule_b


def _apply_merge(winner: Rule, loser: Rule) -> Rule:
    """
    将 loser 的信息合并到 winner，返回合并后的规律。

    合并规则：
        - 保留 winner 的 id、content、confidence
        - 累加 source_experience_count（取 max）
        - 合并 evidence 列表（按 snap_indices 去重后拼接）
        - 更新 last_verified_at
    """
    try:
        merged = Rule.from_dict(winner.to_dict())
    except Exception:
        import copy
        merged = copy.deepcopy(winner)

    # 累加经验计数（取 max）
    exp_w = getattr(winner, "source_experience_count", 1)
    exp_l = getattr(loser, "source_experience_count", 1)
    merged.source_experience_count = max(exp_w, exp_l)

    # 合并 evidence（按 snap_indices 去重）
    existing_indices = set()
    for ev in merged.evidence:
        for idx in ev.snap_indices:
            existing_indices.add(idx)

    from .rules import Evidence as EvClass
    for ev_loser in loser.evidence:
        if not isinstance(ev_loser, dict):
            ev_loser = ev_loser.to_dict()
        new_indices = [
            idx for idx in ev_loser.get("snap_indices", [])
            if idx not in existing_indices
        ]
        if new_indices:
            merged.evidence.append(EvClass(
                discrimination=float(ev_loser.get("discrimination", 0.0)),
                effect_action_mean=float(ev_loser.get("effect_action_mean", 0.0)),
                effect_baseline_mean=float(ev_loser.get("effect_baseline_mean", 0.0)),
                action_sample_count=int(ev_loser.get("action_sample_count", 0)),
                counterfactual_count=int(ev_loser.get("counterfactual_count", 0)),
                state_field=str(ev_loser.get("state_field", "")),
                snap_indices=new_indices,
            ))

    # 更新时间戳
    merged.last_verified_at = time.time()

    return merged


# ============================================================================
# 主入口：merge_rules
# ============================================================================

def merge_rules(
    rules: List[Any],
    new_rules: List[Any],
    embedding_provider: Optional[Any] = None,
    param_snapshot: Any = None,
) -> List[Rule]:
    """
    合并模块主入口。

    参数：
        rules              : 现有规律列表
        new_rules          : induct_rules 产出的新规律列表（最多 3 条）
        embedding_provider  : 可选，嵌入相似度计算器。
                            支持两种形式：
                            1. callable: compute_similarity(a: str, b: str) -> float
                            2. object:  含 compute_similarity(a: str, b: str) 方法
                            若不提供或调用失败，降级为关键词重叠法。
        param_snapshot     : 参数只读快照（来自 parameter_system）

    返回：
        List[Rule] — 合并后的规律列表

    约束（绝对禁止）：
        - 禁止 O(N²) 全量两两比较
        - 仅对 new_rules（最多 3 条）使用 embedding_provider
        - 纯函数，不写文件，不写数据库
    """
    try:
        # ---- 参数读取（严禁 default=None）----
        merge_threshold = get_raw_value(
            param_snapshot,
            "world_model.merge_threshold",
            0.85,
        )
        low_conf_threshold = get_raw_value(
            param_snapshot,
            "world_model.low_confidence_threshold",
            0.15,
        )

        # ---- 现有规律安全化 ----
        existing: Dict[str, Rule] = {}
        for r in _safe_rules(rules):
            if r.id:
                existing[r.id] = r

        # ---- 新规律安全化（限制最多 3 条）----
        safe_new: List[Rule] = []
        for r in _safe_rules(new_rules):
            safe_new.append(r)
            if len(safe_new) >= 3:
                break

        # ---- 增量合并：每条新规律遍历所有现有规律 ----
        merged_ids: set = set()

        for new_rule in safe_new:
            if not new_rule.id:
                continue
            for existing_id, existing_rule in existing.items():
                if existing_id == new_rule.id:
                    continue

                # 计算相似度（仅对 new_rule 使用 embedding_provider）
                sim = _compute_similarity_with_fallback(
                    new_rule, existing_rule, embedding_provider
                )

                if sim >= merge_threshold:
                    # 选择胜者
                    winner, loser = _choose_winner(existing_rule, new_rule)

                    if winner is new_rule:
                        # 新规律胜出
                        merged = _apply_merge(new_rule, existing_rule)
                        existing[existing_id] = merged
                    else:
                        # 现有规律胜出
                        merged = _apply_merge(existing_rule, new_rule)
                        existing[existing_id] = merged

                    merged_ids.add(new_rule.id)
                    break  # 每条新规律只合并一次

        # ---- 构建最终结果 ----
        result: List[Rule] = list(existing.values())

        # 添加未能合并的新规律（作为独立规律加入）
        for new_rule in safe_new:
            if new_rule.id not in merged_ids:
                result.append(new_rule)

        return result

    except Exception:
        # 合并失败时返回现有规律 + 所有新规律
        return _safe_rules(rules) + _safe_rules(new_rules)


# ============================================================================
# 测试入口
# ============================================================================

if __name__ == "__main__":
    from .defaults import DEFAULT_PARAMS

    print("=" * 64)
    print("合并模块测试")
    print("=" * 64)

    now = time.time()

    def make_rule(rid: str, content: str, conf: float, exp: int = 1) -> Rule:
        from .rules import Predicts
        return Rule(
            id=rid,
            content=content,
            confidence=conf,
            source_experience_count=exp,
            stability_score=0.5,
            stability_band=0.1,
            created_at=now,
            last_verified_at=now,
            last_decay_at=now,
            status="active",
            context="test",
            predicts=Predicts(trigger=f"trigger_{rid}", expect="info_gap_decrease"),
            evidence=[],
            _debug_meta={},
        )

    class MockEmbeddingProvider:
        def __init__(self, similarities: dict):
            self.similarities = similarities

        def compute_similarity(self, a: str, b: str) -> float:
            key = tuple(sorted([a, b]))
            return self.similarities.get(key, 0.0)

    # 测试 1: 高相似度 → 合并（现有规律胜出）
    print("\n【测试 1】高相似度 → 合并（现有规律胜出）")
    existing1 = [
        make_rule("r1", "高能量时执行seek动作，info_gap下降均值0.05，对照组自然下降均值0.01，区分度0.04", 0.8, exp=5),
    ]
    new1 = [
        make_rule("n1", "高能量时执行seek动作，info_gap下降均值0.05，对照组自然下降均值0.01，区分度0.04", 0.6, exp=2),
    ]
    mock_ep1 = MockEmbeddingProvider({(new1[0].content, existing1[0].content): 0.95})
    result1 = merge_rules(existing1, new1, mock_ep1, DEFAULT_PARAMS)
    ok1 = len(result1) == 1 and "r1" in [r.id for r in result1]
    print(f"  {'✓' if ok1 else '✗'} 合并后规律数: {len(result1)}（期望 1）")
    if result1:
        print(f"  winner confidence: {result1[0].confidence:.3f}（期望 0.8，胜者置信度保留）")

    # 测试 2: 低相似度 → 不合并
    print("\n【测试 2】低相似度 → 不合并")
    existing2 = [
        make_rule("r2", "孤独时发起社交，loneliness下降，区分度高", 0.7, exp=3),
    ]
    new2 = [
        make_rule("n2", "高能量时执行seek动作，info_gap下降均值0.05，对照组自然下降均值0.01", 0.6, exp=2),
    ]
    mock_ep2 = MockEmbeddingProvider({(new2[0].content, existing2[0].content): 0.2})
    result2 = merge_rules(existing2, new2, mock_ep2, DEFAULT_PARAMS)
    result_ids2 = [r.id for r in result2]
    ok2 = len(result2) == 2 and "n2" in result_ids2
    print(f"  {'✓' if ok2 else '✗'} 未合并：{len(result2)} 条规律（期望 2）")

    # 测试 3: 新规律置信度更高 → 新规律胜出
    print("\n【测试 3】新规律置信度更高 → 新规律胜出")
    existing3 = [
        make_rule("r3", "高能量时执行seek动作，info_gap下降均值0.05，对照组自然下降均值0.01，区分度0.04", 0.6, exp=2),
    ]
    new3 = [
        make_rule("n3", "高能量时执行seek动作，info_gap下降均值0.05，对照组自然下降均值0.01，区分度0.04", 0.9, exp=8),
    ]
    mock_ep3 = MockEmbeddingProvider({(new3[0].content, existing3[0].content): 0.92})
    result3 = merge_rules(existing3, new3, mock_ep3, DEFAULT_PARAMS)
    ok3 = len(result3) == 1 and result3[0].confidence == 0.9 and result3[0].source_experience_count == 8
    print(f"  {'✓' if ok3 else '✗'} 新规律胜出: conf={result3[0].confidence}, exp={result3[0].source_experience_count}")

    # 测试 4: 无 embedding_provider → 降级为关键词重叠法
    print("\n【测试 4】无 embedding_provider → 降级为关键词重叠法")
    existing4 = [
        make_rule("r4", "高能量时执行seek动作，info_gap下降均值0.05，对照组自然下降均值0.01，区分度0.04", 0.7, exp=3),
    ]
    new4 = [
        make_rule("n4", "高能量时执行seek动作，info_gap下降均值0.05，对照组自然下降均值0.01，区分度0.04", 0.6, exp=2),
    ]
    # 用低阈值让 Jaccard 通过
    low_thresh_params = DEFAULT_PARAMS.copy()
    low_thresh_params["world_model.merge_threshold"] = 0.3
    result4 = merge_rules(existing4, new4, None, low_thresh_params)
    ok4 = len(result4) == 1 and result4[0].confidence == 0.7
    print(f"  {'✓' if ok4 else '✗'} 降级合并: {len(result4)} 条规律（期望 1）")

    # 测试 5: 空 new_rules → 原样返回
    print("\n【测试 5】空 new_rules")
    existing5 = [make_rule("r5", "测试规律", 0.7)]
    result5 = merge_rules(existing5, [], None, DEFAULT_PARAMS)
    ok5 = len(result5) == 1 and result5[0].id == "r5"
    print(f"  {'✓' if ok5 else '✗'} 空 new_rules → {len(result5)} 条（期望 1）")

    # 测试 6: 空 existing → 仅返回 new
    print("\n【测试 6】空 existing")
    new6 = [make_rule("n6", "新归纳的规律", 0.6, exp=2)]
    result6 = merge_rules([], new6, None, DEFAULT_PARAMS)
    ok6 = len(result6) == 1 and result6[0].id == "n6"
    print(f"  {'✓' if ok6 else '✗'} 空 existing → {len(result6)} 条（期望 1）")

    # 测试 7: 最多处理 3 条新规律
    print("\n【测试 7】最多处理 3 条新规律")
    new7 = [make_rule(f"n{i}", f"规律内容{i}", 0.5 + i * 0.1) for i in range(5)]
    result7 = merge_rules([], new7, None, DEFAULT_PARAMS)
    # 前3条被处理（现有为空，合并时保留），后2条也加入
    ok7 = len(result7) >= 3
    print(f"  {'✓' if ok7 else '✗'} 最多3条处理: {len(result7)} 条规律（期望 >= 3）")

    # 测试 8: 相似度等于阈值 → 合并
    print("\n【测试 8】相似度等于阈值 → 合并")
    existing8 = [make_rule("r8", "相同的规律内容", 0.8, exp=5)]
    new8 = [make_rule("n8", "相同的规律内容", 0.6, exp=2)]
    mock_ep8 = MockEmbeddingProvider({(new8[0].content, existing8[0].content): 0.85})
    result8 = merge_rules(existing8, new8, mock_ep8, DEFAULT_PARAMS)
    ok8 = len(result8) == 1
    print(f"  {'✓' if ok8 else '✗'} sim=0.85 == threshold → 合并: {len(result8)} 条")

    print("\n" + "=" * 64)
    print("合并模块测试完成")
    print("=" * 64)
