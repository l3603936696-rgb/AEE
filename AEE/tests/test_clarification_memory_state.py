# -*- coding: utf-8 -*-
"""EntityState persistence tests for clarification memory mirrors."""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from AEE.src.entity_state import EntityState  # noqa: E402
from AEE.src.language_system.clarification_learning import observe_reply  # noqa: E402
from AEE.src.language_system.clarification_memory import (  # noqa: E402
    ClarificationEpisode,
    ClarificationMemory,
    _get_memory,
)


def _episode(ts=1000.0):
    return ClarificationEpisode(
        original_input="alpha beta",
        proposition_frame={
            "slot_confidence": {"actor": 0.3},
            "slot_relevance": {"actor": 0.9},
        },
        clarification_kind="targeted",
        clarification_slot="actor",
        question_text="who is alpha",
        confidence=0.2,
        tick=3,
        timestamp=ts,
    )


def test_entity_state_persists_clarification_memory_data():
    entity = EntityState()
    entity.tick = 42
    entity._clarification_memory_data = ClarificationMemory([_episode()]).to_dict()

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "entity.json"
        entity.persist_to_file(path)

        restored = EntityState()
        assert restored.load_from_file(path) is True

    memory = _get_memory(restored)
    assert restored.tick == 42
    assert memory.stats()["total"] == 1
    assert memory.stats()["slot_counts"]["actor"] == 1


def test_entity_state_persists_clarification_hints_data_after_reply():
    entity = EntityState()
    entity.tick = 43
    entity._clarification_memory_data = ClarificationMemory([_episode(ts=1000.0)]).to_dict()

    result = observe_reply(
        entity,
        reply_text="alpha",
        now_ts=1005.0,
        source="ipc_chat",
        reply_event_id="reply-1",
    )

    assert result["skipped"] is False
    assert "evidence" in entity._clarification_hints_data
    assert entity._clarification_hints_data["processed_event_ids"] == ["reply-1"]

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "entity.json"
        entity.persist_to_file(path)

        restored = EntityState()
        assert restored.load_from_file(path) is True

    hints = restored._clarification_hints_data
    assert len(hints["evidence"]) == 1
    assert hints["processed_event_ids"] == ["reply-1"]
    assert len(hints["answered_mass"]) == 1
