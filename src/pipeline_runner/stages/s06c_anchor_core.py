"""Stage 06c — Daemon Anchor 输出内核。

职责：daemon/no_llm 模式下的锚点表达匹配、叙事/锚点竞争决策、
      表达消力记录、模板学习、构式习得、内源校准。

本文件在 s06b_output.py 的 try 块内被调用。
返回：{"text": str, "best_word": str, "second_word": str,
       "best_score": float, "anchor_display_w": float}
"""

import logging
import math as _d_math
import random as _rnd
from datetime import datetime, timezone

from ...language_system import QuenchingTracker
from ...language_system.sentence_composer import PATTERNS
from ...language_training import match_anchor_expression
from ...observability import observe_block

logger = logging.getLogger(__name__)

def run_anchor_core(entity, raw_input, _cx_parse_result, _narrative_text, _is_wakeup_tick, _trace):
    """
    Daemon/no_llm 锚点表达内核。在 s06b_output.py 的 try 块内调用。
    """
    # -------------------------------------------------------------------------
    def _enrich_state(_real_state):
        """心事衰减 + 概念图 + 输入包 + 叙事/代词偏置。"""
        from ...language_system.concept_graph import (
            activate_concepts, record_exposure, scan_text_for_concepts,
        )
        from ...language_system.input_packet import build_input_packet
        from ...language_system.preoccupation_engine import (
            tick_decay as _pre_decay, add_or_refresh as _pre_add,
            soothe as _pre_soothe, project_to_state as _pre_project,
            get_top_preoccupation as _pre_top,
        )
        # 心事系统：每 tick 衰减
        with observe_block("s06c:preoccupation_decay"):
            _pre_decay(entity)
        # 概念图激活
        with observe_block("s06c:concept_graph"):
            _cg_from_vocab = [w for w, _ in _cx_parse_result.get("recognized_words", [])]
            _cg_from_text = scan_text_for_concepts(raw_input or "")
            _cg_words = list(dict.fromkeys(_cg_from_vocab + _cg_from_text))
            _concept_bias = activate_concepts(_cg_words, entity)
            _st_refs = _cx_parse_result.setdefault("state_references", {})
            for _dim, _delta in _concept_bias.items():
                _st_refs[_dim] = _st_refs.get(_dim, 0.0) + _delta * 0.6
            _cg_snap = dict(_real_state)
            for _cg_w in _cg_words:
                record_exposure(_cg_w, entity, _cg_snap)
        # 输入包
        with observe_block("s06c:input_packet"):
            _concept_bias_ref = locals().get("_concept_bias", {})
            _input_packet = build_input_packet(raw_input or "", _concept_bias_ref)
            _cx_parse_result["input_packet"] = _input_packet
            _st_refs = _cx_parse_result.setdefault("state_references", {})
            for _dim, _strength in _input_packet["topic_anchor"].items():
                _st_refs[_dim] = _st_refs.get(_dim, 0.0) + _strength * 0.5
            _other = _input_packet["social_intent"].get("other", 0.0)
            for _dim, _delta in _concept_bias_ref.items():
                _st_refs[_dim] = _st_refs.get(_dim, 0.0) + _delta * _other * 0.4
            _q = _input_packet["social_intent"].get("question", 0.0)
            _st_refs["curiosity"] = _st_refs.get("curiosity", 0.0) + _q * 0.05
            _real_state["_input_other"] = _input_packet["relational_direction"].get("other", 0.0)
            _real_state["_input_sharing"] = _input_packet["social_intent"].get("sharing", 0.0)
        # 输入 → 心事触发
        with observe_block("s06c:preoccupation_trigger"):
            _other_w = _real_state.get("_input_other", 0.0)
            _sharing_w = _real_state.get("_input_sharing", 0.0)
            _trigger_w = _other_w * _sharing_w
            _NEG_WORDS = ("累", "难过", "撑不住", "烦", "怕", "孤独", "孤单",
                           "想", "担心", "不安", "累的", "委屈", "焦虑", "害怕")
            _POS_WORDS = ("开心", "好极", "高兴", "兴奋", "棒", "舒服", "安心")
            _neg_hits = sum((raw_input or "").count(w) for w in _NEG_WORDS)
            _pos_hits = sum((raw_input or "").count(w) for w in _POS_WORDS)
            _total_hits = _neg_hits + _pos_hits
            _neg_share = _neg_hits / max(1, _total_hits)
            _intensity_base = 0.30 + min(0.40, _total_hits * 0.08)
            _intensity = _intensity_base * _trigger_w
            if _total_hits > 0 and _intensity > 0.05:
                _pre_add(entity, about="speaker", p_type="担心",
                         initial_intensity=_intensity * _neg_share)
                _pre_add(entity, about="speaker", p_type="期待",
                         initial_intensity=_intensity * (1.0 - _neg_share))
            _COMFORT_WORDS = ("没事", "别担心", "没关系", "别怕", "我在", "陪着你", "在的")
            if sum((raw_input or "").count(w) for w in _COMFORT_WORDS) > 0:
                _pre_soothe(entity, about="self")
                _pre_soothe(entity, about="speaker")
        # 心事 → _real_state 偏置注入
        with observe_block("s06c:preoccupation_bias"):
            _pre_bias = _pre_project(entity)
            for _dim, _delta in _pre_bias.items():
                _cur = float(_real_state.get(_dim, 0.0))
                _real_state[_dim] = min(1.0, max(-1.0, _cur + _delta))
            _top = _pre_top(entity)
            if _top:
                _about = _top.get("about", "")
                _about_display = "你" if _about == "speaker" else _about
                _real_state["_preoccupation_about"] = _about_display
                _real_state["_preoccupation_intensity"] = float(_top.get("intensity", 0.0))
                _real_state["_preoccupation_type"] = _top.get("type", "")
        # 自我叙事染色
        with observe_block("s06c:narrative_bias"):
            _NARRATIVE_BIAS_SCALE, _NARRATIVE_BIAS_MAX = 0.6, 0.08
            _narr_bias = getattr(entity, "_narrative_bias", None) or {}
            for _dim, _delta in _narr_bias.items():
                if not isinstance(_dim, str): continue
                try:
                    _scaled = max(-_NARRATIVE_BIAS_MAX, min(_NARRATIVE_BIAS_MAX, float(_delta) * _NARRATIVE_BIAS_SCALE))
                    _real_state[_dim] = min(1.0, max(-1.0, _real_state.get(_dim, 0.0) + _scaled))
                except (TypeError, ValueError): pass
        # 语义临时偏置（代词方向 + 回退到 _cx_parse_result）
        from ...language_system.pronoun_direction import match_state_reference
        _pr_result = match_state_reference(raw_input or "")
        _pr_pronoun = _pr_result.get("pronoun_weights", {})
        _pronoun_w = dict(_cx_parse_result.get("pronoun_weights", {}))
        for _dim, _pw_val in _pr_pronoun.items():
            _pronoun_w[_dim] = _pronoun_w.get(_dim, 0.0) * 0.5 + _pw_val * 0.5
        for _ref_dim, _ref_bias in _cx_parse_result.get("state_references", {}).items():
            try:
                _cur = float(_real_state[_ref_dim])
                _pw = float(_pronoun_w.get(_ref_dim, 0.40))
                _scale = _pw * max(0.15, _cur) + (1.0 - _pw) * 1.0
                _real_state[_ref_dim] = min(1.0, _cur + _ref_bias * _scale)
            except (KeyError, TypeError, ValueError): pass
        with observe_block("s06c:uncertainty_injection"):
            from ...language_system.output_state_bias import inject_thinking_focus
            inject_thinking_focus(entity, _real_state, _trace)
            from ...language_system.uncertainty_expression import (
                inject_proposition_uncertainty,
                inject_understanding_uncertainty,
            )
            inject_understanding_uncertainty(entity, _real_state, raw_input or "")
            inject_proposition_uncertainty(_real_state, _cx_parse_result.get("proposition_frame", {}))
        return locals().get("_concept_bias", {})
    # -------------------------------------------------------------------------

    _DRIVE_WRITE_WHITELIST = frozenset({
        "energy", "loneliness", "loneliness_core", "loneliness_surface",
        "unresolved", "boredom", "fatigue", "stress", "relief_debt", "pain",
        "info_gap", "external_change_rate",
        "somatic_tone", "danger_level", "approach_drive", "avoid_drive",
        "approach_social", "approach_explore", "approach_urgency",
        "joy", "anger", "fear", "sadness", "disgust", "anxiety", "surprise",
        "curiosity", "serenity", "excitement",
    })

    _real_state = dict(entity.to_state_snapshot())
    _enrich_state(_real_state)
    _result = match_anchor_expression(_real_state, entity, return_details=True)
    _anchor_text = _result.get("text", "") if isinstance(_result, dict) else _result
    _best_word = _result.get("best_word") if isinstance(_result, dict) else None
    _second_word = _result.get("second_word") if isinstance(_result, dict) else None
    _opening = _result.get("opening_particle", "") if isinstance(_result, dict) else ""
    _anchor_best_score_raw = _result.get("best_score", 0.0) if isinstance(_result, dict) else 0.0
    _anchor_cand_count = _result.get("cand_count", 0) if isinstance(_result, dict) else 0; logger.info(
        f"[AnchorMatch] t={entity.tick} text='{(_anchor_text or '')[:20]}' best_word={_best_word} score={_anchor_best_score_raw:.3f} cands={_anchor_cand_count} narrative={'Y' if _narrative_text else 'N'}"
    )

    # ① 合成始终运行
    _tmpl_idx = -1; _all_templates_snapshot = []  # 函数体层初始化：空锚词路径也已绑定，避免 record 处 NameError
    if _anchor_text:
        with observe_block("s06c:sentence_compose"):
            from ...language_system.sentence_composer import (
                compose_sentence, _COMPOSE_TEMP_BASE, _COMPOSE_TEMP_BOREDOM_GAIN
            )
            _te = {}
            _q_tmp = getattr(entity, "_quenching", None)
            if _q_tmp is not None:
                _te = _q_tmp.get_template_efficiency(seed_count=len(PATTERNS))
            _compose_temp_dm = _COMPOSE_TEMP_BASE + float(_real_state.get("boredom", 0.2)) * _COMPOSE_TEMP_BOREDOM_GAIN
            _extra = list(getattr(entity, "_runtime_templates", None) or [])
            with observe_block("s06c:cxg_candidates"):
                from ...language_system.uncertainty_expression import get_uncertainty_patterns
                _extra.extend(get_uncertainty_patterns())
                _cxg = getattr(entity, "_cxg_learner", None)
                if _cxg is not None:
                    _rcxg = getattr(entity, "_recursive_gen", None)
                    _recognized_words = [w for w, _ in _cx_parse_result.get("recognized_words", [])]
                    _sem_second = _second_word or next(iter(_recognized_words), None)
                    _anchor_list = list(getattr(entity, "_unlocked_vocabulary", []))[:20]
                    _anchor_list = _recognized_words + [w for w in _anchor_list if w not in _recognized_words]
                    _cxg_candidates = _cxg.generate_candidates(
                        _best_word or _anchor_text, _real_state,
                        second_anchor=_sem_second or "", recursive_generator=_rcxg,
                        anchor_words=_anchor_list,
                        action_context=getattr(entity, "_current_action", "") or "",
                    )
                    _extra.extend(_cxg_candidates)
            _sem_second = _second_word or next(iter([w for w, _ in _cx_parse_result.get("recognized_words", [])]), None)
            # 模板快照（record 用，必须与 compose_sentence 内部 all_templates 一致）
            _all_templates_snapshot = PATTERNS + _extra
            _composed, _tmpl_idx = compose_sentence(
                _best_word or _anchor_text, _real_state,
                connector=_opening,
                template_efficiency=_te,
                learned_weights=getattr(entity, "_template_learned_weights", None),
                extra_templates=_extra or None,
                second_anchor=_sem_second,
                temperature=_compose_temp_dm,
                anchor_score=_anchor_best_score_raw,
            )
            if _composed:
                _anchor_text = _composed
    entity._last_template_idx = _tmpl_idx

    # ② 显示决策（softmax 连续竞争）
    _narr_gate = min(1.0, len(_narrative_text or ""))
    _anchor_gate = min(1.0, len(_anchor_text or ""))
    _narr_disp = 0.80 * _narr_gate
    _anchor_disp = _anchor_best_score_raw * 0.85 * _anchor_gate
    if _is_wakeup_tick and _narrative_text:
        _narr_disp = 1.5
        logger.info(f"[Wakeup] Prioritising wakeup narrative over anchor: '{_narrative_text[:40]}'")
    _d_scores = [_narr_disp, _anchor_disp]
    _d_max = max(_d_scores)
    _d_w = [_d_math.exp((s - _d_max) / max(0.15, 0.01)) for s in _d_scores]
    _d_sum = sum(_d_w)
    _d_idx = _rnd.choices([0, 1], weights=[w / max(_d_sum, 1e-9) for w in _d_w], k=1)[0]
    _chosen_text = [_narrative_text or "", _anchor_text or ""][_d_idx]
    _chosen_mode = ["narrative", "anchor_auto"][_d_idx]
    _chosen_conf = _d_scores[_d_idx]
    _anchor_display_w = float(_d_idx)
    response = {"text": _chosen_text, "confidence": _chosen_conf, "anchor_weight": float(_d_idx), "generation_time_ms": 0}
    _trace("output", True, {"mode": _chosen_mode, "text": _chosen_text[:40], "wakeup": _is_wakeup_tick})
    logger.info({0: f"[Narrative] t={entity.tick} said: '{_chosen_text}'",
                 1: f"[AnchorAuto] t={entity.tick} said: '{_chosen_text}'"}[_d_idx]); entity._vr_prev = entity.to_state_snapshot()

    # 澄清记忆记录（clarification_memory v1 record-only）
    if _all_templates_snapshot:
        with observe_block("s06c:clarification_memory"):
            from ...language_system.clarification_memory import (
                maybe_record_displayed_clarification as _record_clar,
            )
            _record_clar(
                entity=entity,
                raw_input=raw_input or "",
                _cx_parse_result=_cx_parse_result,
                _chosen_text=_chosen_text,
                _chosen_mode=_chosen_mode,
                _tmpl_idx=_tmpl_idx,
                all_templates_snapshot=_all_templates_snapshot,
            )

    # 训练 episode 写入（anchor 显示时记录）
    for _ in range(int(round(_anchor_display_w))):
        with observe_block("s06c:episode_write"):
            from ...memory_hub.episodes_db import Episode, write_episode
            _ep = Episode(
                iteration_id=entity.tick,
                timestamp=datetime.now(timezone.utc).isoformat(),
                output_text=_anchor_text or "",
                state_snapshot=dict(_real_state),
                importance=min(1.0, _anchor_best_score_raw),
                tags=["autonomous", "anchor_expression", f"word:{_best_word or 'none'}"],
                summary=f"[anchor_auto] {_anchor_text}",
            )
            write_episode(_ep)

    # 内语回路（anchor 显示时生效）
    with observe_block("s06c:inner_speech"):
        from ...language_system.construction_parser import parse_self_speech
        _inner = parse_self_speech(_anchor_text or "", entity)
        _inner_delta = _inner.get("drive_delta", {})
        for _dim, _val in _inner_delta.items():
            if _dim not in _DRIVE_WRITE_WHITELIST: continue
            _old = getattr(entity, _dim, None)
            if _old is not None and isinstance(_old, (int, float)):
                setattr(entity, _dim, max(0.0, min(1.0, float(_old) + _val * _anchor_display_w)))
        _comprehension = _inner.get("comprehension", 0.0) * _anchor_display_w
        _trace("inner_speech", _comprehension > 0, {
            "text": (_anchor_text or "")[:30],
            "comprehension": _comprehension,
            "delta_dims": list(_inner_delta.keys()),
        })

    # ③ 学习始终运行
    entity._language_best_score = _anchor_best_score_raw
    entity._language_best_candidate = _best_word
    entity._language_best_expression = _anchor_text

    # 表达消力 + 消力记录（每 tick 运行）
    if _best_word:
        with observe_block("s06c:expression_quench"):
            from ...quenching_system import expression_quenching
            _ur_before = float(_real_state.get("unresolved", 0.0))
            expression_quenching(entity, _best_word)
            _ur_after = float(getattr(entity, "unresolved", 0.0))
            _q = getattr(entity, "_quenching", None)
            if _q is None:
                _qd = getattr(entity, "_quenching_data", None)
                _q = QuenchingTracker.from_dict(_qd) if (_qd and _qd.get("records")) else QuenchingTracker()
                entity._quenching = _q
            _q.record(
                drive_state=_real_state,
                expression=_best_word,
                delta_unresolved_before=_ur_before,
                delta_unresolved_after=_ur_after,
                tick=entity.tick,
                template_idx=getattr(entity, "_last_template_idx", -1),
            )
            entity._quenching_data = _q.to_dict()

            # 模板权重学习 + 进化
            with observe_block("s06c:template_learner"):
                from ...language_system import template_learner
                _eff = max(0.0, _ur_before - _ur_after) / max(_ur_before, 0.01)
                _lw = getattr(entity, "_template_learned_weights", {})
                template_learner.update_weights(getattr(entity, "_last_template_idx", -1), _real_state, _eff, _lw)
                entity._template_learned_weights = _lw
                _rt = getattr(entity, "_runtime_templates", [])
                _sc = getattr(entity, "_spawn_counter", 0)
                _stats = _q.get_template_stats(seed_count=len(PATTERNS))
                _new_tmpl, _sc = template_learner.try_spawn_template(_stats, PATTERNS, _rt, _sc)
                entity._spawn_counter = _sc
                if _new_tmpl is not None:
                    _new_tmpl["born_tick"] = entity.tick
                    _rt.append(_new_tmpl)
                    entity._runtime_templates = _rt
                    logger.info(f"[TemplateLearner] t={entity.tick} new template: {_new_tmpl['template']}")
                entity._template_learner_data = template_learner.to_dict(_lw, _rt, _sc)

            # 构式习得：记录实例 + 反馈
            with observe_block("s06c:cxg_learner"):
                _cxg = getattr(entity, "_cxg_learner", None)
                if _cxg is not None and _best_word:
                    _all_tmpls = PATTERNS + list(getattr(entity, "_runtime_templates", []))
                    _ti = getattr(entity, "_last_template_idx", -1)
                    _tmpl_str = ""
                    if 0 <= _ti < len(_all_tmpls):
                        _tmpl_str = _all_tmpls[_ti].get("template", "")
                    elif _ti < -1:
                        from ...language_system.sentence_composer import COMPOUND_PATTERNS
                        _ci = -1000 - _ti
                        if 0 <= _ci < len(COMPOUND_PATTERNS):
                            _tmpl_str = COMPOUND_PATTERNS[_ci].get("template", "")
                    if _tmpl_str:
                        _cxg.record_instance(
                            template_str=_tmpl_str, anchor=_best_word,
                            drive_state=_real_state, efficiency=_eff,
                            tick=entity.tick, second_anchor=_second_word or "",
                        )
                        if _ti >= len(PATTERNS) and _ti < len(_all_tmpls):
                            _sel_tmpl = _all_tmpls[_ti]
                            if _sel_tmpl.get("_from_cxg"):
                                _cxg.reinforce(
                                    _tmpl_str, _eff, entity.tick,
                                    action_context=getattr(entity, "_current_action", "") or "",
                                )
                    _cxg.decay_all(entity.tick)
                    entity._cxg_data = _cxg.to_dict()
                    _rcxg = getattr(entity, "_recursive_gen", None)
                    if _rcxg is not None:
                        _rcxg.decay_all()
                        entity._rcxg_data = _rcxg.to_dict()
    # 热身注入（daemon 自主积累）
    with observe_block("s06c:word_warmup"):
        from ...language_system.word_warmup import inject_warmup_candidates
        inject_warmup_candidates(entity, [], min_hits=3, min_best_efficiency=0.15)

    # 内源校准（每 30 tick 回溯验证一次）
    if entity.tick % 30 == 0:
        with observe_block("s06c:endogenous_calibration"):
            from ...endogenous_calibration import calibrate_from_episodes, apply_calibration
            _calib_report = calibrate_from_episodes(entity, _real_state, limit=5)
            apply_calibration(entity, _calib_report)
            if _calib_report.get("verified_count", 0) > 0:
                logger.info(
                    f"[Calibrate] tick={entity.tick} "
                    f"verified={_calib_report['verified_count']} "
                    f"rate={_calib_report.get('verification_rate', 0):.0%}"
                )

    return {
        "text": _anchor_text or "",
        "best_word": _best_word,
        "second_word": _second_word,
        "best_score": _anchor_best_score_raw,
        "anchor_display_w": _anchor_display_w,
    }
