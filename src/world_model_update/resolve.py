"""
resolve.py — stress 生命周期：can_resolve 判断 surprise 是否被规则覆盖

surprise 的来路：
    预测误差高（_last_prediction_error > 0.3）时产生 surprise
    surprise["prediction_error"] 记录了误差大小
    误差方向（正→低估，负→高估）隐含了上下文信息

can_resolve 逻辑：
    遍历当前 wm_rules 中所有 status="active" 且 confidence >= 0.6 的规则
    检查规则是否覆盖了"当前行为上下文"
    覆盖判定：
        - 规则的 context 字段与当前状态上下文匹配（高 stress / 高 loneliness / etc.）
        - 或规则的 predicts.expect 与当前 stress 变化方向一致
    若有匹配规则 → surprise 被世界模型吸收 → can_resolve = True
    若无匹配规则 → 无法解释 → can_resolve = False

mark_unresolvable 逻辑：
    某 surprise 被连续 MAX_ATTEMPTS 次评估为不可解决
    → 从队列移除
    → 写入一条 episode 记录："这件事我始终没想通"
    → 这是她来路的一部分
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from .defaults import get_param, DEFAULT_PARAMS

# 最大尝试次数（5次评估仍无法解释 → 标记为 UNRESOLVABLE）
DEFAULT_MAX_ATTEMPTS = 5

# 置信度阈值（规则需要达到此置信度才认为可以解释 surprise）
DEFAULT_CONFIDENCE_THRESHOLD = 0.6

# 状态字段名称（从 state_snapshot 中读取）
STATE_FIELDS = {
    "stress", "energy", "loneliness", "unresolved", "fatigue",
    "boredom", "info_gap", "somatic_tone", "approach_drive", "avoid_drive",
}


def _infer_context(prediction_error: float) -> Dict[str, Any]:
    """
    从 prediction_error 推断当前行为上下文。

    prediction_error > 0 → 低估（实际比预期差）→ 高 stress / 低 energy
    prediction_error < 0 → 高估（实际比预期好）→ 低 stress / 正面 somatic_tone

    返回：
        dict，描述当前上下文特征（供规则匹配使用）
    """
    return {
        "error_magnitude": abs(prediction_error),
        "error_direction": "underestimate" if prediction_error > 0 else "overestimate",
        "is_high_stress": prediction_error > 0.4,
        "is_surprise": abs(prediction_error) > 0.3,
    }


def _rule_covers_context(
    rule: Dict[str, Any],
    context: Dict[str, Any],
    current_state: Optional[Dict[str, float]] = None,
) -> bool:
    """
    判断某条规则是否覆盖当前上下文。

    匹配策略（按优先级）：
        1. context 字段精确匹配：规则注明"高 stress"且当前 is_high_stress
        2. error_direction 匹配：规则的 expect 方向与 error_direction 对应
        3. 状态字段范围匹配：当前某状态字段落在规则的 context 范围内

    参数：
        rule          : 规则字典（来自 wm_rules）
        context       : _infer_context() 的输出
        current_state : 当前状态快照（可选，用于更精确的匹配）

    返回：
        True = 规则覆盖该上下文
    """
    rule_context = str(rule.get("context", "")).lower()

    # ---- 1. 上下文标签匹配 ----
    if context.get("is_high_stress") and "stress" in rule_context:
        return True
    if context.get("is_surprise") and ("意外" in rule.get("content", "") or "unexpect" in rule_context):
        return True

    # ---- 2. expect 方向匹配 ----
    expect = str(rule.get("predicts", {}).get("expect", "")).lower()
    error_dir = context.get("error_direction", "")

    if error_dir == "underestimate":
        # 低估：预期好但实际差 → stress 上升 / energy 下降
        if "stress_increase" in expect or "energy_decrease" in expect:
            return True
    elif error_dir == "overestimate":
        # 高估：预期差但实际好 → stress 下降 / energy 上升
        if "stress_decrease" in expect or "energy_increase" in expect:
            return True

    # ---- 3. current_state 字段范围匹配 ----
    if current_state and rule_context:
        # 尝试从 context 字符串中解析字段范围
        # 格式如 "high_energy", "low_stress", "loneliness_gt_0.5"
        for field in STATE_FIELDS:
            val = current_state.get(field, None)
            if val is None:
                continue

            field_lower = field.lower()
            if f"{field_lower}_gt" in rule_context or f"{field_lower}_high" in rule_context:
                threshold_str = rule_context.split(f"{field_lower}_gt_")[-1].split()[0]
                try:
                    threshold = float(threshold_str)
                    if val > threshold:
                        return True
                except ValueError:
                    pass
            elif f"{field_lower}_lt" in rule_context or f"{field_lower}_low" in rule_context:
                threshold_str = rule_context.split(f"{field_lower}_lt_")[-1].split()[0]
                try:
                    threshold = float(threshold_str)
                    if val < threshold:
                        return True
                except ValueError:
                    pass

    return False


def can_resolve(
    surprise: Dict[str, Any],
    wm_rules: List[Dict[str, Any]],
    current_state: Optional[Dict[str, float]] = None,
    param_snapshot: Any = None,
) -> bool:
    """
    判断当前 surprise 是否可以被世界模型规则解释/吸收。

    判断逻辑：
        若存在至少一条 active 规则，其 context 覆盖当前 surprise 的上下文
        且该规则的 confidence >= 阈值
        → surprise 被世界模型已有知识覆盖 → 可以解释 → True

        若所有 active 规则都不覆盖当前上下文
        → surprise 是新知识/无法解释 → False

    参数：
        surprise       : surprise 字典 {"magnitude", "created_at", "prediction_error"}
        wm_rules      : 当前世界模型规律列表（来自 entity.wm_rules）
        current_state  : 当前状态快照（可选）
        param_snapshot : 参数快照（可选，用于读取阈值）

    返回：
        True  = surprise 可以被解释（被某条规则覆盖）
        False = surprise 无法被解释（需要继续处理或标记为 UNRESOLVABLE）
    """
    if not wm_rules:
        return False

    if not surprise or not isinstance(surprise, dict):
        return False

    prediction_error = float(surprise.get("prediction_error", 0.0))
    context = _infer_context(prediction_error)

    confidence_threshold = float(get_param(
        param_snapshot,
        "resolve.confidence_threshold",
        DEFAULT_CONFIDENCE_THRESHOLD,
    ))

    # ---- 遍历所有 active 规则，寻找覆盖当前上下文的规则 ----
    for rule in wm_rules:
        status = str(rule.get("status", "active")).lower()
        if status != "active":
            continue

        confidence = float(rule.get("confidence", 0.0))
        if confidence < confidence_threshold:
            continue

        # 检查规则是否覆盖上下文
        if _rule_covers_context(rule, context, current_state):
            return True

    return False


def mark_unresolvable(
    surprise: Dict[str, Any],
    attempts: int,
    param_snapshot: Any = None,
) -> tuple[bool, Optional[Dict[str, Any]]]:
    """
    判断 surprise 是否超过最大尝试次数，决定是否标记为 UNRESOLVABLE。

    参数：
        surprise : surprise 字典
        attempts : 该 surprise 已尝试解决的次数
        param_snapshot : 参数快照

    返回：
        (should_remove, episode_to_write)
        should_remove     = True  → 从队列移除并写入 episode
        episode_to_write   : 写入 episode 所需的记录 dict
                            = None  → 尚未超限，不写入
    """
    max_attempts = int(get_param(
        param_snapshot,
        "resolve.max_attempts",
        DEFAULT_MAX_ATTEMPTS,
    ))

    if attempts < max_attempts:
        return False, None

    # ---- 超限：生成不可解决的 episode 记录 ----
    created_at = float(surprise.get("created_at", time.time()))
    magnitude = float(surprise.get("magnitude", 0.0))
    prediction_error = float(surprise.get("prediction_error", 0.0))

    episode = {
        "type": "unresolvable_surprise",
        "created_at": created_at,
        "magnitude": magnitude,
        "prediction_error": prediction_error,
        "resolved_at": time.time(),
        "attempts": attempts,
        # 这是她来路的一部分：始终没想通的事
        "reflection": "这件事我始终没想通，但它已经成了我的一部分。",
    }

    return True, episode


def attempt_resolve(
    surprise: Dict[str, Any],
    wm_rules: List[Dict[str, Any]],
    current_state: Optional[Dict[str, float]] = None,
    param_snapshot: Any = None,
) -> tuple[bool, bool, Optional[Dict[str, Any]]]:
    """
    完整的一次 surprise 解决尝试。

    参数：
        surprise       : surprise 字典
        wm_rules      : 当前世界模型规律列表
        current_state  : 当前状态快照
        param_snapshot : 参数快照

    返回：
        (resolved, should_remove, episode_to_write)
        resolved        : True = surprise 被规则覆盖，可以解释
        should_remove   : True = 已超限，应从队列移除
        episode_to_write: 写入 episode 所需的记录 dict（仅当 should_remove=True 时非 None）
    """
    resolved = can_resolve(surprise, wm_rules, current_state, param_snapshot)

    if resolved:
        # surprise 被规则覆盖，不需要写 episode
        return True, False, None

    # 无法解决：检查是否超限
    attempts = int(surprise.get("_attempts", 0)) + 1
    surprise["_attempts"] = attempts

    should_remove, episode = mark_unresolvable(
        surprise, attempts, param_snapshot
    )

    return False, should_remove, episode
