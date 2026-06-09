"""
Stage 05 Pattern Feedback — 行为模式反馈闭环模块。

提取自 s05_behavior.py（Step 8.5 BP feedback 块）。
包含：结果 satisfaction 计算、BP compute_drive_match/world_model_predict/
apply_result/update_long_term_bias、pattern prune。
"""

from __future__ import annotations

from typing import Any, Dict, Optional, List


def run_bp_feedback(
    selected_candidate,
    all_action_results: List[str],
    emergent_action: str,
    decision: Dict,
    raw_input: Any,
    pre_bp_state: Dict,
    entity,
    trace_fn,
) -> tuple[Optional[Dict], Optional[Dict]]:
    """
    运行 BP 反馈闭环。

    返回：(bias_info, score_breakdown)
    bias_info 或 score_breakdown 可能为 None（失败时）。
    """
    success = any(r.startswith("[OK]") or "[search]" in r for r in all_action_results)
    failure = any("失败" in r or "Error" in r or "error" in r for r in all_action_results)
    _fail_signal = float(failure)
    _success_signal = float(success) * (1.0 - _fail_signal)
    short_reward = _success_signal * 1.5 - 0.5
    result_count = len(all_action_results)
    satisfaction = (
        0.5
        + min(result_count / 5.0, 0.3)
        - _fail_signal * 0.3
    )
    satisfaction = max(0.0, min(1.0, satisfaction))
    result_for_feedback = {
        "success": _success_signal > 0.5,
        "detail": " | ".join(all_action_results[:3]),
        "prediction_error": 0.2 + _fail_signal * 0.3,
        "error_type": {True: "execution", False: "none"}[failure],
        "short_term_reward": short_reward,
        "satisfaction": satisfaction,
        "content": " | ".join(all_action_results[:3]),
        "reason": f"{emergent_action} action",
        "count": result_count,
    }
    entity._bp_identity = 0.5
    entity._bp_unresolved_src = "external"
    state_for_bp = entity.to_state_snapshot()
    try:
        from src.core import behavior_patterns as bp

        candidate_name = (
            selected_candidate.actions
            if hasattr(selected_candidate, "actions")
            else str(selected_candidate)
        )
        base_score = bp.compute_drive_match(selected_candidate, state_for_bp)
        wm_pred = bp.world_model_predict(selected_candidate, state_for_bp)
        bias_bonus = 0.0
        drive = "?"
        intent = "unknown"
        if hasattr(selected_candidate, "intent_tag"):
            intent = selected_candidate.intent_tag
            drive = bp.INTENT_TO_DRIVE.get(intent, "explore")
            bias_bonus = 0.15 * entity.long_term_bias.get(drive, 0.0)
        score_breakdown = {
            "candidate": candidate_name, "intent": intent, "drive": drive,
            "base": round(base_score, 3),
            "wm_reward": round(wm_pred["reward"], 3),
            "wm_uncertainty": round(wm_pred["uncertainty"], 3),
            "bias_bonus": round(bias_bonus, 4),
            "bias": dict(entity.long_term_bias),
        }
        entity._bp_identity = entity.update_behavior_signature(
            decision.get("action_type", "") or emergent_action
        )
        raw_input_str = str(raw_input or "").strip()
        entity._bp_unresolved_src = "external" if raw_input_str else "self_generated"
        enriched_result = dict(result_for_feedback)
        enriched_result["identity_signal"] = entity._bp_identity
        enriched_result["unresolved_source"] = entity._bp_unresolved_src
        bp.apply_result(selected_candidate, enriched_result, state_for_bp)
        bias_info = bp.update_long_term_bias(
            entity_state=entity,
            pattern_or_intent=selected_candidate,
            pre_state=pre_bp_state,
            post_state=state_for_bp,
            action_result=enriched_result,
        )
        if entity.tick % 20 == 0:
            removed = bp.get_pool().prune()
            if removed:
                trace_fn("pattern_prune", True, {"removed": removed})
        trace_fn("pattern_feedback", True, {
            "candidate": candidate_name, "intent": intent,
            "success": success, "satisfaction": satisfaction,
            "short_reward": short_reward,
            "score_breakdown": score_breakdown,
            "bias_update": bias_info,
        })
        return bias_info, score_breakdown
    except Exception as e:
        trace_fn("pattern_feedback", False, {}, str(e))
        return None, None
