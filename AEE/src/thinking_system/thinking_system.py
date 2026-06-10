"""
Thinking System Module (思考系统)

v5 统一流改造：问题和建议都从同一个焦点规则集合中涌现。

Submodule:
    thinking_system_helpers.py — core algorithms: dimensions, focal rules, questions, suggestions
"""

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .thinking_system_helpers import (
    _rules,
    _active_dimensions,
    _select_focal_rules,
    _build_suggestions,
)
from .thinking_system_questions import (
    _build_question,
    _build_tool_capability_question,
)


@dataclass
class ThoughtPacket:
    suggestions: List[Dict[str, Any]] = field(default_factory=list)
    questions: List[Dict[str, Any]] = field(default_factory=list)
    branch_memories: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "suggestions": self.suggestions,
            "questions": self.questions,
            "branch_memories": self.branch_memories,
        }


THOUGHT_PACKET_EMPTY = ThoughtPacket()

DEFAULT_PARAMS = {
    "thinking_activation_threshold": 0.5,
    "max_thinking_steps": 3,
    "thinking_time_budget_ms": 500.0,
    "max_suggestions": 2,
}


def think(
    wm_context: Optional[dict],
    drive_vector: Optional[dict],
    state_snapshot: Optional[dict] = None,
    params: Optional[dict] = None,
    somatic_signals: Optional[dict] = None,
    entity_state: Optional[Any] = None,
    concept_tags: Optional[List[Any]] = None,
    attention_weights: Optional[Dict[str, float]] = None,
    input_context: Optional[Dict[str, Any]] = None,
) -> dict:
    """
    v5 统一流思考主入口。

    流程：
        1. 驱动力场 → 当前活跃维度集合
        2. 活跃维度 → 焦点规则（按重叠度）
        3. 焦点规则 → 同时生成问题和建议（统一流）
        4. 感质调制 + 注意力调制
        5. 工具能力缺口自省问题（v11.6）
        6. 枝干联想检索
    """
    try:
        params = {**DEFAULT_PARAMS, **(params or {})}

        dv = {}
        for k in ("curiosity", "info_hunger", "obsolescence_anxiety",
                  "loneliness_drive", "fatigue_avoid"):
            dv[k] = float((drive_vector or {}).get(k, 0.0))

        rules = _rules(wm_context)
        if not rules:
            return THOUGHT_PACKET_EMPTY.to_dict()
        if not any(v >= params["thinking_activation_threshold"] for v in dv.values()):
            return THOUGHT_PACKET_EMPTY.to_dict()

        # Step 1: 活跃维度
        active_dims = _active_dimensions(dv, state_snapshot)

        # Step 2: 焦点规则
        start = time.time()
        focal_rules = _select_focal_rules(rules, active_dims, params, input_context)

        # Step 3: 问题（仅针对活规则，排除 decayed）
        _living_rules = [r for r in rules if r.get("status", "active") != "decayed"]
        question_rules = _select_focal_rules(_living_rules, active_dims, params, input_context)
        questions = []
        for rule in question_rules:
            if (time.time() - start) * 1000 >= params["thinking_time_budget_ms"]:
                break
            questions.append(_build_question(rule, question_rules))

        # Step 4: 建议
        suggestions = _build_suggestions(
            focal_rules, dv, state_snapshot, params, somatic_signals, attention_weights,
        )

        # Step 4.5: 心智模拟验证
        if suggestions and state_snapshot and entity_state is not None:
            try:
                from .mental_simulation import simulate_suggestions
                wm_rules = getattr(entity_state, "wm_rules", [])
                if wm_rules:
                    suggestions = simulate_suggestions(
                        suggestions, state_snapshot, wm_rules, entity=entity_state,
                    )
            except Exception:
                pass

        # Step 5: 工具能力缺口自省问题（v11.6）
        tool_capability_questions = []
        if entity_state is not None:
            try:
                pending_gaps = getattr(entity_state, "_pending_tool_gaps", [])
                if pending_gaps:
                    for gap in pending_gaps:
                        q = _build_tool_capability_question(gap)
                        if q is not None:
                            tool_capability_questions.append(q)
                    if hasattr(entity_state, "_pending_tool_gaps"):
                        entity_state._pending_tool_gaps = []
            except Exception:
                tool_capability_questions = []

        # Step 6: 枝干联想检索
        branch_memories = []
        if entity_state is not None and concept_tags is not None:
            try:
                from ..memory_retrieval.branch import branch_retrieval
                tag_strings = [
                    t.get("tag") if isinstance(t, dict) else str(t)
                    for t in (concept_tags or [])
                ]
                branch_memories = branch_retrieval(entity_state, tag_strings)
            except Exception:
                branch_memories = []

        # 合并 + 排序
        all_questions = questions + tool_capability_questions
        all_questions.sort(key=lambda x: x.get("priority", 0.0), reverse=True)
        all_questions = all_questions[:5]

        return ThoughtPacket(
            suggestions=suggestions,
            questions=all_questions,
            branch_memories=branch_memories,
        ).to_dict()

    except Exception:
        return THOUGHT_PACKET_EMPTY.to_dict()
