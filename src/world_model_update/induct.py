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

子模块：
    induct_helpers.py — 辅助函数（生成器、剪枝、格式转换）
    induct_test.py    — 测试入口
"""

import uuid
import time
from typing import Any, Dict, List, Optional, Set

from .defaults import (
    get_raw_value,
    STATE_FIELD_WHITELIST,
    ACTION_TYPE_WHITELIST,
    CONTEXT_DIMENSIONS,
)
from .rules import Rule, Snap, Predicts
from .induct_helpers import (
    _safe_float,
    _salient_fields,
    _generate_trigger,
    _generate_expect_from_deltas,
    _generate_content_from_deltas,
    _infer_context_label,
    _get_prediction_error_map,
)


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


def _extract_state(state: Any) -> Dict[str, float]:
    """安全提取状态向量，仅保留白名单字段"""
    if not isinstance(state, dict):
        return {}
    return {
        k: _safe_float(v)
        for k, v in state.items()
        if k in STATE_FIELD_WHITELIST
    }


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


def _find_in_new(new_rules: List[Rule], trigger: str) -> Optional[Rule]:
    """在本轮新创建的规则中查找"""
    for r in new_rules:
        if r.predicts.trigger == trigger:
            return r
    return None


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
        salience_ratio = get_raw_value(
            param_snapshot,
            "world_model.induction_salience_ratio",
            0.3,
        )
        max_new = max(1, int(get_raw_value(
            param_snapshot,
            "world_model.induction_max_new_rules_per_cycle",
            3,
        )))

        safe_snaps = _safe_snaps(snaps)
        if len(safe_snaps) < 1:
            return []

        old_by_trigger: Dict[str, Rule] = {}
        if old_rules:
            for r in old_rules:
                rule = r
                if isinstance(r, dict):
                    rule = Rule.from_dict(r)
                if isinstance(rule, Rule) and rule.predicts.trigger:
                    old_by_trigger[rule.predicts.trigger] = rule

        new_rules: List[Rule] = []
        new_triggers: Set[str] = set()

        for snap in safe_snaps:
            action = snap.action_type.strip().lower()
            if action not in ACTION_TYPE_WHITELIST:
                continue

            pred_error = _get_prediction_error_map(snap)
            if not pred_error:
                continue

            pre = snap.pre_state if isinstance(snap.pre_state, dict) else {}
            post = snap.post_state if isinstance(snap.post_state, dict) else {}
            all_fields = set(pre.keys()) | set(post.keys())
            actual_deltas = {}
            for f in all_fields:
                try:
                    actual_deltas[f] = float(post.get(f, 0.0)) - float(pre.get(f, 0.0))
                except (TypeError, ValueError):
                    pass

            significant = [
                f for f, err in pred_error.items()
                if abs(err) > error_threshold
            ]
            if not significant:
                continue

            context_label = _infer_context_label(snap.pre_state, CONTEXT_DIMENSIONS)
            trigger = _generate_trigger(action, context_label)

            existing = old_by_trigger.get(trigger) or (
                trigger in new_triggers and _find_in_new(new_rules, trigger)
            )

            if existing:
                for f in significant:
                    old_val = existing.expected_deltas.get(f, 0.0)
                    existing.expected_deltas[f] = round(
                        old_val * (1 - ema_alpha) + actual_deltas[f] * ema_alpha,
                        5,
                    )

                kept_fields = _salient_fields(
                    existing.expected_deltas,
                    list(existing.expected_deltas.keys()),
                    salience_ratio,
                )
                existing.expected_deltas = {
                    f: existing.expected_deltas[f] for f in kept_fields
                }

                all_fields = list(existing.expected_deltas.keys())
                existing.predicts.expect = _generate_expect_from_deltas(
                    existing.expected_deltas, all_fields
                )
                existing.content = _generate_content_from_deltas(
                    action, context_label, existing.expected_deltas, all_fields
                )

                avg_abs_error = sum(
                    abs(pred_error.get(f, 0.0)) for f in significant
                ) / len(significant)
                norm_err = min(avg_abs_error / 0.1, 1.0)
                boost = 0.02 + 0.06 * (1.0 - norm_err)
                existing.confidence = round(
                    min(0.95, existing.confidence + boost), 4
                )
                existing.last_verified_at = time.time()
                existing.source_experience_count += 1

            else:
                if len(new_rules) >= max_new:
                    break

                salient = _salient_fields(actual_deltas, significant, salience_ratio)

                expect = _generate_expect_from_deltas(actual_deltas, salient)
                content = _generate_content_from_deltas(
                    action, context_label, actual_deltas, salient
                )

                now = time.time()
                rule = Rule(
                    id=f"wmu_{uuid.uuid4().hex[:8]}",
                    content=content,
                    confidence=0.3,
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
                        f: round(actual_deltas[f], 5) for f in salient
                    },
                    evidence=[],
                    _debug_meta={
                        "induction_method": "prediction_error_driven",
                        "prediction_error_fields": salient,
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


__all__ = [
    "induct_rules",
    "predict_action_effects",
]
