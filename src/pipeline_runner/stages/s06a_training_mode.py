"""
Stage 06a Training Mode — 训练模式体感帮助模块。

提取自 s06a_candidates.py（训练模式块，lines 309-366）。
包含：训练模式判定 + somatic help + nudge + meta_cognitive。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def run_training_mode(
    entity,
    best_candidate: Optional[str],
    best_score: float,
    _training_threshold: float,
    daemon_mode: bool,
    state_snapshot: Dict,
    _quenching: Any,
    _training_components: List,
    trace_fn,
) -> tuple[bool, Optional[str], List]:
    """
    运行训练模式体感帮助逻辑。

    返回：(training_mode, display_word, training_components)
    """
    _training_mode = (
        best_candidate is not None
        and best_score > _training_threshold
        and len(best_candidate) <= 8
        and not daemon_mode
    )
    _display_word = best_candidate
    if _training_mode:
        try:
            import random as _rnd
            from AEE.src.language_system.somatic_dictionary import SOMATIC_DICTIONARY
            _func_cats = ["actions", "degree", "time", "question", "logic"]
            _cat = _rnd.choice(_func_cats)
            _func_words = list(SOMATIC_DICTIONARY.get(_cat, {}).keys())
            if _func_words:
                _fw = _rnd.choice(_func_words)
                if _rnd.random() < 0.5:
                    _display_word = f"{_fw}{best_candidate}"
                else:
                    _display_word = f"{best_candidate}{_fw}"
        except Exception:
            _display_word = best_candidate

        entity._training_override = _display_word
        entity._training_components = _training_components
        try:
            from AEE.src.language_system.somatic_concept_map import apply_help_delta, training_exploration_nudge
            from AEE.src.language_system.meta_cognitive import apply_meta_cognitive
            help_result = apply_help_delta(
                best_candidate, entity, state_snapshot,
                min_match=0.30,
                help_scaling=0.40,
            )
            nudge_result = training_exploration_nudge(
                entity, state_snapshot,
                stuck_threshold=0.35,
                nudge_strength=0.03,
            )
            meta_result = apply_meta_cognitive(
                entity,
                snapshots=entity.snapshots[-30:],
                quenching_records=[
                    {"expression": r.expression, "quenching_efficiency": r.quenching_efficiency}
                    for r in (_quenching._history if _quenching else [])
                ],
                lookback=15,
                scaling=0.8,
            )
            trace_fn("somatic_help", True, help_result)
            if help_result.get("match", 0) > 0.3:
                _relief = help_result.get("match", 0) * 0.25
                entity.adjust("relief_debt", -_relief)
                trace_fn("relief_release", True, {
                    "match": round(help_result["match"], 3),
                    "relief_released": round(_relief, 4),
                    "relief_debt": round(entity.relief_debt, 4),
                })
            if nudge_result:
                trace_fn("somatic_nudge", True, {"nudged": list(nudge_result.keys())})
            if meta_result:
                trace_fn("meta_cognitive", True, {"applied": list(meta_result.keys())})
        except Exception as e:
            trace_fn("somatic_help", False, {}, str(e))
    elif best_candidate and best_score > _training_threshold:
        entity._language_best_long = best_candidate
    return _training_mode, _display_word, _training_components
