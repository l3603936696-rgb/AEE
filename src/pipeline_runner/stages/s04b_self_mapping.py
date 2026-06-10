"""
Stage 04b Self-Mapping — 元认知感知模块。

提取自 s04b_emerge.py（Step 8.2 self_mapping 块）。
包含：SelfBodyMap 感知 + narrative 生成 + 自验证。
"""

from __future__ import annotations

from typing import Any, Dict, Optional


def run_self_mapping(
    entity,
    state_snapshot: Dict,
    wm_rules: list,
    trace_fn,
) -> tuple[Optional[Dict], float]:
    """
    元认知感知：SelfBodyMap + NarrativeGenerator + 自验证。

    返回：(narrative_record, coherence_meta)
    """
    try:
        from AEE.src.self_mapping import SelfBodyMap, NarrativeGenerator

        state_for_mapping = entity.to_state_snapshot()
        _self_body_map = SelfBodyMap(tick=entity.tick)
        _self_body_map.update(state_snapshot, state_for_mapping)
        _self_body_map.sync_relations(wm_rules)
        _narrative_record = _self_body_map.generate_narrative()
        trace_fn("self_mapping_sense", True, {
            "changes": _self_body_map._changes,
            "relation_count": len(_self_body_map.relations),
            "narrative": _narrative_record["prediction"] if _narrative_record else None,
        })
        _prev_narrative_tick = getattr(entity, "_prev_self_narrative", None)
        _verification_result = None
        if _prev_narrative_tick is not None:
            _prev_narr = _prev_narrative_tick.get("record")
            _prev_rel_id = _prev_narrative_tick.get("relation_id")
            if _prev_narr and _prev_rel_id:
                _target_rel = next(
                    (r for r in _self_body_map.relations
                     if r.cause == _prev_narr.get("cause") and r.effect == _prev_narr.get("effect")),
                    None,
                )
                if _target_rel:
                    _ng = NarrativeGenerator()
                    _verification_result = _ng.verify(_prev_narr, _self_body_map.parts, _target_rel)
        if _narrative_record:
            entity._prev_self_narrative = _narrative_record
        else:
            entity._prev_self_narrative = None
        coherence_meta = _self_body_map.get_coherence_meta()
        entity._coherence_meta = coherence_meta
        trace_fn("self_mapping_verify", True, {
            "verification": _verification_result,
            "coherence_meta": coherence_meta,
        })
        return _narrative_record, coherence_meta
    except Exception as e:
        trace_fn("self_mapping_sense", False, {}, str(e))
        entity._prev_self_narrative = None
        entity._coherence_meta = 0.5
        return None, 0.5
