"""
Episodes DB Helpers — dataclasses, importance, internal utilities.

Extracted from episodes_db.py to keep it below 400 lines.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# Importance Computation
# =============================================================================

def compute_importance(
    emotion_intensity: float,
    emotion_polarity: float,
    priority: float,
    is_failed_decision: bool = False,
) -> float:
    """
    Compute episode importance score.

    formula: base = |polarity| * 0.3 + intensity * 0.3 + priority * 0.2
             bonus = 0.3 if is_failed_decision else 0.0
    Returns clamped to [0, 1].
    """
    base = (
        abs(emotion_polarity) * 0.3
        + emotion_intensity * 0.3
        + priority * 0.2
    )
    bonus = 0.3 if is_failed_decision else 0.0
    return min(base + bonus, 1.0)


# =============================================================================
# Episode Dataclass
# =============================================================================

@dataclass
class Episode:
    """
    Raw event log entry.
    Corresponds to one row in episodes.db.
    """
    iteration_id: int
    timestamp: str
    raw_input: Optional[str] = None
    semantic_packet_biased: Optional[Dict[str, Any]] = None
    decision: Optional[Dict[str, Any]] = None
    intent_repr: Optional[Dict[str, Any]] = None
    state_snapshot: Optional[Dict[str, Any]] = None
    drive_vector: Optional[Dict[str, Any]] = None
    output_text: Optional[str] = None
    idle_seconds: float = 0.0
    summary: str = ""
    importance: float = 1.0
    tags: List[str] = field(default_factory=list)
    dispatched_actions: List[Dict[str, Any]] = field(default_factory=list)

    def to_row(self) -> Dict[str, Any]:
        """Convert to DB row format. Logs and returns minimal row on failure."""

        def _sanitize_text(text):
            if not isinstance(text, str):
                return text
            try:
                text.encode("utf-8", errors="strict")
                return text
            except UnicodeEncodeError:
                return text.encode("utf-8", errors="replace").decode("utf-8")

        def _json(val):
            try:
                return json.dumps(val, ensure_ascii=False, default=str)
            except Exception as e:
                import logging as _log
                _log.warning(f"[EpisodesDB] to_row json failed for {type(val).__name__}: {e}")
                return "{}"

        return {
            "iteration_id": self.iteration_id,
            "timestamp": _sanitize_text(self.timestamp),
            "raw_input": _sanitize_text(self.raw_input or ""),
            "semantic_packet_biased": _json(self.semantic_packet_biased or {}),
            "decision": _json(self.decision or {}),
            "intent_repr": _json(self.intent_repr or {}),
            "state_snapshot": _json(self.state_snapshot or {}),
            "drive_vector": _json(self.drive_vector or {}),
            "output_text": _sanitize_text(self.output_text or ""),
            "idle_seconds": self.idle_seconds,
            "summary": _sanitize_text(self.summary or ""),
            "importance": self.importance,
            "tags": _json(self.tags or []),
            "dispatched_actions": _json(self.dispatched_actions or []),
        }


# =============================================================================
# Insight Dataclass
# =============================================================================

@dataclass
class Insight:
    """
    High-emotion-impact cognitive reorganization record.
    """
    insight_type: str
    content: str
    drive_snapshot: str
    source_episode_id: Optional[int] = None
    confidence: float = 0.8
    created_at: float = 0.0
    labels: List[str] = field(default_factory=list)
    id: Optional[int] = None

    def to_row(self) -> Dict[str, Any]:
        def _json(val):
            try:
                return json.dumps(val, ensure_ascii=False, default=str)
            except Exception:
                return "[]"
        return {
            "insight_type": str(self.insight_type),
            "content": str(self.content),
            "drive_snapshot": str(self.drive_snapshot),
            "source_episode_id": self.source_episode_id,
            "confidence": float(self.confidence),
            "created_at": float(self.created_at),
            "labels": _json(self.labels),
        }


# =============================================================================
# Internal Utilities
# =============================================================================

def _row_to_episode(row: Any) -> Episode:
    """Convert DB row to Episode."""
    import sqlite3
    return Episode(
        iteration_id=int(row["iteration_id"]),
        timestamp=row["timestamp"],
        raw_input=row["raw_input"] if row["raw_input"] else None,
        semantic_packet_biased=json.loads(row["semantic_packet_biased"] or "{}"),
        decision=json.loads(row["decision"] or "{}"),
        intent_repr=json.loads(row["intent_repr"] or "{}"),
        state_snapshot=json.loads(row["state_snapshot"] or "{}"),
        drive_vector=json.loads(row["drive_vector"] or "{}"),
        output_text=row["output_text"] if row["output_text"] else None,
        idle_seconds=float(row["idle_seconds"] or 0.0),
        summary=row["summary"] or "",
        importance=float(row["importance"] or 1.0),
        tags=json.loads(row["tags"] or "[]"),
    )


def _row_to_insight(row: Any) -> Insight:
    """Convert DB row to Insight."""
    labels_str = row["labels"] or "[]"
    labels = []
    try:
        labels = json.loads(labels_str)
    except Exception:
        pass
    return Insight(
        id=int(row["id"]) if row["id"] else None,
        insight_type=str(row["insight_type"]),
        content=str(row["content"]),
        drive_snapshot=str(row["drive_snapshot"]),
        source_episode_id=int(row["source_episode_id"]) if row["source_episode_id"] else None,
        confidence=float(row["confidence"]),
        created_at=float(row["created_at"]),
        labels=labels,
    )


def _parse_timestamp(ts: str) -> float:
    """Parse ISO timestamp to Unix time."""
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.timestamp()
    except Exception:
        return 0.0


def _safe_get(d: Dict[str, Any], key: str, default: Any) -> Any:
    return d.get(key, default)


def _current_utc_time() -> str:
    return datetime.now(timezone.utc).isoformat()


# =============================================================================
# Episode Builder
# =============================================================================

def build_episode(
    iteration_id: int,
    raw_input: Optional[str],
    semantic_packet_biased: Dict[str, Any],
    decision: Dict[str, Any],
    intent_repr: Dict[str, Any],
    state_snapshot: Dict[str, Any],
    drive_vector: Dict[str, Any],
    output_text: Optional[str],
    idle_seconds: float,
    was_override: bool = False,
    tags: Optional[List[str]] = None,
    dispatched_actions: Optional[List[Dict[str, Any]]] = None,
    summary: str = "",
) -> Episode:
    """
    Construct Episode from pipeline output.
    """
    emotion = semantic_packet_biased.get("emotion", 0.0)
    intensity = semantic_packet_biased.get("intensity", 0.5)
    priority = float(decision.get("priority", 0.0))

    importance = compute_importance(
        emotion_intensity=intensity,
        emotion_polarity=emotion,
        priority=priority,
        is_failed_decision=was_override,
    )

    all_tags = list(tags or [])
    if semantic_packet_biased.get("intent"):
        all_tags.append(f"intent:{semantic_packet_biased['intent']}")
    if abs(emotion) > 0.5:
        all_tags.append("high_emotion")
    if was_override:
        all_tags.append("failed_decision")
    if not raw_input:
        all_tags.append("internal_tick")

    return Episode(
        iteration_id=iteration_id,
        timestamp=_current_utc_time(),
        raw_input=raw_input,
        semantic_packet_biased=semantic_packet_biased,
        decision=decision,
        intent_repr=intent_repr,
        state_snapshot=state_snapshot,
        drive_vector=drive_vector,
        output_text=output_text,
        idle_seconds=idle_seconds,
        summary=summary,
        importance=importance,
        tags=all_tags,
        dispatched_actions=dispatched_actions or [],
    )
