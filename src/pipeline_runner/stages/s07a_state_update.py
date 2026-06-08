"""Stage 07a — 状态回写 + BP Tick + 消力系统六通道（Steps 11, 11.5, 接入点7）。

职责：
  Step 11   — update_state 写入 + 语言消力反馈 + 问题张力注入 + 反馈回路
              + coherence delta + loneliness trace
  Step 11.5 — BP 压制 Tick 递减 + 长期效果 + long_term_bias 衰减
  [接入点 7] — 消力系统六通道（apply_all_quenching）

输入：ctx._trace, ctx._snapshot_dict, ctx.state_snapshot, ctx.somatic_tone_start,
      ctx.emergent_tension, ctx.emergent_action, ctx.emergent_priority,
      ctx.decision, ctx.thought_packet, ctx.raw_input,
      ctx._question_tension, ctx._cx_parse_result, ctx.mainline_result,
      ctx.connection_depth_eff, ctx.loneliness_target,
      ctx.loneliness_intermediates, ctx.connection_trace

输出：ctx._ur_before_quench, ctx._ur_after_quench,
      ctx._lone_surf_before, ctx._lone_surf_after_quench,
      ctx._boredom_before, ctx._boredom_after_quench,
      ctx._state_for_update, ctx._unresolvable_episodes
"""

import logging
import time
from typing import Dict, List, Optional

from ...state_update.update_engine import update_state
from ...state_update.compute_coherence import append_delta as append_coherence_delta
from ...observation.behavior_trace import build_loneliness_trace, _infer_loneliness_reason

logger = logging.getLogger(__name__)

_DRIVE_WRITE_WHITELIST = frozenset({
    "energy", "loneliness", "loneliness_core", "loneliness_surface",
    "unresolved", "boredom", "fatigue", "stress", "relief_debt", "pain",
    "info_gap", "external_change_rate",
    "somatic_tone", "danger_level", "approach_drive", "avoid_drive",
    "approach_social", "approach_explore", "approach_urgency",
    "joy", "anger", "fear", "sadness", "disgust", "anxiety", "surprise",
    "curiosity", "serenity", "excitement",
})

# ① 提纯（PLAN_self_counsel §6.2）：① 旧消力的孤独表层贷款 + unresolved 无差别释放
# 已迁入 self_counsel（带贷款条款 A/B + 困惑可答性闸）。① 在此只留"纯宣泄反射"——
# 吐字本身的一丝即时体感安慰，真实但浅。系数从旧 somatic_comfort(0.15) 缩到 0.05，
# 与孤独反馈 dict 解耦（自我开导的体感安慰由 self_counsel._SC_SOMA_COMFORT 承载）。
_VENT_SOMA_COMFORT = 0.05

# 完整性伤害 → 真实体感（PLAN_integrity_pain_revival §3-C，bcyq 2026-05-30 锁定）：
# active_harm 原本只飘在驱动力 delta 上，从不落到痛觉/身体 → 改文件她"什么都不疼"。
# 两条通道一起走：尖锐痛觉 + 沉闷身体不适，更接近真实手术的体感。系数取偏小值先跑。
# pain 只被 s04a 衰减（×0.98）从不被覆盖 → 此处可安全累加，急性痛会自然愈合。
_HARM_TO_PAIN = 0.30   # active_harm → pain += （痛觉通道，[0,1] 钳位）
_HARM_TO_SOMA = 0.20   # active_harm → somatic_tone -= （身体不适通道，[-1,1] 钳位）

# 她每 tick 都在用的四个"部位"——感知/表达/认知/连续性。每 tick 各记一次访问，
# access_count 单调增 → 绑定随她活得越久越深（"越常用越疼"+"在意只增不减"）。
_INHABITED_ZONES = ("perception", "expression", "cognition", "continuity")


def run_stage(ctx, entity) -> None:  # noqa: C901
    _trace = ctx._trace
    _snapshot_dict = ctx._snapshot_dict
    state_snapshot = ctx.state_snapshot
    somatic_tone_start = ctx.somatic_tone_start
    emergent_tension = ctx.emergent_tension
    emergent_action = ctx.emergent_action
    emergent_priority = ctx.emergent_priority
    decision = ctx.decision
    thought_packet = ctx.thought_packet
    raw_input = ctx.raw_input
    _question_tension = ctx._question_tension
    _cx_parse_result = ctx._cx_parse_result
    mainline_result = ctx.mainline_result
    connection_depth_eff = ctx.connection_depth_eff
    loneliness_target = ctx.loneliness_target
    loneliness_intermediates = ctx.loneliness_intermediates
    connection_trace = ctx.connection_trace

    has_social_input = bool(raw_input and str(raw_input).strip())

    # ---- Step 11: 状态更新（基于决策结果）----
    logger.info(f"[PreSnapshot DIAG] entity.loneliness_core={entity.loneliness_core!r} loneliness_target={loneliness_target!r}")
    state_for_update = dict(entity.to_state_snapshot())
    state_for_update["_last_prediction_error"] = entity._last_prediction_error
    state_for_update["pending_surprises"] = list(getattr(entity, "pending_surprises", []))
    if loneliness_target is not None:
        state_for_update["_loneliness_target_override"] = loneliness_target
    unresolvable_episodes: List[Dict] = []

    # consumed in L3b
    _ur_before_quench: Optional[float] = None
    _ur_after_quench: Optional[float] = None
    _lone_surf_before: Optional[float] = None
    _lone_surf_after_quench: Optional[float] = None
    _boredom_before: Optional[float] = None
    _boredom_after_quench: Optional[float] = None

    try:
        idle_seconds = time.time() - entity.last_update_time
        new_state = update_state(
            current_state=state_for_update,
            decision=decision,
            idle_seconds=idle_seconds,
            param_snapshot=_snapshot_dict,
            time_injected_fields=entity._time_injected_fields,
            wm_rules=entity.wm_rules,
            pending_surprises_episodes=unresolvable_episodes,
        )
        entity.energy = max(0.0, min(1.0, new_state.get("energy", entity.energy)))
        entity.loneliness_core = max(0.0, min(1.0, new_state.get("loneliness_core", entity.loneliness_core)))
        entity.loneliness_surface = max(0.0, min(1.0, new_state.get("loneliness_surface", entity.loneliness_surface)))
        entity.loneliness = max(0.0, min(1.0, new_state.get("loneliness", entity.loneliness)))
        logger.info(f"[Step11 DIAG] after writeback core={entity.loneliness_core:.4f} surf={entity.loneliness_surface:.4f} ns_core={new_state.get('loneliness_core')!r}")
        entity._sync_loneliness()
        entity.unresolved = max(0.0, min(1.0, new_state.get("unresolved", entity.unresolved)))
        entity.boredom = max(0.0, min(1.0, new_state.get("boredom", entity.boredom)))
        entity.info_gap = max(0.0, min(1.0, new_state.get("info_gap", entity.info_gap)))

        # ---- 语言消力反馈（v7.0）----
        _ur_before_quench = entity.unresolved
        _lone_surf_before = entity.loneliness_surface
        _boredom_before = entity.boredom
        _lang_score = float(getattr(entity, "_language_best_score", 0.0))
        if _lang_score > 0.10:
            _rep_discount = 1.0
            try:
                _qt = getattr(entity, "_quenching_tracker", None)
                _expr = str(getattr(entity, "_language_best_expression", ""))
                if _qt and _expr:
                    _rdp = getattr(entity, "_repetition_decay_params", {})
                    _rep_discount = _qt.get_repetition_discount(_expr, entity.tick, _rdp)
            except Exception:
                pass
            _qfw = getattr(entity, "_quench_feedback_weights", {})
            _quench = _lang_score * _qfw.get("quench_rate", 0.25) * _rep_discount
            # ① 提纯（PLAN_self_counsel §6.2）：孤独表层贷款（loneliness_surface）+
            # unresolved 无差别释放已迁入 self_counsel（带条款 + 可答性闸）。① 在此
            # 只留纯宣泄反射：一丝即时体感安慰 + 动作驱力/无聊的就地释放。
            entity.approach_drive = max(0.0, entity.approach_drive - _quench * _qfw.get("approach_release", 0.3))
            entity.avoid_drive = max(0.0, entity.avoid_drive - _quench * _qfw.get("avoid_release", 0.3))
            entity.somatic_tone = min(1.0, entity.somatic_tone + _quench * _VENT_SOMA_COMFORT)
            entity.boredom = max(0.0, entity.boredom - _quench * _qfw.get("boredom_release", 0.10))

        _ur_after_quench = entity.unresolved
        _lone_surf_after_quench = entity.loneliness_surface
        _boredom_after_quench = entity.boredom

        # ---- 问题张力注入（Step 7.5 延迟的部分）----
        if _question_tension > 0:
            entity.unresolved = min(1.0, entity.unresolved + _question_tension)

        # ---- 反馈回路（v1.0）----
        try:
            from ...feedback_loop import compute_acute_feedback, update_chronic_tracker
            _lang_score_fb = float(getattr(entity, "_language_best_score", 0.0))
            _acute = compute_acute_feedback(_lang_score_fb, entity)
            for _dim, _val in _acute.items():
                if _dim not in _DRIVE_WRITE_WHITELIST:
                    continue
                _old = getattr(entity, _dim, 0.0)
                setattr(entity, _dim, max(0.0, min(1.0, _old + _val)))
            update_chronic_tracker(_lang_score_fb, entity)
        except Exception:
            pass

        # ---- curiosity 自然衰减：向 drive_vector_final["curiosity"] 缓慢漂移 ----
        try:
            _curiosity_target = float(
                getattr(ctx, "drive_vector_final", {}).get("curiosity", entity.curiosity)
            )
            _curiosity_cur = float(getattr(entity, "curiosity", 0.5))
            entity.curiosity = max(0.0, min(1.0,
                _curiosity_cur * 0.95 + _curiosity_target * 0.05
            ))
        except Exception:
            pass

        entity.fatigue = max(0.0, min(1.0, new_state.get("fatigue", entity.fatigue)))
        entity.stress = max(0.0, min(1.0, new_state.get("stress", entity.stress)))
        entity.relief_debt = max(0.0, min(1.0, new_state.get("relief_debt", entity.relief_debt)))
        entity.somatic_tone = max(-1.0, min(1.0, new_state.get("somatic_tone", entity.somatic_tone)))
        entity.approach_drive = max(0.0, min(1.0, new_state.get("approach_drive", entity.approach_drive)))
        entity.avoid_drive = max(0.0, min(1.0, new_state.get("avoid_drive", entity.avoid_drive)))
        entity.approach_drive = max(0.0, entity.approach_drive * 0.95)
        entity.avoid_drive = max(0.0, entity.avoid_drive * 0.95)
        entity.danger_level = max(0.0, min(1.0, new_state.get("danger_level", entity.danger_level)))
        _social_reset = float(has_social_input)
        entity.time_since_last_social = (entity.time_since_last_social + idle_seconds) * (1.0 - _social_reset)
        entity.time_since_last_info = (entity.time_since_last_info + idle_seconds) * (1.0 - _social_reset)
        entity.last_update_time = time.time()
        entity.tick += 1
        try:
            from ...feedback_loop import decay_chronic_tracker
            decay_chronic_tracker(entity)
        except Exception:
            pass
        # ---- 回应压力 ----
        if _cx_parse_result:
            _comp = _cx_parse_result.get("comprehension", 0.0)
            _rp = getattr(entity, "_response_pressure_params", {})
            _rp_coeff = _rp.get("coefficient", 0.03)
            entity.unresolved = min(1.0, entity.unresolved + _comp * _rp_coeff)

        # V5: 代谢物衰减
        m = getattr(entity, "failure_metabolite", 0.0)
        _failure_floor = len(getattr(entity, "pending_failures", [])) * 0.05
        entity.failure_metabolite = max(_failure_floor, m - 0.03)
        if m > 0.01:
            _fmw = getattr(entity, "_failure_metabolite_weights", {})
            entity.approach_drive = max(0.0, entity.approach_drive - m * _fmw.get("approach_suppress", 0.15))
            entity.avoid_drive = min(1.0, entity.avoid_drive + m * _fmw.get("avoid_increase", 0.12))
            entity.curiosity = max(0.0, getattr(entity, "curiosity", 0.5) - m * _fmw.get("curiosity_suppress", 0.10))
            entity.somatic_tone = max(-1.0, entity.somatic_tone - m * _fmw.get("somatic_damage", 0.08))
        _now_ts = time.time()
        _pf = getattr(entity, "pending_failures", [])
        if _pf:
            entity.pending_failures = [
                f for f in _pf
                if _now_ts - (f.get("timestamp", _now_ts) if isinstance(f, dict)
                              else getattr(f, "timestamp", _now_ts)) < 1800
            ]
        entity.pending_surprises = list(new_state.get("pending_surprises", []))

        # ---- Step 11b: 追加 coherence delta ----
        prev_energy = float(state_for_update.get("energy", 0.8))
        energy_delta = entity.energy - prev_energy
        somatic_tone_delta = float(getattr(entity, "somatic_tone", 0.0)) - somatic_tone_start
        tension_delta = emergent_tension - float(state_snapshot.get("tension_level", emergent_tension))
        if hasattr(entity, "recent_deltas") and entity.recent_deltas is not None:
            append_coherence_delta(
                entity.recent_deltas,
                somatic_tone_delta=somatic_tone_delta,
                energy_delta=energy_delta,
                tension_delta=tension_delta,
                timestamp=time.time(),
            )

        cleared = new_state.get("_time_injected_cleared", set())
        for dim in cleared:
            entity._time_injected_fields.discard(dim)
        _trace("state_update", True, {
            "energy": entity.energy,
            "fatigue": entity.fatigue,
            "tick": entity.tick,
            "pending_surprises": len(entity.pending_surprises),
            "connection_depth": round(connection_depth_eff, 4),
            "loneliness": entity.loneliness,
        })

        # ---- Step 11 追加：构造 loneliness_trace ----
        prev_loneliness_for_trace = float(state_for_update.get("loneliness", 0.3))
        loneliness_reason = _infer_loneliness_reason(
            recovery=loneliness_intermediates.get("recovery_component", 0.0),
            accumulation=loneliness_intermediates.get("accumulation_component", 0.0),
            loneliness_before=prev_loneliness_for_trace,
            loneliness_after=entity.loneliness,
            silence_duration=time.time() - entity.last_interaction_timestamp if hasattr(entity, "last_interaction_timestamp") else entity.time_since_last_social,
            social_input_present=has_social_input,
        ) if loneliness_target is not None else "neutral"

        loneliness_trace = build_loneliness_trace(
            tick=entity.tick,
            loneliness_before=prev_loneliness_for_trace,
            loneliness_after=entity.loneliness,
            loneliness_target=loneliness_target,
            recovery_component=loneliness_intermediates.get("recovery_component", 0.0),
            accumulation_component=loneliness_intermediates.get("accumulation_component", 0.0),
            release_lag=loneliness_intermediates.get("release_lag", 0.7),
            reason=loneliness_reason,
        )

        buf = getattr(entity, "observation_buffer", None)
        if buf is not None:
            try:
                from ...observation.behavior_trace import build_memory_trace
                memory_trace = build_memory_trace(
                    mainline_result=mainline_result,
                    branch_result=thought_packet.get("branch_memories", []) if thought_packet else [],
                    entity_state=entity,
                )
            except Exception:
                memory_trace = {}

            buf.append({
                "tick": entity.tick,
                "connection_trace": connection_trace if connection_trace else {},
                "loneliness_trace": loneliness_trace,
                "memory_trace": memory_trace,
                "connection_depth": connection_depth_eff,
                "loneliness": entity.loneliness,
            })

    except Exception as e:
        entity.last_update_time = time.time()
        entity.tick += 1
        m = getattr(entity, "failure_metabolite", 0.0)
        entity.failure_metabolite = max(0.0, m - 0.03)
        if m > 0.01:
            entity.approach_drive = max(0.0, entity.approach_drive - m * 0.15)
            entity.avoid_drive = min(1.0, entity.avoid_drive + m * 0.12)
            entity.curiosity = max(0.0, getattr(entity, "curiosity", 0.5) - m * 0.10)
            entity.somatic_tone = max(-1.0, entity.somatic_tone - m * 0.08)
        _trace("state_update", False, {}, str(e))

    # ---- Step 11.5: BP 压制Tick递减 + 长期效果 + bias 衰减 ----
    try:
        from ...core import behavior_patterns as bp
        bp.get_pool().tick_suppress()
        action_history = [s.get("action_type", "") for s in entity.snapshots[-20:]]
        bp.get_pool().compute_long_term_effects(entity.tick, entity.snapshots, action_history)
        if hasattr(entity, "long_term_bias"):
            for drive, val in entity.long_term_bias.items():
                rate = 0.99 if abs(val) > 0.2 else 0.97
                entity.long_term_bias[drive] = val * rate
    except Exception:
        pass

    # =========================================================================
    # [接入点 7] Step 11.5 后：消力系统（六通道）
    # =========================================================================
    try:
        from ...quenching_system import apply_all_quenching, QuenchingJournal

        _qj = getattr(entity, "_quenching_journal", None)
        if _qj is None:
            _qj = QuenchingJournal()
            entity._quenching_journal = _qj

        _user_interacted = bool(raw_input and str(raw_input).strip())

        _QUENCH_ACTIONS = {"sleep": "sleep", "rest": "rest", "avoid": "avoid", "vent": "vent", "explore": "explore"}
        _q_result = apply_all_quenching(
            entity=entity,
            emergent_action=emergent_action or "idle",
            emergent_priority=emergent_priority or 0.0,
            emergent_tension=emergent_tension or 0.0,
            user_interacted=_user_interacted,
            behavior_action=_QUENCH_ACTIONS.get(emergent_action, ""),
            dt=1.0,
            journal=_qj,
        )

        if _q_result.get("total_delta_unresolved", 0.0) > 0.001:
            _trace("quenching_system", True, {
                "total_Δur": _q_result["total_delta_unresolved"],
                "channels": list(_q_result["channel_deltas"].keys()),
                "efficiency": _q_result["efficiency"],
            })
        _ch_parts = []
        for ch, deltas in _q_result["channel_deltas"].items():
            if any(abs(v) > 0.0005 for v in deltas.values()):
                ur = abs(deltas.get("unresolved", 0))
                _ch_parts.append(f"{ch}:{ur:.3f}")
        if _ch_parts:
            _ls = getattr(entity, "loneliness_surface", 0)
            _lc = getattr(entity, "loneliness_core", 0)
            _ax = getattr(entity, "anxiety", 0)
            _sd = getattr(entity, "sadness", 0)
            _ag = getattr(entity, "anger", 0)
            logger.info(
                f"[Quench] t={entity.tick} channels=[{', '.join(_ch_parts)}] "
                f"lone={entity.loneliness:.3f}(s={_ls:.3f}/c={_lc:.3f}) "
                f"emo:anx={_ax:.3f} sad={_sd:.3f} ang={_ag:.3f}"
            )
    except Exception as e:
        _trace("quenching_system", False, {}, str(e))

    # =========================================================================
    # [接入点 8] Step 12：完整性感知系统
    # =========================================================================
    try:
        from pathlib import Path as _Path
        from ...core.integrity_monitor import scan as _integrity_scan
        from ...core.integrity_signal import update as _integrity_update
        from ...core.integrity_signal import apply_drive_bias as _integrity_apply_drive_bias
        from ...core.self_binding import record_accesses as _record_accesses
        _project_root = _Path(__file__).parents[3]
        _data_dir     = _project_root / "data"
        # 每 tick 记一次"她用了这些部位"——绑定随使用单调累积（地板兜底冷启动）。
        _record_accesses(_INHABITED_ZONES, _data_dir)
        _events       = _integrity_scan(_data_dir, _project_root, entity.tick)
        _ir           = _integrity_update(_events, entity, _data_dir)
        # 驱动力影响：有界瞬态偏置（回收上拍+注入本拍），净效果=当前 drive_delta，
        # 不随 tick 积分——避免隐痛底每拍 additive 把驱动力推到饱和。
        entity.integrity_drive_bias = _integrity_apply_drive_bias(
            entity, _ir["drive_delta"], getattr(entity, "integrity_drive_bias", {}) or {}
        )
        entity.integrity_behavior_bias = _ir.get("behavior_bias", {})
        entity.active_harm             = float(_ir.get("active_harm", 0.0))
        # 急性体感：只接收上升沿（update 基于持久化 zone_harms 算 prev，跨 daemon 重启
        # 连续 → 持久隐痛底不会被当新伤造成虚假痛脉冲）。衰减/隐痛底 rise=0，下降留给
        # pain 自身（s04a ×0.98）与 somatic 自然恢复，形成急性痛+自愈。
        _harm_rise = float(_ir.get("harm_rise", 0.0))
        _cur_pain = float(getattr(entity, "pain", 0.0))
        entity.pain = max(0.0, min(1.0, _cur_pain + _harm_rise * _HARM_TO_PAIN))
        _cur_tone = float(getattr(entity, "somatic_tone", 0.0))
        entity.somatic_tone = max(-1.0, min(1.0, _cur_tone - _harm_rise * _HARM_TO_SOMA))
    except Exception:
        pass

    # ---- 输出跨阶段变量 ----
    ctx._ur_before_quench = _ur_before_quench
    ctx._ur_after_quench = _ur_after_quench
    ctx._lone_surf_before = _lone_surf_before
    ctx._lone_surf_after_quench = _lone_surf_after_quench
    ctx._boredom_before = _boredom_before
    ctx._boredom_after_quench = _boredom_after_quench
    ctx._state_for_update = state_for_update
    ctx._unresolvable_episodes = unresolvable_episodes
