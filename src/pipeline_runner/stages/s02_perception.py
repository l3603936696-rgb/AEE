"""Stage 02 — 感性认识 + 驱动力计算 + 感质初始化。

职责：语义分析、构式解析、词汇习得、记忆偏置、概念标签、注意场、世界模型查询、
      驱动力计算、Insula 感质调味（第一次）。
输入：ctx.snapshot, ctx._snapshot_dict, ctx.state_snapshot, ctx._five_rights,
      ctx._semantic_analyzer, ctx._candidate_gen, ctx._quenching
输出：ctx.semantic_packet, ctx.semantic_packet_biased, ctx._cx_parse_result,
      ctx.user_intent_from_input, ctx._defy_result,
      ctx.concept_tags, ctx._recalled_insights, ctx.tag_strings,
      ctx.wm_context, ctx.wm_snapshot,
      ctx.drive_vector, ctx.drive_params, ctx.curiosity_baseline, ctx.info_hunger_baseline,
      ctx.somatic_signals, ctx._attention_field
"""

import copy
import logging
from typing import Any, Dict, List

from ...semantic.semantic_understanding import analyze_semantic
from ...memory_bias.memory_bias import apply_memory_bias
from ...concept_tags.concept_tags import generate_concept_tags
from ...world_model_reader.world_model_reader import query_world_model
from ...drive_system.drive_system import compute_drive_vector
from ...memory_hub.insula_hub import compute_somatic_signals as _compute_somatic_signals
from ...parameter_system.access import get_param
from ..utils import get_default_drive_params

_DRIVE_WRITE_WHITELIST = frozenset({
    "energy", "loneliness", "loneliness_core", "loneliness_surface",
    "unresolved", "boredom", "fatigue", "stress", "relief_debt", "pain",
    "info_gap", "external_change_rate",
    "somatic_tone", "danger_level", "approach_drive", "avoid_drive",
    "approach_social", "approach_explore", "approach_urgency",
    "joy", "anger", "fear", "sadness", "disgust", "anxiety", "surprise",
    "curiosity", "serenity", "excitement",
})

logger = logging.getLogger(__name__)


def run_stage(ctx, entity) -> None:
    _trace = ctx._trace
    raw_input = ctx.raw_input
    snapshot = ctx.snapshot
    _snapshot_dict = ctx._snapshot_dict
    state_snapshot = ctx.state_snapshot
    _five_rights = ctx._five_rights
    _semantic_analyzer = ctx._semantic_analyzer
    _candidate_gen = ctx._candidate_gen
    _quenching = ctx._quenching

    # ---- Step 1.5: 刻板印象树剪枝（说话者上下文约束）----
    _stereotype_context = None
    if raw_input and str(raw_input).strip():
        try:
            from ...language_system.stereotype_tree import get_speaker_context, ensure_tree
            from ...language_system.stereotype_learner import FeatureExtractor
            # 获取说话者 ID（来自 ctx._input_source 或默认为 "external"）
            source_id = getattr(ctx, "_input_source", "external")
            # 快速提取输入特征
            extractor = FeatureExtractor(window_size=1)
            _input_features = extractor.extract_from_single_message(
                str(raw_input),
                float(semantic_packet.get("emotion", 0.0)) if semantic_packet else 0.0,
            ) if semantic_packet else None
            # 获取说话者上下文
            tree = ensure_tree(entity)
            _stereotype_context = tree.match(source_id, _input_features)
            if _stereotype_context:
                _trace("stereotype_match", True, {
                    "speaker_id": source_id,
                    "depth": _stereotype_context.depth,
                    "confidence": _stereotype_context.confidence,
                    "active_tags": _stereotype_context.active_tags[:5],
                })
        except Exception as e:
            _trace("stereotype_match", False, {}, str(e))

    # ---- Step 2: 感性认识 ----
    try:
        semantic_raw = analyze_semantic(raw_input) if raw_input else {
            "emotion": 0.0, "intent": "闲聊", "intensity": 0.3, "anchors": []
        }
        if "intent_confidence" not in semantic_raw:
            semantic_raw["intent_confidence"] = 0.8
        # ---- 刻板印象偏置：说话者上下文约束语义分析 ----
        if _stereotype_context:
            try:
                from ...language_system.stereotype_tree import apply_stereotype_bias
                semantic_raw = apply_stereotype_bias(semantic_raw, _stereotype_context)
                _trace("stereotype_bias", True, {
                    "confidence": _stereotype_context.confidence,
                    "emotion_adjusted": semantic_raw.get("emotion"),
                })
            except Exception as e:
                _trace("stereotype_bias", False, {}, str(e))
        semantic_packet = semantic_raw
        _trace("semantic", True, semantic_packet)
    except Exception as e:
        semantic_raw = {"emotion": 0.0, "intent": "闲聊", "intensity": 0.3, "anchors": [], "intent_confidence": 0.8}
        semantic_packet = semantic_raw
        _trace("semantic", False, semantic_packet, str(e))

    # ---- Step 2a: 构式解析（她自己的"耳朵"）----
    _cx_parse_result: Dict[str, Any] = {}
    if raw_input and str(raw_input).strip():
        try:
            from ...language_system.construction_parser import parse_input as _cx_parse
            _cx_parse_result = _cx_parse(str(raw_input), entity)
            semantic_packet["cx_comprehension"] = _cx_parse_result.get("comprehension", 0.0)
            semantic_packet["cx_social_intent"] = _cx_parse_result.get("social_intent", "unknown")
            semantic_packet["cx_construction_match"] = _cx_parse_result.get("construction_match", "")
            _cx_delta = _cx_parse_result.get("drive_delta", {})
            for _dim, _val in _cx_delta.items():
                if _dim not in _DRIVE_WRITE_WHITELIST:
                    continue
                _old = getattr(entity, _dim, None)
                if _old is not None and isinstance(_old, (int, float)):
                    setattr(entity, _dim, max(0.0, min(1.0, float(_old) + _val)))
            _trace("cx_parse", True, {
                "comprehension": _cx_parse_result.get("comprehension", 0.0),
                "social_intent": _cx_parse_result.get("social_intent", "unknown"),
                "drive_delta_dims": list(_cx_delta.keys()),
            })
        except Exception as e:
            _trace("cx_parse", False, {}, str(e))

    # ---- Step 2b: 词汇习得（v1.0）----
    if raw_input and str(raw_input).strip() and _cx_parse_result:
        try:
            from ...language_system.vocabulary_acquisition import (
                try_acquire_words_sync, decay_exposure,
            )
            _acq_comp = _cx_parse_result.get("comprehension", 0.0)
            _acquired = try_acquire_words_sync(
                str(raw_input), entity, _acq_comp, ctx.llm_callable,
            )
            if _acquired:
                _trace("vocab_acquire", True, {"acquired": _acquired})
            decay_exposure(entity)
        except Exception as e:
            _trace("vocab_acquire", False, {}, str(e))

    # ---- Step 2c: 从输入中学习构式（v1.0）----
    if raw_input and str(raw_input).strip() and _cx_parse_result:
        try:
            from ...language_system.construction_parser import learn_constructions_from_input
            learn_constructions_from_input(str(raw_input), entity, _cx_parse_result)
        except Exception:
            pass

    # ---- 顶撞权检查 ----
    user_intent_from_input: Dict[str, Any] = {}
    if raw_input and str(raw_input).strip():
        user_intent_from_input = {
            "content": str(raw_input),
            "intent": semantic_packet.get("intent", "") if semantic_packet else "",
            "emotion": float(semantic_packet.get("emotion", 0.0)) if semantic_packet else 0.0,
            "pressure": abs(float(semantic_packet.get("emotion", 0.0))) if semantic_packet else 0.0,
        }
    _defy_result: Dict[str, Any] = {"defy": False, "reason": "", "efficiency_boost": 1.0}
    if user_intent_from_input:
        _defy_result = _five_rights.check_defy(user_intent_from_input, state_snapshot, snapshot)
        _trace("language_defy", True, _defy_result)

    # ---- Step 3: 记忆偏置 ----
    try:
        semantic_packet_biased = apply_memory_bias(semantic_packet, entity.memory_context)
        semantic_packet_biased["raw_input"] = raw_input
        _trace("memory_bias", True, {"emotion": semantic_packet_biased.get("emotion")})
    except Exception as e:
        semantic_packet_biased = dict(semantic_packet)
        semantic_packet_biased["raw_input"] = raw_input
        _trace("memory_bias", False, semantic_packet_biased, str(e))

    # ---- Step 4: 概念标签映射 ----
    try:
        concept_tags = generate_concept_tags(semantic_packet_biased)
        _trace("concept_tags", True, {"count": len(concept_tags), "tags": [t.get("tag") for t in concept_tags]})
    except Exception as e:
        concept_tags = []
        _trace("concept_tags", False, {"count": 0}, str(e))

    # ---- Step 4a: 注意场调制（v11.5）----
    try:
        from ...emotion_system.attention_field import (
            compute_attention_field_from_entity,
            ALL_CATEGORIES,
        )
        _attention_field = compute_attention_field_from_entity(entity)
        entity._attention_field = _attention_field
        _af_tags = []
        for _cat in ALL_CATEGORIES:
            _gain = _attention_field.get(_cat, 1.0)
            if abs(_gain - 1.0) > 0.15:
                _af_tags.append({
                    "tag": f"focus:{_cat}",
                    "category": "attention_focus",
                    "confidence": min(1.0, abs(_gain - 1.0) * 2.0),
                    "gain": round(_gain, 2),
                })
        _af_tags.sort(key=lambda t: abs(t["gain"] - 1.0), reverse=True)
        concept_tags.extend(_af_tags[:5])
        _trace("attention_field", True, {"top_gains": {t["tag"]: t["gain"] for t in _af_tags[:3]}})
        if _af_tags and entity.tick % 5 == 0:
            _top = ", ".join(f"{t['tag']}={t['gain']:.2f}" for t in _af_tags[:4])
            logger.info(f"[AttnField] t={entity.tick} top_focus: {_top}")
    except Exception as e:
        _attention_field = None
        _trace("attention_field", False, {}, str(e))

    # ---- Step 4.5: Insights 召回 ----
    tag_strings = [t.get("tag", "") for t in concept_tags if isinstance(t, dict)]
    _recalled_insights: List[Any] = []
    try:
        from ...memory_hub.insights import recall_insights as _recall_insights
        _recalled_insights = _recall_insights(tag_strings)
        _trace("insights_recall", True, {"query_tags": tag_strings, "hit_count": len(_recalled_insights)})
    except Exception as e:
        _recalled_insights = []
        _trace("insights_recall", False, {}, str(e))

    # ---- Step 5: 世界模型查询（只读）----
    wm_snapshot = {"rules": entity.wm_rules}
    try:
        tag_strings = [t.get("tag", "") for t in concept_tags if isinstance(t, dict)]
        wm_context = query_world_model(tag_strings, copy.deepcopy(wm_snapshot))
        _trace("world_model_read", True, {
            "hit_rate": wm_context.get("coverage", {}).get("hit_rate", 0.0),
            "matched_count": len(wm_context.get("matched_rules", [])),
        })
    except Exception as e:
        wm_context = {"matched_rules": [], "key_signals": {}, "coverage": {"hit_rate": 0.0, "queried_tags": [], "missed_tags": []}}
        _trace("world_model_read", False, {}, str(e))

    # ---- Step 6: 驱动力计算 ----
    try:
        curiosity_baseline = get_param(snapshot, "drives.curiosity_baseline", 0.2)
        info_hunger_baseline = get_param(snapshot, "drives.info_hunger_baseline", 0.24)
        drive_params = {
            "curiosity_baseline": curiosity_baseline,
            "info_hunger_baseline": info_hunger_baseline,
            "curiosity_param": get_param(snapshot, "drives.curiosity_param", 1.0),
            "max_info_gap_hours": get_param(snapshot, "drives.max_info_gap_hours", 24.0),
            "max_social_gap_hours": get_param(snapshot, "drives.max_social_gap_hours", 24.0),
            **get_default_drive_params(),
        }
        drive_state = dict(state_snapshot)
        drive_state["info_gap"] = min(1.0, state_snapshot.get("info_gap", 0.0) + curiosity_baseline * 0.5)
        drive_vector = compute_drive_vector(drive_state, drive_params)
        drive_vector["curiosity"] = min(1.0, drive_vector.get("curiosity", 0.0) + curiosity_baseline)
        drive_vector["info_hunger"] = min(1.0, drive_vector.get("info_hunger", 0.0) + info_hunger_baseline)
        _trace("drive", True, drive_vector)
    except Exception as e:
        curiosity_baseline = 0.2
        info_hunger_baseline = 0.24
        drive_params = {}
        drive_vector = {"curiosity": 0.2, "info_hunger": 0.24, "obsolescence_anxiety": 0.0, "loneliness_drive": 0.0, "fatigue_avoid": 0.0}
        _trace("drive", False, drive_vector, str(e))

    # ---- Step 6.1: 注意场调制 drive_vector ----
    try:
        _af = getattr(entity, "_attention_field", None)
        if _af:
            from ...emotion_system.attention_field import apply_attention_to_drive_vector
            drive_vector = apply_attention_to_drive_vector(drive_vector, _af)
            _trace("drive_attention_mod", True, {k: round(v, 3) for k, v in drive_vector.items()})
    except Exception as e:
        _trace("drive_attention_mod", False, {}, str(e))

    # ---- Step 6.5: 感质调味（v3）----
    try:
        somatic_signals = _compute_somatic_signals(
            drive_vector=drive_vector,
            wm_context=wm_context,
            entity_core_state=state_snapshot,
            param_snapshot=_snapshot_dict,
        )
        entity.somatic_tone = max(-1.0, min(1.0, somatic_signals.get("tone", 0.0)))
        _trace("insula_hub", True, {
            "tone": somatic_signals.get("tone"),
            "dominant_feeling": somatic_signals.get("dominant_feeling"),
            "channel_weights": somatic_signals.get("channel_weights"),
        })
    except Exception as e:
        somatic_signals = {"tone": 0.0, "intensity": 0.0, "dominant_feeling": "", "channel_weights": {}, "dos_suppressed": []}
        _trace("insula_hub", False, {}, str(e))

    # 更新 state_snapshot 供后续步骤使用
    state_snapshot["somatic_tone"] = entity.somatic_tone

    # --- Outputs ---
    ctx.semantic_packet = semantic_packet
    ctx.semantic_packet_biased = semantic_packet_biased
    ctx._cx_parse_result = _cx_parse_result
    ctx.user_intent_from_input = user_intent_from_input
    ctx._defy_result = _defy_result
    ctx.concept_tags = concept_tags
    ctx._recalled_insights = _recalled_insights
    ctx.tag_strings = tag_strings
    ctx.wm_context = wm_context
    ctx.wm_snapshot = wm_snapshot
    ctx.drive_vector = drive_vector
    ctx.drive_params = drive_params
    ctx.curiosity_baseline = curiosity_baseline
    ctx.info_hunger_baseline = info_hunger_baseline
    ctx.somatic_signals = somatic_signals
    ctx._attention_field = _attention_field
    ctx._stereotype_context = _stereotype_context
    ctx.state_snapshot = state_snapshot  # somatic_tone 已注入
