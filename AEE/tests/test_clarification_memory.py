# -*- coding: utf-8 -*-
"""Tests for clarification memory record-only behavior."""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from AEE.src.language_system.clarification_memory import (  # noqa: E402
    ClarificationEpisode,
    ClarificationMemory,
    _get_memory,
    maybe_record_displayed_clarification,
)


class _Entity:
    def __init__(self):
        self.tick = 7
        self._understanding_confidence = 0.25
        self._clarification_memory = None
        self._clarification_memory_data = {}


def _episode(kind="generic", slot=None, ts=1000.0):
    return ClarificationEpisode(
        original_input="what is this",
        proposition_frame={
            "slot_confidence": {"actor": 0.2},
            "slot_relevance": {"actor": 0.8},
        },
        clarification_kind=kind,
        clarification_slot=slot,
        question_text="what do you mean",
        confidence=0.25,
        tick=7,
        timestamp=ts,
    )


def test_record_recent_records_and_stats():
    memory = ClarificationMemory()
    memory.record(_episode("generic", None, ts=1000.0))
    memory.record(_episode("targeted", "actor", ts=1010.0))

    records = memory.recent_records(1120.0)
    assert len(records) == 2
    assert records[0]["age_seconds"] == 120.0
    assert math.isclose(records[0]["recency"], math.exp(-120.0 / 240.0))

    stats = memory.stats()
    assert stats["generic_count"] == 1
    assert stats["targeted_count"] == 1
    assert stats["total"] == 2
    assert stats["slot_counts"]["actor"] == 1
    assert stats["slot_confidence"]["count"] == 1.0


def test_memory_roundtrip_ignores_unknown_fields():
    ep = _episode("targeted", "patient", ts=1000.0)
    data = ep.to_dict()
    data["legacy_noise"] = "ignored"

    restored_ep = ClarificationEpisode.from_dict(data)
    restored_memory = ClarificationMemory.from_dict({"history": [data]})

    assert restored_ep.clarification_slot == "patient"
    assert restored_memory.to_dict()["history"][0]["clarification_slot"] == "patient"


def test_get_memory_lazily_restores_entity_mirror():
    entity = _Entity()
    source = ClarificationMemory([_episode("targeted", "predicate", ts=1000.0)])
    entity._clarification_memory_data = source.to_dict()

    memory = _get_memory(entity)

    assert memory is entity._clarification_memory
    assert memory.stats()["slot_counts"]["predicate"] == 1


def test_maybe_record_displayed_clarification_records_targeted_template():
    entity = _Entity()
    templates = [{
        "template": "who is it",
        "clarification_kind": "targeted",
        "clarification_slot": "actor",
    }]
    parse_result = {
        "proposition_frame": {
            "slot_confidence": {"actor": 0.1},
            "slot_relevance": {"actor": 0.9},
        }
    }

    maybe_record_displayed_clarification(
        entity,
        raw_input="someone did something",
        _cx_parse_result=parse_result,
        _chosen_text="who is it",
        _chosen_mode="anchor_auto",
        _tmpl_idx=0,
        all_templates_snapshot=templates,
    )

    history = entity._clarification_memory_data["history"]
    assert len(history) == 1
    assert history[0]["clarification_kind"] == "targeted"
    assert history[0]["clarification_slot"] == "actor"
    assert history[0]["original_input"] == "someone did something"


def test_maybe_record_displayed_clarification_guards_non_clarification():
    entity = _Entity()
    templates = [{"template": "plain answer"}]

    maybe_record_displayed_clarification(
        entity,
        raw_input="hello",
        _cx_parse_result={},
        _chosen_text="plain answer",
        _chosen_mode="anchor_auto",
        _tmpl_idx=0,
        all_templates_snapshot=templates,
    )

    assert entity._clarification_memory_data == {}
