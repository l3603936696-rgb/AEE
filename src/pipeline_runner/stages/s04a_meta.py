"""Stage 04a — 元认知状态调整（Steps 7.5–7.14）。

职责：感知前衰减、MetaCognitive 镇压、Boredom、蒙特卡洛扰动、反锁推力、
      物理约束、danger/fatigue/unresolved/pain/relief 激活。
全部通过直接修改 entity 状态实现，无显式跨阶段输出。
"""

import logging
import random as _random

logger = logging.getLogger(__name__)


def run_stage(ctx, entity) -> None:
    _trace = ctx._trace
    daemon_mode = ctx.daemon_mode

    # ---- Step 7.5: 感知前衰减（v11: 子驱动力缓慢衰减）----
    entity.approach_social = max(0.0, entity.approach_social * 0.95)
    entity.approach_explore = max(0.0, entity.approach_explore * 0.95)
    entity.approach_urgency = max(0.0, entity.approach_urgency * 0.95)
    entity.avoid_drive = max(0.0, entity.avoid_drive * 0.88)

    # ---- Step 7.6: MetaCognitive 感知镇压（v11）----
    try:
        _lock_snaps = 0
        _snaps = entity.snapshots
        if _snaps and len(_snaps) >= 15:
            _recent = _snaps[-15:]
            LOCK_DIMS = ["approach_drive", "somatic_tone", "loneliness"]
            for dim in LOCK_DIMS:
                _vals = [s.get(dim, 0.5) for s in _recent]
                _mean = sum(_vals) / len(_vals)
                _variance = sum((v - _mean)**2 for v in _vals) / len(_vals)
                if _variance < 0.001 and abs(_mean - (0.5 if dim not in ("somatic_tone", "loneliness") else (0.0 if dim == "somatic_tone" else 0.3))) > 0.3:
                    _lock_snaps += 1
            _lock_snaps = min(_lock_snaps * 5, 50)

        _perception_dampen = 1.0 / (1.0 + _lock_snaps * 0.02)
        entity._perception_dampen = _perception_dampen
        entity._lock_snaps = _lock_snaps
        _lock_boredom = _lock_snaps * 0.005
        entity.adjust("boredom", _lock_boredom)
        if _lock_snaps > 10:
            _trace("meta_perception_dampen", True, {
                "lock_snaps": _lock_snaps,
                "dampen": round(_perception_dampen, 3),
                "lock_boredom": round(_lock_boredom, 4),
            })
    except Exception as e:
        entity._perception_dampen = 1.0
        _trace("meta_perception_dampen", False, {}, str(e))

    # ---- Step 7.7: Boredom 独立激活（v11）----
    try:
        _eff_ema = entity.quenching_eff_rolling
        _boredom_delta = (1.0 - _eff_ema) * 0.05
        entity.adjust("boredom", _boredom_delta)
        entity.adjust("approach_explore", entity.boredom * 0.20)
        entity.adjust("somatic_tone", -entity.boredom * 0.15)
        entity.boredom *= 0.99
        _trace("boredom_activation", True, {
            "eff_ema": round(_eff_ema, 3),
            "boredom_delta": round(_boredom_delta, 4),
            "boredom": round(entity.boredom, 3),
        })
    except Exception as e:
        _trace("boredom_activation", False, {}, str(e))

    # ---- Step 7.9: 自适应蒙特卡洛训练随机化（v11.1）----
    try:
        _frozen = getattr(entity, "_freeze_state", False)
        if daemon_mode and not _frozen:
            _lock_snaps = getattr(entity, "_lock_snaps", 0)
            _sigma_base = 0.03
            _vocab_diversity = 1.0
            try:
                from ...language_system.meta_cognitive import MetaCognitive
                _mc = MetaCognitive()
                _diagnosis = _mc.diagnose(entity.to_state_snapshot())
                _vocab_diversity = _diagnosis.get("vocabulary_diversity", 1.0)
            except Exception:
                pass
            _sigma = _sigma_base * (1.0 + _lock_snaps * 0.10)
            _sigma = _sigma / (1.0 + _vocab_diversity * 0.5)
            _sigma = min(_sigma, 0.12)

            _dims = ["somatic_tone", "loneliness", "energy", "boredom",
                     "unresolved", "stress", "danger_level", "fatigue"]
            _all_targets = _dims + ["approach_social", "approach_explore", "approach_urgency"]
            _n_perturb = max(3, len(_all_targets) // 3)
            _perturb = set(_random.sample(_all_targets, _n_perturb))
            for _dim in _dims:
                if _dim not in _perturb:
                    continue
                _PERTURB_SCALE = {"somatic_tone": 2.0}
                _step = _random.gauss(0, _sigma)
                entity.adjust(_dim, _step * _PERTURB_SCALE.get(_dim, 1.0))
            for _sub in ["approach_social", "approach_explore", "approach_urgency"]:
                if _sub not in _perturb:
                    continue
                _val = getattr(entity, _sub, 0.0)
                setattr(entity, _sub, max(0.0, min(1.0,
                    _val + _random.gauss(0, _sigma * 0.75))))
            if entity.tick % 10 == 0:
                logger.info(
                    f"[TrainingMC] σ={_sigma:.3f} lock={_lock_snaps} "
                    f"somatic={entity.somatic_tone:.2f} "
                    f"loneliness={entity.loneliness:.2f}(c={entity.loneliness_core:.2f}/s={entity.loneliness_surface:.2f}) "
                    f"boredom={entity.boredom:.2f}"
                )
            _trace("training_mc", True, {
                "sigma": round(_sigma, 4),
                "lock_snaps": _lock_snaps,
                "somatic": round(entity.somatic_tone, 3),
                "loneliness": round(entity.loneliness, 3),
                "boredom": round(entity.boredom, 3),
            })
    except Exception:
        pass

    # ---- Step 7.9b: 反锁推力（v11.2）----
    try:
        _frozen = getattr(entity, "_freeze_state", False)
        if not _frozen:
            _snaps = entity.snapshots
            if _snaps and len(_snaps) >= 8:
                _recent = _snaps[-15:] if len(_snaps) >= 15 else _snaps[-8:]
                _neutral_map = {
                    "somatic_tone": 0.0, "loneliness": 0.3, "energy": 0.5,
                    "boredom": 0.2, "unresolved": 0.2, "stress": 0.1,
                    "danger_level": 0.0, "fatigue": 0.1,
                    "approach_drive": 0.5, "avoid_drive": 0.5,
                    "approach_social": 0.5, "approach_explore": 0.5, "approach_urgency": 0.5,
                }
                _lock = getattr(entity, "_lock_snaps", 0)
                _lock_factor = min(_lock / 20.0, 1.0) if _lock > 0 else 0.0

                for _dim, _neutral in _neutral_map.items():
                    _vals = [s.get(_dim, _neutral) for s in _recent]
                    _mean = sum(_vals) / len(_vals)
                    _deviation = abs(_mean - _neutral)
                    if _deviation < 0.25:
                        continue
                    _variance = sum((v - _mean) ** 2 for v in _vals) / len(_vals)
                    if _variance > 0.005:
                        continue
                    _current = getattr(entity, _dim, _mean)
                    _stuck_ratio = min(_deviation / 0.5, 1.0)
                    _force = (_neutral - _current) * _stuck_ratio * 0.10 * (1.0 + _lock_factor)
                    entity.adjust(_dim, _force)

                if entity.tick % 10 == 0 and _lock_factor > 0:
                    _stuck_dims = []
                    for _dim, _neutral in _neutral_map.items():
                        _vals = [s.get(_dim, _neutral) for s in _recent]
                        _mean = sum(_vals) / len(_vals)
                        _deviation = abs(_mean - _neutral)
                        if _deviation >= 0.25:
                            _variance = sum((v - _mean) ** 2 for v in _vals) / len(_vals)
                            if _variance <= 0.002:
                                _stuck_dims.append(f"{_dim}={getattr(entity, _dim, 0):.2f}")
                    if _stuck_dims:
                        logger.info(
                            f"[AntiLock] lock_factor={_lock_factor:.2f} "
                            f"pushing: {', '.join(_stuck_dims)}"
                        )
    except Exception:
        pass

    # ---- Step 7.9c: 物理约束检查（v11.1）----
    try:
        _e, _f = entity.energy, entity.fatigue
        _excess_1 = max(0.0, _e + _f - 1.3) / 2
        entity.energy = max(0.0, _e - _excess_1)
        entity.fatigue = max(0.0, _f - _excess_1)

        _pain_limit = 0.4 + max(0.0, entity.somatic_tone - 0.3) * 0.3
        _pain_excess = max(0.0, entity.pain - _pain_limit)
        entity.pain = entity.pain - _pain_excess

        _dp = entity.danger_level * entity.approach_social
        _excess_3 = max(0.0, _dp - 0.5) / 2
        entity.danger_level = max(0.0, entity.danger_level - _excess_3)
        entity.approach_social = max(0.0, entity.approach_social - _excess_3)

        _fu = entity.fatigue * entity.approach_urgency
        _excess_4 = max(0.0, _fu - 0.4) / 2
        entity.fatigue = max(0.0, entity.fatigue - _excess_4)
        entity.approach_urgency = max(0.0, entity.approach_urgency - _excess_4)

        _a, _av = entity.approach_drive, entity.avoid_drive
        _a_over = max(0.0, _a - 0.6)
        _av_over = max(0.0, _av - 0.6)
        _joint = min(_a_over, _av_over)
        entity.approach_drive = max(0.0, _a - _joint * 0.5)
        entity.avoid_drive = max(0.0, _av - _joint * 0.5)

        _violations = _excess_1 + _pain_excess + _excess_3 + _excess_4 + _joint
        _trace("mc_constraints", True, {"violations_total": round(_violations, 4)})
    except Exception:
        pass

    # ---- Step 7.10: danger → 独立 avoid 通路（v11.1）----
    try:
        _lock_snaps = getattr(entity, "_lock_snaps", 0)
        _lock_depth = max(0.0, (_lock_snaps - 10) / 10.0)
        _inefficiency = 1.0 - entity.quenching_eff_rolling
        _danger_delta = _lock_depth * _inefficiency * 0.03
        if _danger_delta > 0:
            entity.adjust("danger_level", _danger_delta)
        entity.danger_level = max(0.0, entity.danger_level * 0.95)
        _danger_avoid = entity.danger_level * 0.50
        if _danger_avoid > 0.001:
            entity.adjust("avoid_drive", _danger_avoid)
            entity.adjust("stress", entity.danger_level * 0.20)
            if entity.tick % 20 == 0:
                _trace("danger_amygdala", True, {
                    "danger": round(entity.danger_level, 4),
                    "avoid_push": round(_danger_avoid, 4),
                    "lock_depth": round(_lock_depth, 3),
                    "inefficiency": round(_inefficiency, 3),
                })
    except Exception:
        pass

    # ---- Step 7.11: fatigue → 全局感知阻尼（v11.1）----
    try:
        _fatigue_delta = entity.stress * 0.015
        entity.adjust("fatigue", _fatigue_delta)
        entity.fatigue = max(0.0, entity.fatigue * 0.998)
        _fatigue_gain = 1.0 / (1.0 + entity.fatigue * 2.0)
        _current_dampen = getattr(entity, "_perception_dampen", 1.0)
        entity._perception_dampen = _current_dampen * _fatigue_gain
        if entity.tick % 20 == 0 and entity.fatigue > 0.3:
            _trace("fatigue_damping", True, {
                "fatigue": round(entity.fatigue, 4),
                "stress": round(entity.stress, 4),
                "fatigue_gain": round(_fatigue_gain, 4),
                "combined_dampen": round(entity._perception_dampen, 4),
            })
    except Exception:
        pass

    # ---- Step 7.12: unresolved → 内省模式（v11.1）----
    try:
        _cuw = getattr(entity, "_conflict_to_unresolved_weights", {})
        _conflict = min(entity.approach_drive, entity.avoid_drive)
        _unresolved_delta = _conflict * _cuw.get("conflict_rate", 0.04)
        if _unresolved_delta > 0.001:
            entity.adjust("unresolved", _unresolved_delta)
        _ur_baseline = 0.05
        _ur_decay = _cuw.get("unresolved_decay", 0.98)
        entity.unresolved = _ur_baseline + (entity.unresolved - _ur_baseline) * _ur_decay
        _external_gain = 1.0 / (1.0 + entity.unresolved * _cuw.get("introspection_gain", 1.5))
        _current_dampen = getattr(entity, "_perception_dampen", 1.0)
        entity._perception_dampen = _current_dampen * _external_gain
        if entity.tick % 20 == 0 and entity.unresolved > 0.4:
            _trace("introspection_mode", True, {
                "unresolved": round(entity.unresolved, 4),
                "conflict": round(_conflict, 4),
                "external_gain": round(_external_gain, 4),
                "combined_dampen": round(entity._perception_dampen, 4),
            })
    except Exception:
        pass

    # ---- Step 7.13: pain 激活（v11.1）----
    try:
        _somatic_pain = max(0.0, -entity.somatic_tone - 0.2) * 0.03
        _threat_pain = entity.stress * entity.danger_level * 0.05
        _pain_delta = _somatic_pain + _threat_pain
        if _pain_delta > 0:
            entity.adjust("pain", _pain_delta)
        entity.pain = max(0.0, entity.pain * 0.98)
        if entity.tick % 20 == 0 and entity.pain > 0.2:
            _trace("pain_activation", True, {
                "pain": round(entity.pain, 4),
                "somatic_pain": round(_somatic_pain, 4),
                "threat_pain": round(_threat_pain, 4),
            })
    except Exception:
        pass

    # ---- Step 7.14: relief_debt 激活（v11.1）----
    try:
        _inefficiency = 1.0 - entity.quenching_eff_rolling
        _debt_delta = _inefficiency * entity.unresolved * 0.02
        if _debt_delta > 0:
            entity.adjust("relief_debt", _debt_delta)
        entity.relief_debt = max(0.0, entity.relief_debt * 0.99)
        if entity.tick % 20 == 0 and entity.relief_debt > 0.3:
            _trace("relief_debt_activation", True, {
                "relief_debt": round(entity.relief_debt, 4),
                "inefficiency": round(_inefficiency, 3),
                "unresolved": round(entity.unresolved, 3),
            })
    except Exception:
        pass
