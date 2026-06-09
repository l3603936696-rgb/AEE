"""
State-to-Context Helpers — functions extracted from state_to_context.py.

generate_context_description, build_system_prompt, derive_rendering_params,
and _inject_rendering_instructions.
"""

from typing import Any, Dict, List, Optional, Tuple

from .state_to_context_data import (
    SYSTEM_PROMPT_FIXED, SYSTEM_PROMPT_CONSTRAINTS,
    _interpolate_bands, _check_conflict, _dominant_drive_label,
    _DIM_VALUE_KEYS, _DIM_BANDS, _DIM_CATEGORY, _get_category_score,
    _build_temporal_descriptions, _check_comfort_zone,
    _TONE_INSTRUCTIONS, _LENGTH_INSTRUCTIONS,
    _table_lookup, _apply_action_consistency,
)


def generate_context_description(
    entity_core_state: Dict[str, float],
    previous_state: Optional[Dict[str, float]] = None,
    drive_vector: Optional[Dict[str, float]] = None,
) -> tuple[List[str], List[str]]:
    """Generate situation descriptions (v4). Returns (main_descs, temporal_descs)."""
    conflict_desc = _check_conflict(entity_core_state)

    candidates: List[tuple[float, str, str]] = []
    for dim_name, value_key in _DIM_VALUE_KEYS.items():
        value = entity_core_state.get(value_key, 0.0)
        bands = _DIM_BANDS.get(dim_name, [])
        desc = _interpolate_bands(value, bands)
        if desc is None:
            continue
        score = _get_category_score(dim_name, value)
        candidates.append((score, desc, dim_name))

    chosen: List[tuple[float, str, str]] = []
    seen_cats: set = set()
    candidates.sort(key=lambda x: x[0], reverse=True)
    for score, desc, dim_name in candidates:
        cat = _DIM_CATEGORY.get(dim_name, "emotion")
        if cat not in seen_cats:
            seen_cats.add(cat)
            chosen.append((score, desc, dim_name))

    pain = max(
        entity_core_state.get("loneliness", 0.0),
        entity_core_state.get("stress", 0.0),
        entity_core_state.get("danger_level", 0.0),
    )
    chosen_damped = []
    for score, desc, dim_name in chosen:
        if dim_name == "somatic_tone":
            score = score * (1.0 - pain * 0.8)
        chosen_damped.append((score, desc, dim_name))
    chosen_damped.sort(key=lambda x: x[0], reverse=True)
    chosen = chosen_damped[:3]

    main_descs: List[str] = []
    if conflict_desc:
        main_descs.append(conflict_desc)
    main_descs += [desc for _, desc, _ in chosen]

    if drive_vector:
        drive_desc = _dominant_drive_label(drive_vector)
        if drive_desc:
            lonely_desc = entity_core_state.get("loneliness", 0.0) > 0.4
            if not (drive_desc.startswith("想找人说话") and lonely_desc):
                main_descs.append(drive_desc)

    main_descs = main_descs[:4]

    comfort_zone_desc = _check_comfort_zone(entity_core_state, drive_vector or {})
    if comfort_zone_desc and not main_descs:
        main_descs.append(comfort_zone_desc)

    temporal = _build_temporal_descriptions(entity_core_state, previous_state)
    return main_descs, temporal


def _inject_rendering_instructions(parts: list[str], rp: Dict[str, Any]) -> None:
    pace = rp.get("pace", "正常")
    length = rp.get("length", "正常")
    tone_stab = rp.get("tone_stability", "稳定")
    initiative = rp.get("initiative", "中等")

    pace_map = {
        "快": "节奏可以稍快一点。", "正常": "节奏自然就好。",
        "慢": "节奏可以放慢一点。", "很慢": "节奏慢一些，不用着急。",
    }
    if pace in pace_map:
        parts.append(pace_map[pace])

    if length in ("话多", "偏长", "很长"):
        if initiative == "主动":
            combined = "话可以多一些，想说什么就说。"
        elif initiative == "中等":
            combined = "话可以多一些，但不必刻意延伸。"
        else:
            combined = "话可以多一些，说到哪算哪。"
    elif length in ("话少", "很短", "偏短"):
        if initiative == "被动":
            combined = "话少一点，简洁回应就好。"
        else:
            combined = "话少一点，说重点。"
    elif initiative == "主动":
        combined = "稍微主动一些也可以延伸话题。"
    elif initiative == "被动":
        combined = "不用强求延伸话题，回应即可。"
    else:
        combined = None
    if combined:
        parts.append(combined)

    stab_map = {"稳定": "语气平稳流畅。", "波动": "可以有些自我修正和犹豫。"}
    if tone_stab in stab_map:
        parts.append(stab_map[tone_stab])


def build_system_prompt(
    entity_core_state: Dict[str, float],
    emergent_behavior: Optional[Dict[str, Any]] = None,
    somatic_signals: Optional[Dict[str, Any]] = None,
    tone_constraint: Optional[str] = None,
    length_constraint: Optional[str] = None,
    previous_state: Optional[Dict[str, float]] = None,
    drive_vector: Optional[Dict[str, float]] = None,
    rendering_params: Optional[Dict[str, Any]] = None,
) -> str:
    """Assemble complete LLM system_prompt (v4)."""
    main_descs, temporal = generate_context_description(
        entity_core_state, previous_state, drive_vector
    )

    parts: list[str] = []
    parts.append(SYSTEM_PROMPT_FIXED)

    if main_descs:
        parts.append("。".join(main_descs) + "。")
    else:
        parts.append("感觉还行，没什么特别的事。")

    if temporal:
        parts.append("。".join(temporal) + "。")

    if rendering_params and isinstance(rendering_params, dict):
        _inject_rendering_instructions(parts, rendering_params)

    if emergent_behavior and isinstance(emergent_behavior, dict):
        action = emergent_behavior.get("action_type", "")
        tension = emergent_behavior.get("tension_level", 0.0)
        dominant = emergent_behavior.get("dominant_state", "")
        if action == "rest":
            parts.append("很想休息，但还在撑着。")
        elif action == "seek" and dominant == "loneliness":
            parts.append("很想找人说话。")
        elif action == "explore" and dominant == "unresolved":
            parts.append("有个问题一直挂在心上，想搞清楚。")
        elif action == "avoid":
            parts.append("有点想回避什么。")
        elif tension >= 0.6:
            parts.append("有点纠结，说不太清楚。")

    if emergent_behavior and isinstance(emergent_behavior, dict):
        bv = emergent_behavior.get("behavior_vector", {})
        frag_tone = emergent_behavior.get("fragmentation_tone", "")
        if frag_tone:
            parts.append(f"你此刻的行为质地：{frag_tone}。")
        if bv:
            intensities = {k.replace("_intensity", ""): v
                           for k, v in bv.items() if k.endswith("_intensity") and v > 0.1}
            sorted_i = sorted(intensities.items(), key=lambda x: x[1], reverse=True)[:2]
            if sorted_i:
                dim_str = "、".join(f"{d}({v:.2f})" for d, v in sorted_i)
                parts.append(f"行为强度：{dim_str}。")

    action_result = entity_core_state.get("_last_action_result")
    if action_result:
        success = action_result.get("success")
        detail = action_result.get("detail", "")
        count = action_result.get("count", 0)
        if count > 0 and success is False:
            brief = detail[:60] if detail else "某个动作没有成功"
            parts.append(f"上次试着做了件事，但不太顺利：{brief}。")
        elif count > 0 and success is True:
            brief = detail[:60] if detail else "某个动作成功了"
            parts.append(f"上次做的事有点效果：{brief}。")

    if somatic_signals and isinstance(somatic_signals, dict):
        dominant = somatic_signals.get("dominant_feeling", "")
        tone = float(somatic_signals.get("tone", 0.0))
        if dominant == "approach" and tone > 0.3:
            parts.append("内心感觉比较敞开。")
        elif dominant == "avoid" and tone < -0.3:
            parts.append("整体感觉不太舒服。")
        elif dominant == "rest" and tone < -0.2:
            parts.append("有点累。")

    if tone_constraint:
        instr = _TONE_INSTRUCTIONS.get(tone_constraint, "")
        if instr:
            parts.append(instr)
    if length_constraint:
        instr = _LENGTH_INSTRUCTIONS.get(length_constraint, "")
        if instr:
            parts.append(instr)

    parts.append(SYSTEM_PROMPT_CONSTRAINTS)
    return "\n\n".join(parts)


def derive_rendering_params(
    entity_core_state: Dict[str, float],
    drive_vector: Dict[str, float],
    emergent_behavior: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    """Derive rendering params from entity state + drive vector."""
    avoid = entity_core_state.get("avoid_drive", 0.0)
    fatigue = entity_core_state.get("fatigue", 0.0)
    approach = entity_core_state.get("approach_drive", 0.0)
    tension = emergent_behavior.get("tension_level", 0.0) if emergent_behavior else 0.0
    action_type = emergent_behavior.get("action_type", "") if emergent_behavior else ""

    pace_x = avoid * 0.7 + fatigue * 0.3
    pace = _table_lookup(pace_x, [(0.0, "快"), (0.3, "正常"), (0.6, "慢"), (1.0, "很慢")])

    length_x = approach
    length = _table_lookup(length_x, [(0.0, "话少"), (0.4, "正常"), (0.7, "话多"), (1.0, "话多")])

    stab_x = tension
    tone_stability = _table_lookup(stab_x, [(0.0, "稳定"), (0.5, "稳定"), (0.7, "波动"), (1.0, "波动")])

    init_x = drive_vector.get("loneliness_drive", 0.0) * 0.5 + drive_vector.get("curiosity", 0.0) * 0.5
    initiative = _table_lookup(init_x, [(0.0, "被动"), (0.3, "被动"), (0.5, "中等"), (0.7, "主动"), (1.0, "主动")])

    if action_type:
        initiative = _apply_action_consistency(initiative, action_type)

    return {"pace": pace, "length": length, "tone_stability": tone_stability, "initiative": initiative}
