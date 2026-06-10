"""Source Identity v1 — separate speaker identity from content origin.

The same local input channel can carry different kinds of content:

- bcyq speaking directly to XIA
- bcyq pasting an article or third-party text
- sibling-channel messages

This module provides one small normalization point so source_profiler,
speaker_model, and later processing-depth logic do not keep treating all
external text as one "external" bucket.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

DEFAULT_OWNER_SPEAKER_ID = "bcyq"
DEFAULT_EXTERNAL_SPEAKER_ID = "external"
DIRECT_CHAT_ORIGIN = "direct_chat"
PASTED_TEXT_ORIGIN = "pasted_text"
UNKNOWN_CONTENT_AUTHOR = "unknown"

_DIRECT_ORIGINS = {DIRECT_CHAT_ORIGIN, "ipc_chat", "reach_client"}


def build_source_identity(
    input_source: str,
    entity: Any = None,
    speaker_id: Optional[str] = None,
    content_origin: Optional[str] = None,
    author_id: Optional[str] = None,
) -> Dict[str, str]:
    """Return a normalized source identity dict.

    Keys:
        input_source: raw channel label, e.g. external/sibling/none/ipc_chat
        speaker_id: who delivered the message
        content_origin: what kind of content it is
        author_id: original author when content is not direct speech
        source_id: persistent profile bucket
    """
    raw_source = str(input_source or "none")
    peer_name = _sibling_peer_name(entity)
    speaker = str(speaker_id or _default_speaker(raw_source, peer_name))
    origin = str(content_origin or _default_origin(raw_source))
    author = str(author_id or _default_author(origin, speaker, peer_name))
    source_id = _profile_source_id(raw_source, speaker, origin, author, peer_name)
    return {
        "input_source": raw_source,
        "speaker_id": speaker,
        "content_origin": origin,
        "author_id": author,
        "source_id": source_id,
    }


def source_id_from_identity(identity: Optional[Dict[str, str]]) -> str:
    """Compatibility helper for call sites that only need the profile bucket."""
    data = identity or {}
    return str(data.get("source_id") or "none")


def _sibling_peer_name(entity: Any) -> str:
    try:
        return str(getattr(entity, "_sibling_channel", {}).get("peer_name", "unknown"))
    except Exception:
        return "unknown"


def _default_speaker(input_source: str, peer_name: str) -> str:
    table = {
        "external": DEFAULT_OWNER_SPEAKER_ID,
        "ipc_chat": DEFAULT_OWNER_SPEAKER_ID,
        "sibling": f"sibling:{peer_name}",
        "none": "none",
    }
    return table.get(input_source, DEFAULT_EXTERNAL_SPEAKER_ID)


def _default_origin(input_source: str) -> str:
    table = {
        "external": DIRECT_CHAT_ORIGIN,
        "ipc_chat": DIRECT_CHAT_ORIGIN,
        "sibling": "sibling_channel",
        "none": "none",
    }
    return table.get(input_source, input_source)


def _default_author(content_origin: str, speaker_id: str, peer_name: str) -> str:
    direct_weight = float(content_origin in _DIRECT_ORIGINS)
    sibling_weight = float(content_origin == "sibling_channel")
    unknown_weight = max(0.0, 1.0 - direct_weight - sibling_weight)
    choices = [
        (direct_weight, speaker_id),
        (sibling_weight, f"sibling:{peer_name}"),
        (unknown_weight, UNKNOWN_CONTENT_AUTHOR),
    ]
    return max(choices, key=lambda item: item[0])[1]


def _profile_source_id(
    input_source: str,
    speaker_id: str,
    content_origin: str,
    author_id: str,
    peer_name: str,
) -> str:
    direct_weight = float(content_origin in _DIRECT_ORIGINS)
    sibling_weight = float(input_source == "sibling")
    none_weight = float(input_source == "none")
    content_weight = max(0.0, 1.0 - direct_weight - sibling_weight - none_weight)
    choices = [
        (direct_weight, speaker_id),
        (sibling_weight, f"sibling:{peer_name}"),
        (none_weight, "none"),
        (content_weight, f"{content_origin}:{author_id or UNKNOWN_CONTENT_AUTHOR}"),
    ]
    return max(choices, key=lambda item: item[0])[1]
