"""
输入触发归纳（「输入→后果」规则） — PLAN_learn_from_outside §2b

镜像 induct.py 的预测误差驱动逻辑，但学的是「某类输入到达 → 状态如何变」，
而非「我做某动作 → 状态如何变」。这是认知通道的燃料源：对话/阅读能回答的
规则，必须由外部输入触发，才能被「问→答→不确定性下降」的认知信用强化。

与 induct.py 的差异（仅三处，其余复用其纯函数辅助）：
    1. 门：按 snap.input_class != "" 进入（而非 ACTION_TYPE_WHITELIST）。
    2. trigger = f"input_{input_class}_in_{ctx}"（而非 action_{action}_in_{ctx}）。
    3. **top-K 收窄**：只保留 |delta| 最大的 K 个字段，避免重蹈 action 规则
       12 维合取、永远证不了、confidence 冻在地板的覆辙。

约束（同 induct.py）：
    - 纯函数，不写文件 / 数据库。
    - action 规则路径零改动（本模块是纯新增旁路）。
"""

import uuid
import time
from typing import Any, Dict, List, Set

from .defaults import get_raw_value
from .rules import Rule, Snap, Predicts
from .induct import (
    _safe_snaps,
    _infer_context_label,
    _generate_expect_from_deltas,
    _generate_content_from_deltas,
    _get_prediction_error_map,
    _find_in_new,
)

# ── 常量（来源标注）──
# input 规则字段宽度上限：只留 |delta| 最大的 K 个，收窄合取。
# **K=1（§6 标定后定值，非种子）**：verify._verify_single_rule 用 rsplit("_",1) 只解析
# 单字段 expect（"{field}_{direction}"）。多字段 expect（"a_decrease+b_decrease"）会被
# 解析成不存在的字段名 → delta_val 恒 0 → 每拍判失败 → confidence 只降不升（这正是
# action 12 维规则冻在地板 0.05 的底层机制）。故 input 规则取单一最显著后果，才能被
# 现有 verify 正确兑现、confidence 真正爬升。加宽 K 须先改 verify（§8 红线，另议）。
_K_INPUT_FIELDS = 1


def _generate_input_trigger(input_class: str, context_label: str) -> str:
    """自动生成 input 触发字段。"""
    cls = input_class.strip().lower()
    ctx = context_label.strip().lower()
    return f"input_{cls}_in_{ctx}"


def induct_input_rules(
    old_rules: List[Any],
    snaps: List[Any],
    param_snapshot: Any,
) -> List[Rule]:
    """
    输入触发归纳主入口。结构镜像 induct.induct_rules，仅处理带 input_class 的快照。

    返回新创建的 input 规则列表（旧 input 规则在 old_rules 中被原地更新）。
    """
    try:
        error_threshold = get_raw_value(
            param_snapshot, "world_model.prediction_error_threshold", 0.02,
        )
        ema_alpha = get_raw_value(
            param_snapshot, "world_model.prediction_ema_alpha", 0.3,
        )
        max_new = max(1, int(get_raw_value(
            param_snapshot, "world_model.induction_max_new_rules_per_cycle", 3,
        )))

        safe_snaps = _safe_snaps(snaps)
        if len(safe_snaps) < 1:
            return []

        # ---- 老规则索引（trigger → Rule）----
        old_by_trigger: Dict[str, Rule] = {}
        if old_rules:
            for r in old_rules:
                rule = Rule.from_dict(r) if isinstance(r, dict) else r
                if isinstance(rule, Rule) and rule.predicts.trigger:
                    old_by_trigger[rule.predicts.trigger] = rule

        new_rules: List[Rule] = []
        new_triggers: Set[str] = set()

        for snap in safe_snaps:
            input_class = getattr(snap, "input_class", "") or ""
            # 门：非输入触发快照（input_class=""）→ 跳过，留给 induct.py 的 action 路径
            if not input_class:
                continue

            pred_error = _get_prediction_error_map(snap)
            if not pred_error:
                continue

            pre = snap.pre_state if isinstance(snap.pre_state, dict) else {}
            post = snap.post_state if isinstance(snap.post_state, dict) else {}
            all_fields = set(pre.keys()) | set(post.keys())
            actual_deltas: Dict[str, float] = {}
            for f in all_fields:
                try:
                    actual_deltas[f] = float(post.get(f, 0.0)) - float(pre.get(f, 0.0))
                except (TypeError, ValueError):
                    pass

            significant = [
                f for f, err in pred_error.items() if abs(err) > error_threshold
            ]
            if not significant:
                continue

            # ---- top-K 收窄：只留 |delta| 最大的 K 个字段 ----
            significant = sorted(
                significant,
                key=lambda f: abs(actual_deltas.get(f, 0.0)),
                reverse=True,
            )[:_K_INPUT_FIELDS]

            context_label = _infer_context_label(pre)
            trigger = _generate_input_trigger(input_class, context_label)
            content_label = f"输入·{input_class}"

            existing = old_by_trigger.get(trigger) or (
                trigger in new_triggers and _find_in_new(new_rules, trigger)
            )

            if existing:
                for f in significant:
                    old_val = existing.expected_deltas.get(f, 0.0)
                    existing.expected_deltas[f] = round(
                        old_val * (1 - ema_alpha) + actual_deltas[f] * ema_alpha, 5,
                    )
                all_keys = list(existing.expected_deltas.keys())
                existing.predicts.expect = _generate_expect_from_deltas(
                    existing.expected_deltas, all_keys
                )
                existing.content = _generate_content_from_deltas(
                    content_label, context_label, existing.expected_deltas, all_keys
                )
                avg_abs_error = sum(
                    abs(pred_error.get(f, 0.0)) for f in significant
                ) / len(significant)
                norm_err = min(avg_abs_error / 0.1, 1.0)
                boost = 0.02 + 0.06 * (1.0 - norm_err)
                existing.confidence = round(min(0.95, existing.confidence + boost), 4)
                existing.last_verified_at = time.time()
                existing.source_experience_count += 1
            else:
                if len(new_rules) >= max_new:
                    break
                expect = _generate_expect_from_deltas(actual_deltas, significant)
                content = _generate_content_from_deltas(
                    content_label, context_label, actual_deltas, significant
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
                        f: round(actual_deltas[f], 5) for f in significant
                    },
                    evidence=[],
                    _debug_meta={
                        "induction_method": "input_prediction_error_driven",
                        "input_class": input_class,
                        "prediction_error_fields": significant,
                    },
                )
                new_rules.append(rule)
                new_triggers.add(trigger)

        return new_rules

    except Exception:
        return []
