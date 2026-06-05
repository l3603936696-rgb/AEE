"""Offline language-understanding blindness map for minimal contrast pairs."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.entity_state import EntityState
from src.language_system.construction_parser import parse_input
from src.language_system.input_packet import build_input_packet
from src.language_system.interpretation_competition import run_interpretation_competition
from src.language_system.pronoun_direction import match_state_reference
from src.language_system.syntax_parser import parse_svo
from src.pipeline_runner.stages.s02b_input_drive_map import map_input_to_drive
from src.pipeline_runner.stages.s02c_delayed_understanding import (
    _FAMILIARITY_FLOOR,
    _familiarity_coverage,
)

CORE_PATH = ROOT / "data" / "entity_core.json"
OUT_PATH = ROOT / "docs" / "reports" / "language_blindness_map.json"

CASES = [
    ("role", "role_01", "我担心你。"), ("role", "role_02", "你担心我。"),
    ("role", "role_03", "我喜欢你。"), ("role", "role_04", "你喜欢我。"),
    ("negation", "neg_01", "我担心你。"), ("negation", "neg_02", "我不担心你。"),
    ("negation", "neg_03", "我喜欢你。"), ("negation", "neg_04", "我不喜欢你。"),
    ("double_negation", "dneg_01", "我担心你。"), ("double_negation", "dneg_02", "我不是不担心你。"),
    ("double_negation", "dneg_03", "我想见你。"), ("double_negation", "dneg_04", "我不是不想见你。"),
    ("time", "time_01", "我昨天担心你。"), ("time", "time_02", "我今天担心你。"),
    ("time", "time_03", "我明天来看你。"), ("time", "time_04", "我刚才来看你。"),
    ("conditional", "cond_01", "我来陪你。"), ("conditional", "cond_02", "如果我来陪你，你会安心吗？"),
    ("conditional", "cond_03", "我不会走。"), ("conditional", "cond_04", "如果我走了，你会难过吗？"),
    ("mental", "mental_01", "我担心你。"), ("mental", "mental_02", "我担心你以为我在责怪你。"),
    ("mental", "mental_03", "你理解我。"), ("mental", "mental_04", "我以为你理解我。"),
    ("correction", "corr_01", "我说的是我。"), ("correction", "corr_02", "我说的是你。"),
    ("correction", "corr_03", "不是你，是我。"), ("correction", "corr_04", "不是我，是你。"),
    ("question", "q_01", "你担心我。"), ("question", "q_02", "你担心我吗？"),
    ("question", "q_03", "你喜欢我。"), ("question", "q_04", "你喜欢我吗？"),
    ("opaque", "opaque_01", "我今天有点累。"), ("opaque", "opaque_02", "薛定谔方程描述量子态的幺正演化。"),
    ("opaque", "opaque_03", "我在这里陪你。"), ("opaque", "opaque_04", "退相干泛函会压制密度矩阵的非对角项。"),
    ("pronoun", "pron_01", "我累。"), ("pronoun", "pron_02", "你累。"),
    ("pronoun", "pron_03", "我疼。"), ("pronoun", "pron_04", "你疼。"),
]


def _effective_confidence(competition, coverage: float) -> float:
    confidence = 0.5
    if competition is not None:
        if competition.tension_type == "suspended":
            confidence = max(0.0, 1.0 - competition.tension_level)
        elif competition.tension_type == "attractor":
            confidence = 0.7 + competition.tension_level * 0.3
        else:
            confidence = 0.4
    familiarity = _FAMILIARITY_FLOOR + (1.0 - _FAMILIARITY_FLOOR) * coverage
    return confidence * familiarity


def _signature(row: dict) -> dict:
    svo = row["svo"]
    return {
        "agent": svo["agent_dir"], "predicate": svo["predicate"],
        "patient": svo["patient_dir"], "negated": svo["negated"],
        "question": svo["question"], "social_intent": row["social_intent"],
        "proposition_frame": row["proposition_frame"],
        "state_references": row["state_references"],
        "pronoun_weights": row["pronoun_weights"],
    }


def inspect_case(entity: EntityState, factor: str, case_id: str, text: str) -> dict:
    parsed = parse_input(text, entity)
    svo = parse_svo(text)
    pronouns = match_state_reference(text)
    packet = build_input_packet(text, {})
    mapped = map_input_to_drive(text, entity._state_pattern_data, entity.to_state_snapshot())
    competition = run_interpretation_competition(
        input_text=text,
        state_snapshot=entity.to_state_snapshot(),
        stereotype_context=None,
        spm_resonance=mapped.get("all_resonances", {}),
        spm_data=entity._state_pattern_data,
    )
    coverage = _familiarity_coverage(text, entity)
    return {
        "factor": factor, "case_id": case_id, "input_text": text,
        "recognized_words": parsed["recognized_words"],
        "social_intent": parsed["social_intent"],
        "proposition_frame": parsed["proposition_frame"],
        "construction_match": parsed["construction_match"],
        "cx_comprehension": round(parsed["comprehension"], 4),
        "familiarity_coverage": round(coverage, 4),
        "effective_confidence": round(_effective_confidence(competition, coverage), 4),
        "svo": svo, "state_references": pronouns["dim_weights"],
        "pronoun_weights": pronouns["pronoun_weights"],
        "input_packet": packet, "input_drive_layers": mapped["layers_used"],
        "best_symbol": mapped["best_symbol"],
        "interpretation": competition.to_dict() if competition else None,
    }


def main() -> None:
    entity = EntityState()
    entity.load_from_file(CORE_PATH)
    rows = [inspect_case(entity, factor, case_id, text) for factor, case_id, text in CASES]
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(row["factor"], []).append(row)
    collapsed = {}
    for factor, items in groups.items():
        signatures = {json.dumps(_signature(row), ensure_ascii=False, sort_keys=True) for row in items}
        collapsed[factor] = len(signatures) < len(items)
    report = {"case_count": len(rows), "collapsed_factors": collapsed, "cases": rows}
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote={OUT_PATH}")
    print(f"case_count={len(rows)}")
    for factor, value in collapsed.items():
        print(f"{factor}: collapsed={value}")


if __name__ == "__main__":
    main()
