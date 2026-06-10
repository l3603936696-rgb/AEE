"""
参数同步桥 — param_store.json ↔ EntityState 转换系数 dict 的双向同步

设计约束：
    - 只在风化周期（每 300 tick）调用，不干扰 feedback_loop 等运行时修改
    - reverse_sync 在风化前调用：把 entity 运行时值写回 param_store，让风化从真实值开始漂移
    - sync 在风化后调用：把漂移后的值写入 entity dict，让下一轮 pipeline 使用新值
    - 只处理 param_store 中已存在的键，不引入新键、不破坏 entity 上的其他字段
"""

from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


# ============================================================================
# 映射表：param_store dot-path → EntityState (attr_name, *key_path)
# ============================================================================
# 二元组 = flat dict：entity._xxx[key]
# 三元组 = nested dict：entity._xxx[k1][k2]

_SYNC_MAP: Dict[str, tuple] = {
    # ---- approach_synthesis_weights ----
    "conversion.approach_synthesis.social":  ("_approach_synthesis_weights", "social"),
    "conversion.approach_synthesis.explore": ("_approach_synthesis_weights", "explore"),
    "conversion.approach_synthesis.urgency": ("_approach_synthesis_weights", "urgency"),

    # ---- quench_feedback_weights ----
    "conversion.quench_feedback.quench_rate":      ("_quench_feedback_weights", "quench_rate"),
    "conversion.quench_feedback.approach_release":  ("_quench_feedback_weights", "approach_release"),
    "conversion.quench_feedback.avoid_release":     ("_quench_feedback_weights", "avoid_release"),
    "conversion.quench_feedback.somatic_comfort":   ("_quench_feedback_weights", "somatic_comfort"),

    # ---- failure_metabolite_weights ----
    "conversion.failure_metabolite.approach_suppress":  ("_failure_metabolite_weights", "approach_suppress"),
    "conversion.failure_metabolite.avoid_increase":     ("_failure_metabolite_weights", "avoid_increase"),
    "conversion.failure_metabolite.curiosity_suppress":  ("_failure_metabolite_weights", "curiosity_suppress"),
    "conversion.failure_metabolite.somatic_damage":      ("_failure_metabolite_weights", "somatic_damage"),

    # ---- conflict_to_unresolved_weights ----
    "conversion.conflict_to_unresolved.conflict_rate":      ("_conflict_to_unresolved_weights", "conflict_rate"),
    "conversion.conflict_to_unresolved.unresolved_decay":    ("_conflict_to_unresolved_weights", "unresolved_decay"),
    "conversion.conflict_to_unresolved.introspection_gain":  ("_conflict_to_unresolved_weights", "introspection_gain"),

    # ---- emotion_drive_modulation (nested) ----
    "conversion.emotion_drive_mod.approach.joy":        ("_emotion_drive_modulation", "approach", "joy"),
    "conversion.emotion_drive_mod.approach.anger":      ("_emotion_drive_modulation", "approach", "anger"),
    "conversion.emotion_drive_mod.approach.excitement":  ("_emotion_drive_modulation", "approach", "excitement"),
    "conversion.emotion_drive_mod.approach.sadness":     ("_emotion_drive_modulation", "approach", "sadness"),
    "conversion.emotion_drive_mod.approach.anxiety":     ("_emotion_drive_modulation", "approach", "anxiety"),
    "conversion.emotion_drive_mod.avoid.fear":           ("_emotion_drive_modulation", "avoid", "fear"),
    "conversion.emotion_drive_mod.avoid.disgust":        ("_emotion_drive_modulation", "avoid", "disgust"),
    "conversion.emotion_drive_mod.avoid.anxiety":        ("_emotion_drive_modulation", "avoid", "anxiety"),
    "conversion.emotion_drive_mod.avoid.anger":          ("_emotion_drive_modulation", "avoid", "anger"),

    # ---- vocab_acquisition_params ----
    "conversion.vocab_acquisition.min_comprehension":  ("_vocab_acquisition_params", "min_comprehension"),
    "conversion.vocab_acquisition.exposure_per_hit":   ("_vocab_acquisition_params", "exposure_per_hit"),
    "conversion.vocab_acquisition.ask_threshold":      ("_vocab_acquisition_params", "ask_threshold"),
    "conversion.vocab_acquisition.exposure_decay":     ("_vocab_acquisition_params", "exposure_decay"),
    "conversion.vocab_acquisition.max_asks_per_tick":  ("_vocab_acquisition_params", "max_asks_per_tick"),

    # ---- repetition_decay_params ----
    "conversion.repetition_decay.decay_per_use":   ("_repetition_decay_params", "decay_per_use"),
    "conversion.repetition_decay.recovery_rate":   ("_repetition_decay_params", "recovery_rate"),
    "conversion.repetition_decay.floor":           ("_repetition_decay_params", "floor"),
    "conversion.repetition_decay.window_ticks":    ("_repetition_decay_params", "window_ticks"),

    # ---- response_pressure_params ----
    "conversion.response_pressure.coefficient":       ("_response_pressure_params", "coefficient"),
    "conversion.response_pressure.min_comprehension":  ("_response_pressure_params", "min_comprehension"),

    # ---- feedback_params ----
    "conversion.feedback_loop.acute_boost_scale":    ("_feedback_params", "acute_boost_scale"),
    "conversion.feedback_loop.chronic_threshold":    ("_feedback_params", "chronic_threshold"),
    "conversion.feedback_loop.chronic_drift_rate":   ("_feedback_params", "chronic_drift_rate"),
    "conversion.feedback_loop.chronic_signal_decay":  ("_feedback_params", "chronic_signal_decay"),
    "conversion.feedback_loop.chronic_tick_decay":    ("_feedback_params", "chronic_tick_decay"),
    "conversion.feedback_loop.chronic_min_quench":   ("_feedback_params", "chronic_min_quench"),
    "conversion.feedback_loop.weight_ceiling":       ("_feedback_params", "weight_ceiling"),
    "conversion.feedback_loop.weight_floor":         ("_feedback_params", "weight_floor"),
}


def _read_entity_value(entity: Any, mapping: tuple) -> float:
    """从 entity 的 dict 属性中按映射路径读取值。"""
    attr_name = mapping[0]
    d = getattr(entity, attr_name, {})
    # 二元组：d[key]
    # 三元组：d[k1][k2]
    keys = mapping[1:]
    for k in keys:
        d = d[k]
    return float(d)


def _write_entity_value(entity: Any, mapping: tuple, value: float) -> None:
    """向 entity 的 dict 属性中按映射路径写入值。"""
    attr_name = mapping[0]
    d = getattr(entity, attr_name, {})
    keys = mapping[1:]
    # 导航到倒数第二层
    for k in keys[:-1]:
        d = d[k]
    d[keys[-1]] = value


def sync_conversion_params(entity: Any) -> int:
    """
    param_store → entity：将 param_store.json 中的转换系数值写入 entity dict。

    在风化漂移之后调用，让 entity 拿到漂移后的新值。

    返回：同步的参数数量。
    """
    try:
        from .param_writer import read_current_params
        from .registry import REGISTRY

        # 只读 REGISTRY 中已注册的 conversion 参数（可漂移的子集）
        conversion_paths = [p for p in _SYNC_MAP if p in REGISTRY]
        defaults = {p: REGISTRY[p].baseline_default for p in conversion_paths}
        current = read_current_params(conversion_paths, defaults)

        count = 0
        for path, value in current.items():
            mapping = _SYNC_MAP.get(path)
            if not mapping:
                continue
            try:
                _write_entity_value(entity, mapping, value)
                count += 1
            except (KeyError, AttributeError, TypeError):
                logger.debug(f"[param_sync] sync skip: {path}")

        return count
    except Exception as e:
        logger.debug(f"[param_sync] sync failed: {e}")
        return 0


def reverse_sync_conversion_params(entity: Any) -> int:
    """
    entity → param_store：将 entity dict 中的转换系数值写回 param_store.json。

    在风化漂移之前调用，让风化系统从真实运行值开始计算。

    返回：同步的参数数量。
    """
    try:
        from .param_writer import write_drifted_params

        values: Dict[str, float] = {}
        for path, mapping in _SYNC_MAP.items():
            try:
                val = _read_entity_value(entity, mapping)
                values[path] = val
            except (KeyError, AttributeError, TypeError):
                continue

        written = write_drifted_params(values)
        return len(values) if written else 0
    except Exception as e:
        logger.debug(f"[param_sync] reverse_sync failed: {e}")
        return 0
