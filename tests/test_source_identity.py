from types import SimpleNamespace

from src.language_system.source_identity import build_source_identity
from src.language_system.source_profiler import get_source_id, update_profile


def _entity():
    return SimpleNamespace(
        _sibling_channel={"peer_name": "nuonuo"},
        _source_profiles={},
    )


def test_external_direct_chat_defaults_to_owner_bucket():
    entity = _entity()

    identity = build_source_identity("external", entity)

    assert identity["speaker_id"] == "bcyq"
    assert identity["content_origin"] == "direct_chat"
    assert identity["author_id"] == "bcyq"
    assert identity["source_id"] == "bcyq"
    assert get_source_id("external", entity) == "bcyq"


def test_pasted_text_keeps_owner_as_deliverer_but_not_profile_bucket():
    entity = _entity()

    identity = build_source_identity(
        "ipc_chat",
        entity,
        speaker_id="bcyq",
        content_origin="pasted_text",
    )

    assert identity["speaker_id"] == "bcyq"
    assert identity["content_origin"] == "pasted_text"
    assert identity["author_id"] == "unknown"
    assert identity["source_id"] == "pasted_text:unknown"


def test_sibling_uses_peer_bucket():
    entity = _entity()

    identity = build_source_identity("sibling", entity)

    assert identity["speaker_id"] == "sibling:nuonuo"
    assert identity["content_origin"] == "sibling_channel"
    assert identity["source_id"] == "sibling:nuonuo"


def test_update_profile_records_identity_metadata():
    entity = _entity()
    identity = build_source_identity("external", entity)

    update_profile(
        entity,
        identity["source_id"],
        cx_recognized_words=[("无聊", 0.8)],
        social_intent="comfort",
        causal_delta={"loneliness": -0.1, "unresolved": -0.05},
        tick=7,
        source_identity=identity,
    )

    profile = entity._source_profiles["bcyq"]
    assert profile["interaction_count"] == 1
    assert profile["speaker_id"] == "bcyq"
    assert profile["content_origin_counts"]["direct_chat"] == 1
    assert profile["word_counts"]["无聊"] == 1
