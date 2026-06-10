"""Small output-state biases derived from cognitive state."""

import math

# Seed values from PLAN_thinking_to_language.md section 4/6.
THINK_TAU_QUESTION = 8.0
THINK_K_UNRESOLVED = 0.30
THINK_K_CURIOSITY = 0.10
THINK_BIAS_MAX = 0.40


def inject_thinking_focus(entity, state: dict, trace) -> None:
    """Project unanswered low-confidence questions into expression state."""
    pending_questions = getattr(entity, "_pending_questions", None) or []
    current_tick = float(getattr(entity, "tick", 0))
    tension = 0.0
    for question in pending_questions:
        age = max(0.0, current_tick - float(question.get("tick", current_tick)))
        recency = math.exp(-age / THINK_TAU_QUESTION)
        uncertainty = 1.0 - float(question.get("confidence_at_ask", 1.0))
        tension += float(question.get("priority", 0.0)) * uncertainty * recency
    unresolved_bias = min(THINK_BIAS_MAX, tension * THINK_K_UNRESOLVED)
    curiosity_bias = min(THINK_BIAS_MAX, tension * THINK_K_CURIOSITY)
    state["unresolved"] = min(1.0, float(state.get("unresolved", 0.0)) + unresolved_bias)
    state["curiosity"] = min(1.0, float(state.get("curiosity", 0.5)) + curiosity_bias)
    trace("think_bias", min(1.0, tension), {
        "tension": round(tension, 4),
        "ur_bias": round(unresolved_bias, 4),
        "cur_bias": round(curiosity_bias, 4),
        "pending_q": len(pending_questions),
    })
