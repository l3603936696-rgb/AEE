"""
Induction Module (归纳模块) — v11.2 预测误差驱动

从实体的亲身经历快照和逐字段预测误差中学习因果规律。

核心约束（绝对禁止）：
    - 禁止使用硬编码的反事实模板
    - 禁止硬编码动作标签
    - 所有 trigger / expect / content 均自动生成
    - 纯函数，不写文件，不写数据库

算法（v11.2 预测误差驱动）：
    对每个快照中存储的 prediction_error_map（逐字段预测误差）：
    - |error| > threshold → 该字段的预测与实际不符
    - 已有匹配规则 → EMA 更新 expected_deltas，调整 confidence
    - 无匹配规则 → 创建新规则（confidence=0.3 起步）
    冷启动：无规则时预测=0，任何|actual|>threshold 触发规则创建

v11.1 旧版（反事实对比法）已移除——方法论存在四个结构性缺陷：
    1. 对照组混入了不同动作的效果
    2. 动作选择偏差使 pre_state 差异被误读为因果
    3. 10样本 × 0.03 阈值=噪声放大器
    4. 上下文维度与状态字段循环
"""

import uuid
import time
import math
from typing import Any, Dict, List, Optional, Set

from .defaults import (
    get_raw_value,
    STATE_FIELD_WHITELIST,
    ACTION_TYPE_WHITELIST,
    CONTEXT_DIMENSIONS,
)
from .rules import Rule, Snap, Predicts


# ============================================================================
# 辅助函数
# ============================================================================

def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _extract_state(state: Any) -> Dict[str, float]:
    """安全提取状态向量，仅保留白名单字段"""
    if not isinstance(state, dict):
        return {}
    return {
        k: _safe_float(v)
        for k, v in state.items()
        if k in STATE_FIELD_WHITELIST
    }


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


def _infer_context_label(pre_state: Dict[str, float]) -> str:
    """从 pre_state 推断上下文标签，用于 trigger 生成"""
    parts = []
    for dim in CONTEXT_DIMENSIONS:
        val = pre_state.get(dim, 0.5)
        direction = "高" if val >= 0.5 else "低"
        parts.append(f"{dim}{direction}")
    return "_".join(parts)


def _generate_trigger(action_type: str, context_label: str) -> str:
    """自动生成 trigger 字段"""
    action = action_type.strip().lower()
    ctx = context_label.strip().lower()
    return f"action_{action}_in_{ctx}"


def _generate_expect_from_deltas(
    deltas: Dict[str, float],
    fields: List[str],
) -> str:
    """从预期变化生成 expect 字符串"""
    parts = []
    for f in fields:
        d = deltas.get(f, 0.0)
        if abs(d) < 0.005:
            parts.append(f"{f}_stable")
        elif d > 0:
            parts.append(f"{f}_increase")
        else:
            parts.append(f"{f}_decrease")
    return "+".join(parts) if parts else "stable"


def _generate_content_from_deltas(
    action_type: str,
    context_label: str,
    deltas: Dict[str, float],
    fields: List[str],
) -> str:
    """从预期变化生成 content 描述文本"""
    action = action_type.strip()
    ctx = context_label.strip()
    field_descs = []
    for f in fields:
        d = deltas.get(f, 0.0)
        if d > 0:
            field_descs.append(f"{f}↑{d:.3f}")
        elif d < 0:
            field_descs.append(f"{f}↓{abs(d):.3f}")
        else:
            field_descs.append(f"{f}→0")
    return f"{ctx}时{action}→{','.join(field_descs)}"


# ============================================================================
# 预测函数（供管线调用）
# ============================================================================

def predict_action_effects(
    action_type: str,
    pre_state: Dict[str, float],
    wm_rules: List[Any],
) -> Dict[str, float]:
    """
    预测执行 action_type 后各状态字段的变化量。

    匹配所有 trigger 包含此 action_type 的 active 规则，
    按 confidence 加权平均 expected_deltas。

    参数：
        action_type : 即将执行的动作类型
        pre_state   : 执行前的状态向量
        wm_rules    : 当前世界模型规则列表

    返回：
        Dict[str, float] — 逐字段预测变化量。
        无匹配规则 → 返回 {}（等效预测"不变"）
    """
    if not action_type or not wm_rules:
        return {}

    action = action_type.strip().lower()
    matching: List[Rule] = []

    for r in wm_rules:
        rule = r
        if isinstance(r, dict):
            rule = Rule.from_dict(r)
        if not isinstance(rule, Rule):
            continue
        if rule.status != "active":
            continue
        if rule.confidence < 0.1:
            continue
        if action not in rule.predicts.trigger:
            continue
        matching.append(rule)

    if not matching:
        return {}

    total_weight = sum(r.confidence for r in matching)
    if total_weight <= 0:
        return {}

    # 收集所有规则涉及的字段
    all_fields: Set[str] = set()
    for r in matching:
        all_fields.update(r.expected_deltas.keys())

    prediction: Dict[str, float] = {}
    for field in all_fields:
        weighted_sum = sum(
            r.expected_deltas.get(field, 0.0) * r.confidence
            for r in matching
        )
        prediction[field] = round(weighted_sum / total_weight, 5)

    return prediction


# ============================================================================
# 主入口：induct_rules（v11.2 预测误差驱动）
# ============================================================================

def induct_rules(
    old_rules: List[Any],
    snaps: List[Any],
    param_snapshot: Any,
) -> List[Rule]:
    """
    归纳模块主入口 — 预测误差驱动学习。

    对每个快照的 prediction_error_map：
        - 逐字段检查 |error| > threshold
        - 已有匹配规则 → EMA 更新 expected_deltas，调 confidence
        - 无匹配规则 → 创建新规则（confidence=0.3）

    参数：
        old_rules       : 当前已有规律列表（用于匹配更新 + 去重）
        snaps           : 经验快照列表（Snap 或 dict）
        param_snapshot  : 参数只读快照（来自 parameter_system）

    返回：
        List[Rule] — 新创建的规律列表（旧规则在 old_rules 中被原地更新）
    """
    try:
        # ---- 参数读取 ----
        error_threshold = get_raw_value(
            param_snapshot,
            "world_model.prediction_error_threshold",
            0.02,
        )
        ema_alpha = get_raw_value(
            param_snapshot,
            "world_model.prediction_ema_alpha",
            0.3,
        )
        max_new = max(1, int(get_raw_value(
            param_snapshot,
            "world_model.induction_max_new_rules_per_cycle",
            3,
        )))

        # ---- 快照安全化 ----
        safe_snaps = _safe_snaps(snaps)
        if len(safe_snaps) < 1:
            return []

        # ---- 建立老规则索引（trigger → Rule 对象）----
        old_by_trigger: Dict[str, Rule] = {}
        if old_rules:
            for r in old_rules:
                rule = r
                if isinstance(r, dict):
                    rule = Rule.from_dict(r)
                if isinstance(rule, Rule) and rule.predicts.trigger:
                    old_by_trigger[rule.predicts.trigger] = rule

        new_rules: List[Rule] = []
        # 跟踪本轮新创建的 trigger（防止同一 cycle 内重复创建）
        new_triggers: Set[str] = set()

        for snap in safe_snaps:
            action = snap.action_type.strip().lower()
            if action not in ACTION_TYPE_WHITELIST:
                continue

            # ---- 读取逐字段预测误差 ----
            pred_error = _get_prediction_error_map(snap)
            if not pred_error:
                # 旧格式 snap（无 prediction_error_map）→ 跳过
                continue

            # ---- 计算实际 delta ----
            pre = _extract_state(snap.pre_state)
            post = _extract_state(snap.post_state)
            actual_deltas = {
                f: post.get(f, 0.0) - pre.get(f, 0.0)
                for f in STATE_FIELD_WHITELIST
            }

            # ---- 找显著预测误差的字段 ----
            significant = [
                f for f, err in pred_error.items()
                if abs(err) > error_threshold
            ]
            if not significant:
                continue

            # ---- 上下文推断 + trigger 生成 ----
            context_label = _infer_context_label(snap.pre_state)
            trigger = _generate_trigger(action, context_label)

            # ---- 匹配已有规则 ----
            existing = old_by_trigger.get(trigger) or (
                trigger in new_triggers and _find_in_new(new_rules, trigger)
            )

            if existing:
                # ====== 更新已有规则 ======
                for f in significant:
                    old_val = existing.expected_deltas.get(f, 0.0)
                    existing.expected_deltas[f] = round(
                        old_val * (1 - ema_alpha) + actual_deltas[f] * ema_alpha,
                        5,
                    )

                # 更新 expect / content 字符串
                all_fields = list(existing.expected_deltas.keys())
                existing.predicts.expect = _generate_expect_from_deltas(
                    existing.expected_deltas, all_fields
                )
                existing.content = _generate_content_from_deltas(
                    action, context_label, existing.expected_deltas, all_fields
                )

                # confidence 调整：误差大→学到东西（微升），误差小→预测准（升更多）
                avg_abs_error = sum(
                    abs(pred_error.get(f, 0.0)) for f in significant
                ) / len(significant)
                # normalized_error: 0=完美预测, 1=完全离谱（以0.1为"离谱"基线）
                norm_err = min(avg_abs_error / 0.1, 1.0)
                # 误差大：+0.02（学到新东西），误差小：+0.08（预测准）
                boost = 0.02 + 0.06 * (1.0 - norm_err)
                existing.confidence = round(
                    min(0.95, existing.confidence + boost), 4
                )
                existing.last_verified_at = time.time()
                existing.source_experience_count += 1

            else:
                # ====== 创建新规则 ======
                if len(new_rules) >= max_new:
                    break

                expect = _generate_expect_from_deltas(actual_deltas, significant)
                content = _generate_content_from_deltas(
                    action, context_label, actual_deltas, significant
                )

                now = time.time()
                rule = Rule(
                    id=f"wmu_{uuid.uuid4().hex[:8]}",
                    content=content,
                    confidence=0.3,  # 新规则低信心起步
                    source_experience_count=1,
                    stability_score=0.3,
                    stability_band=0.1,
                    created_at=now,
                    last_verified_at=now,
                    last_decay_at=now,
                    status="active",
                    context=context_label,
                    predicts=Predicts(trigger=trigger, expect=expect),
                    expected_deltas={
                        f: round(actual_deltas[f], 5) for f in significant
                    },
                    evidence=[],
                    _debug_meta={
                        "induction_method": "prediction_error_driven",
                        "prediction_error_fields": significant,
                        "avg_abs_error": round(
                            sum(abs(pred_error.get(f, 0.0)) for f in significant)
                            / len(significant), 4
                        ),
                    },
                )
                new_rules.append(rule)
                new_triggers.add(trigger)

        return new_rules

    except Exception:
        return []


def _get_prediction_error_map(snap: Snap) -> Optional[Dict[str, float]]:
    """从 Snap 中安全提取 prediction_error_map"""
    # Snap dataclass 字段
    pe_map = getattr(snap, "prediction_error_map", None)
    if pe_map and isinstance(pe_map, dict):
        return {str(k): float(v) for k, v in pe_map.items()}

    # dict 格式 snap
    if isinstance(snap, dict):
        pe_map = snap.get("prediction_error_map")
        if pe_map and isinstance(pe_map, dict):
            return {str(k): float(v) for k, v in pe_map.items()}

    return None


def _find_in_new(new_rules: List[Rule], trigger: str) -> Optional[Rule]:
    """在本轮新创建的规则中查找"""
    for r in new_rules:
        if r.predicts.trigger == trigger:
            return r
    return None


# ============================================================================
# 测试入口
# ============================================================================

if __name__ == "__main__":
    print("=" * 64)
    print("归纳模块测试 — v11.2 预测误差驱动")
    print("=" * 64)

    from .defaults import DEFAULT_PARAMS

    now = time.time()

    def make_snap_with_pred_error(
        idx: int,
        action: str,
        pre_energy: float,
        pre_info_gap: float,
        info_gap_delta: float,
        pred_error_gap: float,
    ) -> Snap:
        snap = Snap(
            snap_index=idx,
            timestamp=now + idx,
            action_type=action,
            target="none",
            priority=0.5,
            pre_state={"energy": pre_energy, "info_gap": pre_info_gap, "loneliness": 0.3},
            post_state={
                "energy": pre_energy - 0.02,
                "info_gap": pre_info_gap + info_gap_delta,
                "loneliness": 0.31,
            },
        )
        # 注入 prediction_error_map（模拟管线中写入的）
        snap.prediction_error_map = {
            "info_gap": pred_error_gap,
            "energy": -0.01,
            "loneliness": 0.005,
        }
        return snap

    # ====== 测试 1：冷启动，无规则，预测=0 → error=actual → 创建规则 ======
    print("\n【测试 1】冷启动：预测=0，|actual| > threshold → 创建规则")
    snaps_cold = [
        make_snap_with_pred_error(0, "seek", 0.8, 0.7, -0.08, -0.08),
        make_snap_with_pred_error(1, "seek", 0.8, 0.6, -0.07, -0.07),
    ]
    new_rules = induct_rules([], snaps_cold, DEFAULT_PARAMS)
    ok1 = len(new_rules) > 0
    print(f"  {'✓' if ok1 else '✗'} 生成规则数: {len(new_rules)}（期望 ≥1）")
    for r in new_rules:
        print(f"    [{r.id}] trigger={r.predicts.trigger}")
        print(f"      expect={r.predicts.expect}")
        print(f"      deltas={r.expected_deltas}")
        print(f"      confidence={r.confidence}")

    # ====== 测试 2：已有规则，EMA 更新 ======
    print("\n【测试 2】已有规则，EMA 更新 expected_deltas")
    if new_rules:
        old_rule = new_rules[0]
        old_info_gap = old_rule.expected_deltas.get("info_gap", 0.0)
        old_conf = old_rule.confidence

        # 新一轮快照，info_gap 变化不同了
        snaps_update = [
            make_snap_with_pred_error(2, "seek", 0.8, 0.7, -0.05, -0.03),
        ]
        induct_rules([old_rule], snaps_update, DEFAULT_PARAMS)
        new_info_gap = old_rule.expected_deltas.get("info_gap", 0.0)
        new_conf = old_rule.confidence

        # EMA: 0.7 * 旧值 + 0.3 * 新值
        expected_ema = round(old_info_gap * 0.7 + (-0.05) * 0.3, 5)
        ok2a = abs(new_info_gap - expected_ema) < 0.001
        ok2b = new_conf > old_conf  # confidence 应上升
        print(f"  {'✓' if ok2a else '✗'} EMA 更新: {old_info_gap} → {new_info_gap}（期望 ≈{expected_ema}）")
        print(f"  {'✓' if ok2b else '✗'} confidence: {old_conf} → {new_conf}（期望上升）")

    # ====== 测试 3：误差小于阈值 → 不触发 ======
    print("\n【测试 3】|error| < threshold → 不创建规则")
    snaps_tiny = [
        make_snap_with_pred_error(3, "seek", 0.8, 0.7, -0.01, -0.005),
    ]
    result_tiny = induct_rules([], snaps_tiny, DEFAULT_PARAMS)
    ok3 = len(result_tiny) == 0
    print(f"  {'✓' if ok3 else '✗'} 生成规则数: {len(result_tiny)}（期望 0）")

    # ====== 测试 4：空快照 ======
    print("\n【测试 4】空快照列表")
    result_empty = induct_rules([], [], DEFAULT_PARAMS)
    ok4 = len(result_empty) == 0
    print(f"  {'✓' if ok4 else '✗'} 生成规则数: {len(result_empty)}（期望 0）")

    # ====== 测试 5：predict_action_effects ======
    print("\n【测试 5】predict_action_effects")
    test_rules = [
        Rule(
            id="test_seek",
            content="高能量时seek降低info_gap",
            confidence=0.7,
            status="active",
            context="energy高_info_gap高",
            predicts=Predicts(
                trigger="action_seek_in_energy高_info_gap高",
                expect="info_gap_decrease",
            ),
            expected_deltas={"info_gap": -0.06, "energy": -0.02},
        ),
    ]
    pred = predict_action_effects(
        "seek",
        {"energy": 0.8, "info_gap": 0.7},
        test_rules,
    )
    ok5a = abs(pred.get("info_gap", 0) + 0.06) < 0.001
    ok5b = abs(pred.get("energy", 0) + 0.02) < 0.001
    print(f"  {'✓' if ok5a else '✗'} info_gap 预测: {pred.get('info_gap')}（期望 -0.06）")
    print(f"  {'✓' if ok5b else '✗'} energy 预测: {pred.get('energy')}（期望 -0.02）")

    # 无匹配规则 → 空预测
    pred_none = predict_action_effects("avoid", {"energy": 0.5}, test_rules)
    ok5c = len(pred_none) == 0
    print(f"  {'✓' if ok5c else '✗'} 无匹配规则 → 空预测: {pred_none}")

    print("\n" + "=" * 64)
    print("induct.py v11.2 测试完成")
    print("=" * 64)
