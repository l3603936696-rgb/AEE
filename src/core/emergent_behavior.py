"""
EmergentBehavior — 涌现行为（V6 连续向量场版）

核心原则：行为从拮抗驱动力场的合力中涌现，无需人工预设类别。

对外接口：
    emerge_behavior(entity_core) → EmergentBehavior

模块结构：
    emergent_behavior.py   — V6 主逻辑（此文件）
    emergent_behavior_v5.py — V5 fallback（V4/V3 历史逻辑）
    drive_vector_field.py  — 拮抗矩阵 + 连续质变
    behavior_vector.py     — 内生 rule effect + rule bias
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


# ============================================================================
# V6: 驱动力场链路
# ============================================================================

# 行为类型映射：从主导净力维度 → 动作类型
_DRIVE_TO_ACTION: Dict[str, str] = {
    "curiosity":      "explore",
    "info_hunger":    "explore",
    "loneliness":     "seek",
    "fatigue":        "rest",
    "unresolved":     "repair",
    "danger":         "avoid",
    "somatic_tone_p": "comfort",
}

# 行为质地描述：fragmentation 高时 → 行为不稳定
_FRAG_TONE_NORMAL: Dict[str, str] = {
    "seek":     "社交渴望强烈",
    "explore":  "好奇心强烈",
    "rest":     "疲惫感强烈",
    "repair":   "解决问题的冲动强烈",
    "avoid":    "回避倾向强烈",
    "comfort":  "需要安抚",
    "idle":     "平静无事",
}

_FRAG_TONE_HIGH: Dict[str, str] = {
    "seek":     "社交欲望断断续续、犹豫不决",
    "explore":  "好奇心飘忽不定、注意力分散",
    "rest":     "想休息但停不下来、身体很矛盾",
    "repair":   "想解决问题但思绪被拉扯",
    "avoid":    "想回避但又不安",
    "comfort":  "想被安慰但感受模糊",
    "idle":     "内心有些拉扯但还算平静",
}


def _compute_v6_behavior(entity_core, drive_vector: Optional[Dict[str, float]] = None) -> "V6Result":
    """
    V6 行为涌现：驱动力场 + 拮抗 + 连续质变 + 内生 rule effect。

    步骤：
        1. 若传入 drive_vector，从 v1 输出映射；否则从 EntityCore 提取
        2. 经拮抗矩阵得到 net_drives
        3. 计算 fragmentation 系数 alpha
        4. 生成 behavior_vector（intensity + fragmentation）
        5. 应用内生 rule bias
        6. 从 intensity 最大维度推导动作类型

    返回 V6Result，失败时抛出异常。
    """
    from .drive_vector_field import compute_drive_field, DriveFieldResult
    from .behavior_vector import apply_rule_bias

    df_result: DriveFieldResult = compute_drive_field(entity_core, drive_vector=drive_vector)
    bv = apply_rule_bias(df_result.behavior_vector, entity_core)

    intensity_items = {
        k.replace("_intensity", ""): v
        for k, v in bv.items()
        if k.endswith("_intensity")
    }

    if not intensity_items:
        return V6Result(
            action_type="idle",
            target="",
            priority=0.0,
            tension_level=df_result.tension_level(),
            dominant_state="",
            behavior_vector=bv,
            drive_field_result=df_result,
            fragmentation_tone="平静无事",
        )

    dominant_dim = max(intensity_items, key=lambda k: intensity_items[k])
    action_type = _DRIVE_TO_ACTION.get(dominant_dim, "idle")

    primary_intensity = intensity_items[dominant_dim]
    tension = df_result.tension_level()
    priority = min(1.0, primary_intensity * (1.0 + tension * 0.3))

    frag_key = f"{dominant_dim}_fragmentation"
    frag = bv.get(frag_key, 0.0)

    if frag > 0.4:
        tone = _FRAG_TONE_HIGH.get(action_type, "行为有抵触感")
    else:
        tone = _FRAG_TONE_NORMAL.get(action_type, "")

    return V6Result(
        action_type=action_type,
        target="",
        priority=round(priority, 3),
        tension_level=round(tension, 3),
        dominant_state=dominant_dim,
        behavior_vector=bv,
        drive_field_result=df_result,
        fragmentation_tone=tone,
    )


@dataclass
class V6Result:
    """V6 行为涌现的完整计算结果."""
    action_type: str
    target: str
    priority: float
    tension_level: float
    dominant_state: str
    behavior_vector: Dict[str, float]
    drive_field_result: Any
    fragmentation_tone: str = ""


# ============================================================================
# V6 主入口
# ============================================================================

def emerge_behavior(entity_core: Any, drive_vector: Optional[Dict[str, float]] = None) -> "EmergentBehavior":
    """
    从 EntityCore 连续状态涌现行为。

    参数：
        entity_core: EntityCore 实例
        drive_vector: 可选，来自 v1 的驱动力向量。
                      若传入，V6 在 v1 输出基础上做拮抗计算；
                      否则从 entity_core 原始状态提取（向后兼容）。

    优先级：
        1. V6（驱动力场 + 拮抗 + fragmentation + 内生 rule effect）
        2. V5 fallback（原有排序逻辑）
    """
    snap = entity_core.take_snapshot()

    # 测试钩子（保持向后兼容）
    forced = getattr(entity_core, "_forced_action", None)
    if forced is not None:
        return EmergentBehavior(str(forced), "test", 0.9, 0.0, "forced", snap)

    # ---- V6: 驱动力场链路（优先）----
    v6_result: V6Result | None = None
    try:
        v6_result = _compute_v6_behavior(entity_core, drive_vector=drive_vector)
    except Exception:
        pass

    if v6_result is not None:
        suggested_tool = ""
        if v6_result.action_type == "repair":
            from .emergent_behavior_v5 import _get_wm_repair_confidence
            wm_conf = _get_wm_repair_confidence(entity_core)
            ask_weight = max(0.0, 1.0 - wm_conf * 2.0)
            shell_weight = max(0.0, (wm_conf - 0.3) * 2.5)
            if ask_weight > shell_weight:
                suggested_tool = "ask_hermes"
            elif shell_weight > 0.1:
                suggested_tool = "shell_run"

        target_locked = getattr(entity_core, "target_locked", None)
        target = getattr(v6_result, "target", "") or (
            target_locked if target_locked and target_locked != "none" else ""
        )

        emergent = EmergentBehavior(
            action_type=v6_result.action_type,
            target=target,
            priority=v6_result.priority,
            tension_level=v6_result.tension_level,
            dominant_state=v6_result.dominant_state,
            state_snapshot=snap,
            suggested_tool=suggested_tool,
        )
        emergent.behavior_vector = v6_result.behavior_vector
        emergent.fragmentation_tone = v6_result.fragmentation_tone
        return emergent

    # ---- V5 fallback ----
    from .emergent_behavior_v5 import compute_v5_fallback
    v5 = compute_v5_fallback(entity_core, snap)

    return EmergentBehavior(
        action_type=v5.action_type,
        target=v5.target,
        priority=v5.priority,
        tension_level=v5.tension_level,
        dominant_state=v5.dominant_state,
        state_snapshot=snap,
        suggested_tool=v5.suggested_tool,
    )


# ============================================================================
# 数据结构
# ============================================================================

@dataclass
class EmergentBehavior:
    """涌现行为输出结构."""
    action_type: str = "idle"
    target: str = ""
    priority: float = 0.0
    tension_level: float = 0.0
    dominant_state: str = ""
    state_snapshot: Dict[str, Any] = field(default_factory=dict)
    suggested_tool: str = ""
    # V6 附加字段
    behavior_vector: Dict[str, float] = field(default_factory=dict)
    fragmentation_tone: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_type": self.action_type,
            "target": self.target,
            "priority": self.priority,
            "tension_level": self.tension_level,
            "dominant_state": self.dominant_state,
            "state_snapshot": self.state_snapshot,
            "suggested_tool": self.suggested_tool,
            "behavior_vector": {k: round(v, 4) for k, v in self.behavior_vector.items()},
            "fragmentation_tone": self.fragmentation_tone,
        }


# ============================================================================
# 兼容旧接口（V5 的导出）
# ============================================================================

def compute_tension(a: float, b: float) -> float:
    na = a - b * 0.3
    nb = b - a * 0.3
    t = na + nb + 1e-6
    return max(0.0, min(1.0, 1.0 - abs(na - nb) / t))


def compute_tension_raw(a: float, b: float) -> tuple:
    na = a - b * 0.3
    nb = b - a * 0.3
    t = max(0.0, min(1.0, 1.0 - abs(na - nb) / (na + nb + 1e-6)))
    return na, nb, t


# ============================================================================
# 渲染参数（V5 遗留，供 output_layer 使用）
# ============================================================================

def _interpolate(x: float, anchors_x, anchors_y) -> str:
    if x <= anchors_x[0]:
        return anchors_y[0]
    if x >= anchors_x[-1]:
        return anchors_y[-1]
    for i in range(len(anchors_x) - 1):
        if anchors_x[i] <= x <= anchors_x[i + 1]:
            t = (x - anchors_x[i]) / (anchors_x[i + 1] - anchors_x[i])
            return anchors_y[i] if t < 0.5 else anchors_y[i + 1]
    return anchors_y[-1]


def _interpolate_pace(x: float) -> str:
    return _interpolate(x, [0.0, 0.3, 0.6, 0.85], ["快", "正常", "慢", "很慢"])


def _interpolate_length(x: float) -> str:
    return _interpolate(x, [0.0, 0.3, 0.5, 0.75], ["很短", "偏短", "正常", "偏长"])


def _interpolate_stability(x: float) -> str:
    return _interpolate(x, [0.0, 0.3, 0.6, 0.8], ["平稳", "正常", "有点波动", "不稳定"])


def _interpolate_initiative(x: float) -> str:
    return _interpolate(x, [0.0, 0.3, 0.5, 0.75], ["被动回应", "正常回应", "偏主动", "主动延伸话题"])


_ACTION_INITIATIVE_CAPS: Dict[str, str] = {
    "rest": "被动回应", "avoid": "被动回应", "comfort": "偏主动",
    "explore": "偏主动", "seek": "主动延伸话题", "repair": "偏主动", "idle": "正常回应",
}


def _apply_action_consistency(initiative: str, action_type: str) -> str:
    levels = ["被动回应", "正常回应", "偏主动", "主动延伸话题"]
    cap = _ACTION_INITIATIVE_CAPS.get(action_type, "主动延伸话题")
    cap_idx = levels.index(cap) if cap in levels else len(levels) - 1
    init_idx = levels.index(initiative) if initiative in levels else cap_idx
    return levels[min(init_idx, cap_idx)]


def derive_rendering_params(
    emergent_behavior: EmergentBehavior,
    entity_state: Any,
) -> Dict[str, str]:
    avoid = float(getattr(entity_state, "avoid_drive", 0.0))
    fatigue = float(getattr(entity_state, "fatigue", 0.0))
    approach = float(getattr(entity_state, "approach_drive", 0.0))
    tension = float(getattr(emergent_behavior, "tension_level", 0.0))
    action = str(getattr(emergent_behavior, "action_type", "idle"))

    pace_x = avoid * 0.7 + fatigue * 0.3
    length_x = approach
    stability_x = tension
    init_x = (
        float(getattr(entity_state, "loneliness_drive", 0.0)) * 0.6
        + float(getattr(entity_state, "curiosity", 0.5)) * 0.4
    )

    if approach >= 0.85 and fatigue <= 0.15:
        init_x = max(init_x, 0.65)

    initiative = _interpolate_initiative(init_x)
    initiative = _apply_action_consistency(initiative, action)

    return {
        "pace": _interpolate_pace(pace_x),
        "length": _interpolate_length(length_x),
        "tone_stability": _interpolate_stability(stability_x),
        "initiative": initiative,
    }
