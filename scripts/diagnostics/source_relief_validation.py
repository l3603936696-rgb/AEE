"""Offline validation for source identity v1 and expression relief v1.

This probe is intentionally low-disturbance: it does not start or restart the
daemon, does not read/write entity_core.json, and only uses fresh in-memory
objects. It is meant to catch the two main failure modes:

1. bcyq direct chat being mixed back into the generic external bucket.
2. pure logical connectors earning strong expression relief.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.language_system.expression_relief import compute_relief
from src.language_system.source_identity import build_source_identity
from src.language_system.source_profiler import update_profile


def _entity() -> SimpleNamespace:
    return SimpleNamespace(
        _sibling_channel={"peer_name": "nuonuo"},
        _source_profiles={},
    )


def _relief_diag(expression: str, novelty: float = 1.0) -> dict:
    state = {
        "boredom": 0.97,
        "unresolved": 0.8,
        "info_gap": 0.9,
        "avoid": 0.5,
        "somatic_tone": 0.5,
        "loneliness": 0.8,
    }
    return compute_relief(expression, state, novelty)["diagnostics"]


def validate_source_identity() -> dict:
    entity = _entity()
    direct = build_source_identity("external", entity)
    pasted = build_source_identity(
        "ipc_chat",
        entity,
        speaker_id="bcyq",
        content_origin="pasted_text",
    )
    sibling = build_source_identity("sibling", entity)

    update_profile(
        entity,
        direct["source_id"],
        cx_recognized_words=[("boredom_marker", 0.8)],
        social_intent="comfort",
        causal_delta={"loneliness": -0.1, "unresolved": -0.05},
        tick=7,
        source_identity=direct,
    )

    profile = entity._source_profiles["bcyq"]
    checks = {
        "direct_source_id_is_bcyq": direct["source_id"] == "bcyq",
        "direct_origin_is_chat": direct["content_origin"] == "direct_chat",
        "pasted_source_not_bcyq": pasted["source_id"] == "pasted_text:unknown",
        "pasted_delivered_by_bcyq": pasted["speaker_id"] == "bcyq",
        "sibling_source_is_peer": sibling["source_id"] == "sibling:nuonuo",
        "profile_origin_counted": profile["content_origin_counts"]["direct_chat"] == 1,
        "profile_speaker_recorded": profile["speaker_id"] == "bcyq",
    }
    return {
        "direct": direct,
        "pasted": pasted,
        "sibling": sibling,
        "profile": profile,
        "checks": checks,
    }


def validate_expression_relief() -> dict:
    pure = _relief_diag("因为所以但是")
    plain = _relief_diag("有点无聊了")
    causal = _relief_diag("无聊了，因为没有人来")
    repeated = _relief_diag("无聊了，因为没有人来", novelty=0.2)

    checks = {
        "pure_connectors_low_accuracy": pure["accuracy"] <= 0.05,
        "pure_connectors_weak_vs_causal": pure["relief"] < causal["relief"] * 0.1,
        "causal_beats_plain": causal["relief"] > plain["relief"],
        "repetition_discount_reduces": repeated["relief"] < causal["relief"],
        "no_loneliness_delta": "loneliness_delta" not in causal,
    }
    return {
        "pure_connectors": pure,
        "plain_naming": plain,
        "causal_naming": causal,
        "repeated_causal": repeated,
        "checks": checks,
    }


def main() -> None:
    source = validate_source_identity()
    relief = validate_expression_relief()
    failed = [
        name
        for group in (source["checks"], relief["checks"])
        for name, ok in group.items()
        if not ok
    ]
    print(json.dumps({
        "source_identity": source,
        "expression_relief": relief,
        "failed": failed,
    }, ensure_ascii=False, indent=2))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
