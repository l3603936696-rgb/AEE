"""
EmergentBehavior V5 — 涌现行为（原有逻辑）

此文件保留 V5 完整逻辑，仅供 V6 fallback 时调用。
不要在此文件内引入 V6 相关代码。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


try:
    from ..state_update import get_info_queue, compute_queue_trigger_rest
    _HAS_COMPUTE_LOAD = True
except Exception:
    _HAS_COMPUTE_LOAD = False


# ============================================================================
# 驱动力计算（V5 独立版）
# ============================================================================

def compute_drive_vector(entity_core) -> Dict[str, float]:
    """从 EntityCore 连续状态映射需求压力 [0, 1]。"""
    somatic = getattr(entity_core, "somatic_tone", 0.0)
    pending = len(getattr(entity_core, "pending_failures", []))
    metabolite = getattr(entity_core, "failure_metabolite", 0.0)
    unresolved_val = getattr(entity_core, "unresolved", 0.2)

    return {
        # 代谢物直接抑制社交欲望——撞墙多了，再孤独也不想动
        "loneliness":        max(0.0, getattr(entity_core, "loneliness", 0.3) - metabolite * 0.6),
        "unresolved":        unresolved_val,
        "info_gap":          getattr(entity_core, "info_gap", 0.5),
        "fatigue":           min(1.0, getattr(entity_core, "fatigue", 0.1) + metabolite * 0.3),
        "danger":            getattr(entity_core, "danger_level", 0.0),
        "somatic_distress":  max(0.0, -somatic) + metabolite * 0.5,
        "repair":            min(1.0, pending / 3.0) * 0.6 + unresolved_val * 0.4,
    }


# ============================================================================
# 动作画像
# ============================================================================

ACTION_PROFILES: Dict[str, Dict[str, float]] = {
    "seek":    {"loneliness": 0.70, "unresolved": 0.10, "info_gap": 0.05, "fatigue": 0.0, "danger": 0.0, "somatic_distress": 0.10, "repair": 0.0},
    "explore": {"loneliness": 0.05, "unresolved": 0.10, "info_gap": 0.70, "fatigue": 0.0, "danger": 0.0, "somatic_distress": 0.05, "repair": 0.0},
    "repair":  {"loneliness": 0.0,  "unresolved": 0.40, "info_gap": 0.10, "fatigue": 0.0, "danger": 0.0, "somatic_distress": 0.15, "repair": 0.80},
    "comfort": {"loneliness": 0.10, "unresolved": 0.0,  "info_gap": 0.0,  "fatigue": 0.05,"danger": 0.10,"somatic_distress": 0.30, "repair": 0.0},
    "rest":    {"loneliness": 0.0,  "unresolved": 0.0,  "info_gap": 0.0,  "fatigue": 0.60,"danger": 0.05,"somatic_distress": 0.05, "repair": 0.0},
    "avoid":   {"loneliness": 0.0,  "unresolved": 0.0,  "info_gap": 0.0,  "fatigue": 0.0, "danger": 0.50,"somatic_distress": 0.0,  "repair": 0.0},
    "idle":    {"loneliness": 0.0,  "unresolved": 0.0,  "info_gap": 0.0,  "fatigue": 0.0, "danger": 0.0, "somatic_distress": 0.0,  "repair": 0.0},
}

PRIMARY_ACTION: Dict[str, str] = {
    "loneliness":        "seek",
    "unresolved":        "explore",
    "info_gap":          "explore",
    "fatigue":           "rest",
    "danger":            "avoid",
    "somatic_distress":  "comfort",
    "repair":            "repair",
}

ACTION_TARGETS: Dict[str, str] = {
    "seek": "social", "explore": "information", "repair": "failure",
    "comfort": "", "rest": "self", "avoid": "", "idle": "information",
}

ACTION_DOMINANTS: Dict[str, str] = {
    "seek": "loneliness", "explore": "info_gap", "repair": "repair_drive",
    "comfort": "somatic_distress", "rest": "fatigue",
    "avoid": "danger", "idle": "tension",
}


# ============================================================================
# 世界模型修复信心（两个版本共用）
# ============================================================================

def _get_wm_repair_confidence(entity_core) -> float:
    """从世界模型估算修复信心 [0, 1]。无阈值，纯连续。"""
    try:
        recent_types = entity_core.recent_failure_types()
    except Exception:
        return 0.0
    if not recent_types:
        return 0.0

    wm_rules = getattr(entity_core, "wm_rules", [])
    if not wm_rules:
        return 0.0

    matched_confidences = []
    for rule in wm_rules:
        if not isinstance(rule, dict):
            continue
        rule_text = str(rule.get("trigger", "")) + str(rule.get("expect", "")) + str(rule.get("content", ""))
        rule_text_lower = rule_text.lower()
        for err_type in recent_types:
            if err_type.lower() in rule_text_lower or "repair" in rule_text_lower or "fix" in rule_text_lower:
                conf = float(rule.get("confidence", 0.5))
                matched_confidences.append(conf)
                break
    if not matched_confidences:
        return 0.0
    return sum(matched_confidences) / len(matched_confidences)


# ============================================================================
# V5 fallback（当 V6 不可用时的完整备选逻辑）
# ============================================================================

@dataclass
class _V5EmergentResult:
    action_type: str
    target: str
    priority: float
    tension_level: float
    dominant_state: str
    state_snapshot: Dict[str, Any]
    suggested_tool: str


def compute_v5_fallback(entity_core, snap) -> _V5EmergentResult:
    """
    V5 原有逻辑的完整实现（当 V6 失败时调用）。

    特点：
        - 排序 argmax 选择动作（离散选择）
        - 代谢物硬路由（seek → comfort → rest）
        - 无 behavior_vector 输出
    """
    drives = compute_drive_vector(entity_core)
    energy = getattr(entity_core, "energy", 0.8)

    queue_pressure = 0.0
    if _HAS_COMPUTE_LOAD:
        try:
            q = get_info_queue()
            tick = getattr(entity_core, "tick_index", 0)
            q.accumulate(
                idle_seconds=60.0,
                loneliness=drives["loneliness"],
                unresolved=drives["unresolved"],
                somatic_tone=getattr(entity_core, "somatic_tone", 0.0),
                info_gap=drives["info_gap"],
                has_social_input=False,
                time_since_last_social=getattr(entity_core, "time_since_last_social", 60.0),
                time_since_last_info=getattr(entity_core, "time_since_last_info", 60.0),
                tick_index=tick,
            )
            if compute_queue_trigger_rest(
                info_queue=q, available_energy=energy,
                current_stress=getattr(entity_core, "stress", 0.0),
                threshold_ratio=1.2,
            ):
                queue_pressure = 0.7
        except Exception:
            pass

    energy_factor = max(0.0, 1.0 - energy) * 0.5
    drives["fatigue"] = min(1.0, drives["fatigue"] + energy_factor + queue_pressure * 0.3)

    ranked = sorted(drives.items(), key=lambda x: x[1], reverse=True)
    primary_dim, primary_pressure = ranked[0]
    _, second_pressure = ranked[1]

    total = primary_pressure + second_pressure + 1e-6
    tension = 1.0 - abs(primary_pressure - second_pressure) / total
    tension = max(0.0, min(1.0, tension))

    action_type = PRIMARY_ACTION.get(primary_dim, "idle")

    metabolite = getattr(entity_core, "failure_metabolite", 0.0)
    if action_type == "seek":
        if metabolite > 0.3:
            action_type = "rest"
            dominant = "metabolite_constraint"
        elif metabolite > 0.1:
            action_type = "comfort"
            dominant = "metabolite_constraint"
        else:
            dominant = ACTION_DOMINANTS.get(action_type, "tension")
    else:
        dominant = ACTION_DOMINANTS.get(action_type, "tension")

    priority = primary_pressure
    boost = 0.0
    if action_type == "seek":
        boost = drives["loneliness"] * 0.2
    elif action_type == "repair":
        boost = drives["repair"] * 0.3
    elif action_type == "rest":
        boost = drives["fatigue"] * 0.15
    priority = min(1.0, priority + boost)

    target = ACTION_TARGETS.get(action_type, "")
    target_locked = getattr(entity_core, "target_locked", None)
    if target_locked and target_locked != "none":
        target = target_locked

    suggested_tool = ""
    if action_type == "repair":
        wm_conf = _get_wm_repair_confidence(entity_core)
        ask_weight = max(0.0, 1.0 - wm_conf * 2.0)
        shell_weight = max(0.0, (wm_conf - 0.3) * 2.5)
        if ask_weight > shell_weight:
            suggested_tool = "ask_hermes"
        elif shell_weight > 0.1:
            suggested_tool = "shell_run"

    return _V5EmergentResult(
        action_type=action_type,
        target=target,
        priority=round(priority, 3),
        tension_level=round(tension, 3),
        dominant_state=dominant,
        state_snapshot=snap,
        suggested_tool=suggested_tool,
    )
