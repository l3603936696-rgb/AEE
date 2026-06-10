"""崩塌检测与抵抗 — 高置信规律被摧毁时的急剧参数漂移。"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..observability import ShatteringEvent, emit_event

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent.parent.parent.parent / "data"
_TENSION_PATH = _DATA_DIR / "suppressed_tension.json"


def load_suppressed_tension() -> Dict[str, float]:
    """加载累积压抑张力。key = domain。"""
    if _TENSION_PATH.exists():
        try:
            return json.loads(_TENSION_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_suppressed_tension(data: Dict[str, float]) -> None:
    try:
        _TENSION_PATH.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning(f"[weathering] Failed to save suppressed_tension: {e}")


# ---- 崩塌阈值 ----
MIN_OLD_CONFIDENCE = 0.7
MIN_CONFIDENCE_DROP = 0.3
MIN_SHATTERING_FORCE = 0.15
FORCED_COLLAPSE_TENSION = 1.5


def compute_shattering_force(
    old_confidence: float,
    new_confidence: float,
    inertia: float,
    contradiction_pressure: float,
    emotional_weight: float,
) -> float:
    """
    计算崩塌力。

    参数：
        old_confidence:        规律更新前的置信度
        new_confidence:        规律更新后的置信度（0 = 被删除）
        inertia:               规律惯性（来自 model_inertia.compute_inertia）
        contradiction_pressure: 矛盾压力（连续预测误差方向一致程度，0~1）
        emotional_weight:      情绪权重（规律追踪维度的当前驱动压力，0~1）

    返回：
        float >= 0，值越大崩塌力越强。
    """
    conf_drop = max(0.0, old_confidence - new_confidence)
    return conf_drop * inertia * max(contradiction_pressure, 0.1) * max(emotional_weight, 0.1)


def compute_update_resistance(
    rule: Any,
    all_rules: List[Any],
) -> Tuple[float, Dict[str, float]]:
    """
    计算规律的更新阻力。

    参数：
        rule:       被挑战的规律（Rule 对象或 dict）
        all_rules:  当前所有活跃规律

    返回：
        (total_resistance, components_dict)
        components: {"identity_binding": float, "attractor_strength": float, "sunk_cost": float}
    """
    rule_deltas = _get_expected_deltas(rule)
    rule_dims = set(rule_deltas.keys())

    shared_count = 0
    for other in all_rules:
        other_id = _get_field(other, "id", "")
        if other_id == _get_field(rule, "id", ""):
            continue
        other_dims = set(_get_expected_deltas(other).keys())
        if rule_dims & other_dims:
            shared_count += 1

    identity_binding = min(shared_count * 0.1, 1.0)

    stability = float(_get_field(rule, "stability_score", 0.5))
    attractor_strength = stability * 0.5

    exp_count = int(_get_field(rule, "source_experience_count", 1))
    sunk_cost = min(exp_count * 0.01, 0.5)

    total = identity_binding + attractor_strength + sunk_cost
    components = {
        "identity_binding": round(identity_binding, 4),
        "attractor_strength": round(attractor_strength, 4),
        "sunk_cost": round(sunk_cost, 4),
    }
    return total, components


def detect_and_process_shattering(
    old_rules: List[Any],
    new_rules: List[Any],
    all_rules: List[Any],
    tick: int,
    get_inertia_fn=None,
    get_contradiction_fn=None,
    get_emotion_fn=None,
) -> List[ShatteringEvent]:
    """
    检测并处理规律崩塌事件。

    在世界模型更新完成后调用，比较新旧规律列表。

    参数：
        old_rules:   更新前的规律列表
        new_rules:   更新后的规律列表
        all_rules:   更新后的完整规律列表（用于计算 identity_binding）
        tick:        当前 tick
        get_inertia_fn:       (rule) -> float，计算惯性。默认返回 0.5。
        get_contradiction_fn: (rule_id) -> float，获取矛盾压力。默认返回 0.5。
        get_emotion_fn:       (rule) -> float，获取情绪权重。默认返回 0.3。

    返回：
        List[ShatteringEvent] — 所有检测到的崩塌/抵抗事件。
    """
    if get_inertia_fn is None:
        get_inertia_fn = lambda r: 0.5
    if get_contradiction_fn is None:
        get_contradiction_fn = lambda rid: 0.5
    if get_emotion_fn is None:
        get_emotion_fn = lambda r: 0.3

    old_conf_map: Dict[str, Tuple[float, Any]] = {}
    for r in old_rules:
        rid = _get_field(r, "id", "")
        if rid:
            old_conf_map[rid] = (float(_get_field(r, "confidence", 0.5)), r)

    new_conf_map: Dict[str, float] = {}
    for r in new_rules:
        rid = _get_field(r, "id", "")
        if rid:
            new_conf_map[rid] = float(_get_field(r, "confidence", 0.5))

    events = []
    tension_data = load_suppressed_tension()

    for rule_id, (old_conf, old_rule) in old_conf_map.items():
        new_conf = new_conf_map.get(rule_id, 0.0)
        conf_drop = old_conf - new_conf

        if old_conf < MIN_OLD_CONFIDENCE or conf_drop < MIN_CONFIDENCE_DROP:
            continue

        inertia = get_inertia_fn(old_rule)
        contradiction = get_contradiction_fn(rule_id)
        emotion = get_emotion_fn(old_rule)

        force = compute_shattering_force(old_conf, new_conf, inertia, contradiction, emotion)

        if force < MIN_SHATTERING_FORCE:
            continue

        resistance, resist_components = compute_update_resistance(old_rule, all_rules)

        domain = str(_get_field(old_rule, "domain", "general"))

        affected_dims = list(_get_expected_deltas(old_rule).keys())

        domain_tension = tension_data.get(domain, 0.0)

        if domain_tension >= FORCED_COLLAPSE_TENSION:
            outcome = "collapsed"
            tension_data[domain] = 0.0
        elif force > resistance:
            outcome = "collapsed"
            tension_data[domain] = max(0.0, domain_tension - force * 0.5)
        else:
            outcome = "resisted"
            tension_data[domain] = domain_tension + force * 0.3

        force_components = {
            "confidence_drop": round(conf_drop, 4),
            "inertia": round(inertia, 4),
            "contradiction_pressure": round(contradiction, 4),
            "emotional_weight": round(emotion, 4),
        }

        event = ShatteringEvent(
            tick=tick,
            rule_id=rule_id,
            rule_content=str(_get_field(old_rule, "content", ""))[:100],
            shattering_force=round(force, 4),
            update_resistance=round(resistance, 4),
            outcome=outcome,
            confidence_before=round(old_conf, 4),
            confidence_after=round(new_conf, 4),
            suppressed_tension_after=round(tension_data.get(domain, 0.0), 4),
            affected_params=affected_dims,
            force_components=force_components,
            resistance_components=resist_components,
            domain=domain,
        )
        events.append(event)
        emit_event(event)

    _save_suppressed_tension(tension_data)

    return events


# ---- 辅助函数 ----

def _get_field(obj: Any, field: str, default: Any = None) -> Any:
    """兼容 dict 和 dataclass 的字段访问。"""
    if isinstance(obj, dict):
        return obj.get(field, default)
    return getattr(obj, field, default)


def _get_expected_deltas(obj: Any) -> Dict[str, float]:
    """获取规律的 expected_deltas。"""
    deltas = _get_field(obj, "expected_deltas", {})
    return deltas if isinstance(deltas, dict) else {}
