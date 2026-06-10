"""Compatibility wrapper for presenting EntityState/EntityCore to emergent behavior."""

from typing import Any, Dict, List, Optional

# ============================================================================


class _CoreWrapper:
    """
    将管线内的 EntityState 适配为 core/emergent_behavior.emerge_behavior() 所需接口。

    支持两种输入：
        - dict: 旧模式，直接取 key
        - EntityCore 实例：直接透传属性访问
    """
    __slots__ = ("_state", "_wm_rules", "_snapshots", "_is_entity_core")

    def __init__(self, state: Any, wm_rules: List[Any], snapshots: List[Any]) -> None:
        self._is_entity_core = not isinstance(state, dict)
        self._state = state  # dict 或 EntityCore
        self._wm_rules = wm_rules
        self._snapshots = snapshots

    def take_snapshot(self) -> Dict[str, Any]:
        if self._is_entity_core:
            return self._state.take_snapshot()
        return dict(self._state)

    @property
    def target_locked(self) -> str:
        if self._is_entity_core:
            return getattr(self._state, "target_locked", "none")
        return str(self._state.get("target_locked", "none"))

    @property
    def energy(self) -> float:
        if self._is_entity_core:
            return float(getattr(self._state, "energy", 0.8))
        return float(self._state.get("energy", 0.8))

    @property
    def loneliness(self) -> float:
        if self._is_entity_core:
            return float(getattr(self._state, "loneliness", 0.3))
        return float(self._state.get("loneliness", 0.3))

    @property
    def unresolved(self) -> float:
        if self._is_entity_core:
            return float(getattr(self._state, "unresolved", 0.2))
        return float(self._state.get("unresolved", 0.2))

    @property
    def fatigue(self) -> float:
        if self._is_entity_core:
            return float(getattr(self._state, "fatigue", 0.1))
        return float(self._state.get("fatigue", 0.1))

    @property
    def info_gap(self) -> float:
        if self._is_entity_core:
            return float(getattr(self._state, "info_gap", 0.5))
        return float(self._state.get("info_gap", 0.5))

    @property
    def somatic_tone(self) -> float:
        if self._is_entity_core:
            return float(getattr(self._state, "somatic_tone", 0.0))
        return float(self._state.get("somatic_tone", 0.0))

    @property
    def danger_level(self) -> float:
        if self._is_entity_core:
            return float(getattr(self._state, "danger_level", 0.0))
        return float(self._state.get("danger_level", 0.0))

    @property
    def approach_drive(self) -> float:
        if self._is_entity_core:
            return float(getattr(self._state, "approach_drive", 0.0))
        return float(self._state.get("approach_drive", 0.0))

    @property
    def avoid_drive(self) -> float:
        if self._is_entity_core:
            return float(getattr(self._state, "avoid_drive", 0.0))
        return float(self._state.get("avoid_drive", 0.0))

    @property
    def stress(self) -> float:
        if self._is_entity_core:
            return float(getattr(self._state, "stress", 0.1))
        return float(self._state.get("stress", 0.1))

    @property
    def pending_surprises_count(self) -> int:
        """pending_surprises 数量（供 emergent_behavior 使用）。"""
        ps = getattr(self._state, "pending_surprises", [])
        if not isinstance(ps, list):
            return 0
        return len(ps)

    @property
    def last_action_result(self) -> Dict[str, Any]:
        """上次异步动作的执行结果（成功/失败反馈）。"""
        if self._is_entity_core:
            return getattr(self._state, "_last_action_result", {"success": None, "detail": ""})
        return self._state.get("_last_action_result", {"success": None, "detail": ""})

    @property
    def time_since_last_social(self) -> float:
        if self._is_entity_core:
            return float(getattr(self._state, "time_since_last_social", 0.0))
        return float(self._state.get("time_since_last_social", 0.0))

    @property
    def time_since_last_info(self) -> float:
        if self._is_entity_core:
            return float(getattr(self._state, "time_since_last_info", 0.0))
        return float(self._state.get("time_since_last_info", 0.0))

    @property
    def curiosity(self) -> float:
        if self._is_entity_core:
            return float(getattr(self._state, "curiosity", 0.5))
        return float(self._state.get("curiosity", 0.5))

    @property
    def failure_metabolite(self) -> float:
        if self._is_entity_core:
            return float(getattr(self._state, "failure_metabolite", 0.0))
        # EntityState has this as a field
        return float(getattr(self._state, "failure_metabolite", 0.0))

    @property
    def pending_failures(self) -> list:
        return getattr(self._state, "pending_failures", [])

    @property
    def boredom(self) -> float:
        if self._is_entity_core:
            return float(getattr(self._state, "boredom", 0.2))
        return float(self._state.get("boredom", 0.2))

    @property
    def last_action_timestamp(self) -> float:
        """最近一次主动行动时间（epoch 秒），供触发器冷却检查用。"""
        if self._is_entity_core:
            return float(getattr(self._state, "last_action_timestamp", 0.0))
        return float(self._state.get("last_action_timestamp", 0.0))

    @property
    def consecutive_reaches_without_response(self) -> int:
        """连续敲门未得到回应的次数。"""
        if self._is_entity_core:
            return int(getattr(self._state, "consecutive_reaches_without_response", 0))
        return int(self._state.get("consecutive_reaches_without_response", 0))

    @property
    def _forced_action(self) -> Optional[str]:
        """强制动作类型（测试场景用）。"""
        if self._is_entity_core:
            return getattr(self._state, "_forced_action", None)
        return None

    @property
    def _last_prediction_error(self) -> float:
        if self._is_entity_core:
            return float(getattr(self._state, "_last_prediction_error", 0.0))
        return float(self._state.get("_last_prediction_error", 0.0))

    @property
    def wm_rules(self) -> List[Any]:
        if self._is_entity_core:
            return getattr(self._state, "wm_rules", self._wm_rules)
        return self._wm_rules

    @property
    def snapshots(self) -> List[Any]:
        if self._is_entity_core:
            return getattr(self._state, "snapshots", self._snapshots)
        return self._snapshots


def _make_core_wrapper(entity_or_state: Any):
    """
    构建 _CoreWrapper 实例。

    参数：
        entity_or_state : EntityCore 实例 或 dict
    """
    if hasattr(entity_or_state, "wm_rules"):
        return _CoreWrapper(
            entity_or_state,
            entity_or_state.wm_rules,
            getattr(entity_or_state, "snapshots", [])[-10:],
        )
    return _CoreWrapper(
        entity_or_state,
        entity_or_state.get("wm_rules", []),
        entity_or_state.get("snapshots", [])[-10:],
    )

