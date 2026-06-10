"""
Decision System Module (裁决系统)

主入口模块：负责汇聚信号、裁决与输出。
各子模块独立存放于 submodules/ 目录，模块注册表驱动，便于增删改。
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import importlib
import logging

logger = logging.getLogger(__name__)

from .submodules.base import DriveSignal


# ============================================================================
# 参数默认值
# ============================================================================

DEFAULT_PARAMS = {
    "module_weights": {
        "SituationAssessment": 1.0,
        "ContextAwareness": 1.0,
        "ThoughtIntegration": 1.0,
        "SignalActivation": 1.0,
        "MainlineConstraint": 1.0,
        "TemporalPressure": 1.0,
        "SelfState": 1.0,
        "Preference": 1.0,
        "WorldModel": 1.0,
    },
    "survival_override_threshold": 0.85,
    "max_suggestions": 2,
    "fallback_priority": 0.0,
}


# ============================================================================
# 模块注册表
#
# 格式：name -> (module_import_path, class_name)
# 通过 importlib 动态加载，支持热插拔（增删改文件后自动生效）。
# 只需在此处注册，无需修改主函数。
# ============================================================================

MODULE_REGISTRY: Dict[str, tuple[str, str]] = {
    "SituationAssessment": ("submodules.situation_assessment", "SituationAssessment"),
    "ContextAwareness":   ("submodules.context_awareness",   "ContextAwareness"),
    "ThoughtIntegration": ("submodules.thought_integration", "ThoughtIntegration"),
    "SignalActivation":   ("submodules.signal_activation",   "SignalActivation"),
    "MainlineConstraint": ("submodules.mainline_constraint", "MainlineConstraint"),
    "TemporalPressure":   ("submodules.temporal_pressure",   "TemporalPressure"),
    "SelfState":         ("submodules.self_state",         "SelfState"),
    "Preference":         ("submodules.preference",         "Preference"),
    "WorldModel":        ("submodules.world_model",        "WorldModel"),
    "WebSearch":         ("submodules.web_search",         "WebSearch"),
    "ToolSelfCheck":     ("submodules.tool_self_check",    "ToolSelfCheck"),  # v11.6 主动工具自省
}


# ============================================================================
# v3 九模块并行感知
# ============================================================================

def perceive_all(
    entity_core: Any,
    semantic_packet_biased: dict,
    concept_tags: List[dict],
    wm_context: dict,
    drive_vector: dict,
    thought_packet: dict,
    state_snapshot: dict,
    params: Optional[dict] = None,
) -> None:
    """
    v3 九模块并行感知主入口。

    遍历 MODULE_REGISTRY，对每个子模块调用 perceive() 方法，
    直接修改 entity_core 的状态变量。

    各模块修改的变量映射（按 v3 报告）：
        SituationAssessment → approach_drive
        ContextAwareness   → loneliness（±）, approach_drive（±）, avoid_drive（±）, danger_level（±）
        ThoughtIntegration → approach_drive（±）, avoid_drive（±）
        SignalActivation   → avoid_drive, approach_drive, somatic_tone
        MainlineConstraint → avoid_drive, approach_drive
        TemporalPressure   → fatigue, approach_drive
        SelfState         → avoid_drive, somatic_tone
        Preference         → approach_drive, avoid_drive
        WorldModel         → curiosity, approach_drive, avoid_drive
        WebSearch          → （无直接修改）

    修改原则：
        - 所有修改通过 entity_core.adjust() 进行，自动 clamp
        - somatic_tone clamp 到 [-1, 1]
        - 单模块失败不影响其他模块
    """
    params = {**DEFAULT_PARAMS, **(params or {})} if isinstance(params, dict) else DEFAULT_PARAMS

    # v11: 感知镇压——记录感知前值，运行完所有模块后 dampen delta
    _dampen = getattr(entity_core, "_perception_dampen", 1.0)
    _pre_approach_social = getattr(entity_core, "approach_social", 0.0)
    _pre_approach_explore = getattr(entity_core, "approach_explore", 0.0)
    _pre_approach_urgency = getattr(entity_core, "approach_urgency", 0.0)
    _pre_avoid = getattr(entity_core, "avoid_drive", 0.0)
    _pre_somatic = getattr(entity_core, "somatic_tone", 0.0)

    # 构建每个模块的输入（各模块只需自己关心的字段）
    inputs = {
        "semantic_packet_biased": semantic_packet_biased,
        "concept_tags": concept_tags,
        "wm_context": wm_context,
        "drive_vector": drive_vector,
        "thought_packet": thought_packet,
        "state_snapshot": state_snapshot,
        "params": params,
    }

    for module_name, (import_path, class_name) in MODULE_REGISTRY.items():
        try:
            mod = importlib.import_module(f".{import_path}", package="src.decision_system")
            cls = getattr(mod, class_name)
            instance = cls()
            # perceive() 方法签名：perceive(inputs, entity_core)
            if hasattr(instance, "perceive"):
                instance.perceive(inputs, entity_core)
        except Exception as e:
            logger.warning(f"[perceive_all] {module_name} failed: {e}")

    # v11: 感知镇压——根据锁死程度 dampen 感知模块的修改量
    if _dampen < 0.99:
        _post_social = getattr(entity_core, "approach_social", _pre_approach_social)
        _post_explore = getattr(entity_core, "approach_explore", _pre_approach_explore)
        _post_urgency = getattr(entity_core, "approach_urgency", _pre_approach_urgency)
        _post_avoid = getattr(entity_core, "avoid_drive", _pre_avoid)
        _post_somatic = getattr(entity_core, "somatic_tone", _pre_somatic)

        # 线性插值：保留 dampen 比例的增量
        entity_core.adjust("approach_social", (_post_social - _pre_approach_social) * (_dampen - 1.0))
        entity_core.adjust("approach_explore", (_post_explore - _pre_approach_explore) * (_dampen - 1.0))
        entity_core.adjust("approach_urgency", (_post_urgency - _pre_approach_urgency) * (_dampen - 1.0))
        entity_core.adjust("avoid_drive", (_post_avoid - _pre_avoid) * (_dampen - 1.0))
        if _post_somatic != _pre_somatic:
            entity_core.adjust("somatic_tone", (_post_somatic - _pre_somatic) * (_dampen - 1.0))


# ============================================================================
# 测试入口
# ============================================================================

if __name__ == "__main__":
    print("=" * 64)
    print("裁决系统集成测试")
    print("=" * 64)

    test_cases = [
        {
            "name": "正常裁决 — 好奇心驱动胜出",
            "semantic_packet_biased": {"emotion": 0.2, "intent": "分享", "intensity": 0.6, "anchors": []},
            "concept_tags": [],
            "wm_context": {"matched_rules": [], "coverage": {"hit_rate": 0.0}},
            "drive_vector": {"curiosity": 0.8, "info_hunger": 0.6, "obsolescence_anxiety": 0.1, "loneliness_drive": 0.1, "fatigue_avoid": 0.1},
            "thought_packet": {"suggestions": [{"action": "探索未知领域", "reason": "好奇心强", "priority": 0.8}], "questions": []},
            "state_snapshot": {},
            "params": {},
            "expect_action": "seek",
            "expect_target": "none",
        },
        {
            "name": "生理底线触发 — 能量极低",
            "semantic_packet_biased": {"emotion": 0.5, "intent": "分享", "intensity": 0.8, "anchors": []},
            "concept_tags": [],
            "wm_context": {"matched_rules": [], "coverage": {"hit_rate": 0.5}},
            "drive_vector": {"curiosity": 0.9, "info_hunger": 0.9, "obsolescence_anxiety": 0.1, "loneliness_drive": 0.1, "fatigue_avoid": 0.1},
            "thought_packet": {"suggestions": [], "questions": []},
            "state_snapshot": {"energy": 0.05, "pain": 0.0, "fatigue": 0.0},
            "params": {},
            "expect_action": "comfort",
            "expect_target": "none",
            "expect_reason_contains": "生理底线",
        },
        {
            "name": "负向情绪 + 高疲劳 → avoid 胜出",
            "semantic_packet_biased": {"emotion": -0.6, "intent": "抱怨", "intensity": 0.7, "anchors": []},
            "concept_tags": [],
            "wm_context": {"matched_rules": [], "coverage": {"hit_rate": 0.5}},
            "drive_vector": {"curiosity": 0.1, "info_hunger": 0.1, "obsolescence_anxiety": 0.1, "loneliness_drive": 0.1, "fatigue_avoid": 0.1},
            "thought_packet": {"suggestions": [], "questions": []},
            "state_snapshot": {"fatigue": 0.8, "pain": 0.0, "energy": 0.5},
            "params": {},
            "expect_action": "avoid",
        },
        {
            "name": "求助意图 → target 锁定 observer_user",
            "semantic_packet_biased": {"emotion": -0.2, "intent": "求助", "intensity": 0.6, "anchors": []},
            "concept_tags": [],
            "wm_context": {"matched_rules": [], "coverage": {"hit_rate": 0.5}},
            "drive_vector": {"curiosity": 0.3, "info_hunger": 0.4, "obsolescence_anxiety": 0.1, "loneliness_drive": 0.1, "fatigue_avoid": 0.1},
            "thought_packet": {"suggestions": [], "questions": []},
            "state_snapshot": {},
            "params": {},
            "expect_action": "seek",
            "expect_target": "observer_user",
        },
        {
            "name": "世界模型低覆盖 → seek 胜出",
            "semantic_packet_biased": {"emotion": 0.0, "intent": "闲聊", "intensity": 0.3, "anchors": []},
            "concept_tags": [],
            "wm_context": {
                "matched_rules": [],
                "coverage": {"hit_rate": 0.1, "queried_tags": [], "missed_tags": []}
            },
            "drive_vector": {"curiosity": 0.1, "info_hunger": 0.1, "obsolescence_anxiety": 0.1, "loneliness_drive": 0.1, "fatigue_avoid": 0.1},
            "thought_packet": {"suggestions": [], "questions": []},
            "state_snapshot": {},
            "params": {},
            "expect_action": "seek",
        },
        {
            "name": "加权聚合 — SituationAssessment 权重 2.0",
            "semantic_packet_biased": {"emotion": 0.4, "intent": "分享", "intensity": 0.7, "anchors": []},
            "concept_tags": [],
            "wm_context": {"matched_rules": [], "coverage": {"hit_rate": 0.5}},
            "drive_vector": {"curiosity": 0.5, "info_hunger": 0.5, "obsolescence_anxiety": 0.1, "loneliness_drive": 0.1, "fatigue_avoid": 0.1},
            "thought_packet": {"suggestions": [{"action": "探索", "reason": "t", "priority": 0.5}], "questions": []},
            "state_snapshot": {},
            "params": {
                "module_weights": {
                    "SituationAssessment": 2.0,
                    "ContextAwareness": 1.0,
                    "ThoughtIntegration": 1.0,
                    "SignalActivation": 1.0,
                    "MainlineConstraint": 1.0,
                    "TemporalPressure": 1.0,
                    "SelfState": 1.0,
                    "Preference": 1.0,
                    "WorldModel": 1.0,
                }
            },
            "expect_action": "seek",
            "expect_source": "SituationAssessment",
        },
    ]

    passed = 0
    for i, tc in enumerate(test_cases, 1):
        result = decide(
            tc["semantic_packet_biased"],
            tc["concept_tags"],
            tc["wm_context"],
            tc["drive_vector"],
            tc["thought_packet"],
            tc["state_snapshot"],
            tc["params"]
        )

        ok_action = result["action_type"] == tc.get("expect_action", result["action_type"])
        ok_target = result["target"] == tc.get("expect_target", result["target"])
        ok_reason = (
            tc.get("expect_reason_contains") is None
            or tc["expect_reason_contains"] in result["payload"]["reason"]
        )
        ok_source = (
            tc.get("expect_source") is None
            or result["payload"]["source"] == tc["expect_source"]
        )
        ok = ok_action and ok_target and ok_reason and ok_source

        if ok:
            passed += 1
            status = "✓"
        else:
            status = "✗"

        print(f"\n【测试 {i}】{tc['name']}  {status}")
        print(f"  action_type : {result['action_type']}  {'✓' if ok_action else '✗ ' + str(tc.get('expect_action'))}")
        print(f"  target      : {result['target']}  {'✓' if ok_target else '✗ ' + str(tc.get('expect_target'))}")
        print(f"  priority    : {result['priority']:.3f}")
        print(f"  payload     : {result['payload']}")

    print(f"\n{'='*64}")
    print(f"通过率: {passed}/{len(test_cases)}")
    print("=" * 64)
