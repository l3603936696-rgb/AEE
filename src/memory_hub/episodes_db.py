"""
Episodes DB — raw event log persistence layer (SQLite).

First layer: raw event log (Episodes) — always written first, never bypassed.

Storage: data/episodes.db (SQLite)
Write timing: after each pipeline iteration

Submodules:
    episodes_db_schema.py — DB init, table definitions, connection
    episodes_db_helpers.py — dataclasses, importance, builders, utilities
"""

import json
import logging
import time as _time
from typing import Any, Dict, List, Optional

from .episodes_db_schema import DB_PATH, init_db, _get_conn, reset_connection
from .episodes_db_helpers import (
    Episode, Insight,
    compute_importance,
    build_episode,
    _row_to_episode, _row_to_insight,
    _parse_timestamp, _safe_get, _current_utc_time,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Episode Write APIs
# =============================================================================

def write_episode(episode: Episode) -> bool:
    """Write a single Episode to SQLite."""
    try:
        init_db()
        conn = _get_conn()
        conn.execute(
            """
            INSERT OR REPLACE INTO episodes (
                iteration_id, timestamp, raw_input,
                semantic_packet_biased, decision, intent_repr,
                state_snapshot, drive_vector, output_text,
                idle_seconds, summary, importance, tags, dispatched_actions
            ) VALUES (
                :iteration_id, :timestamp, :raw_input,
                :semantic_packet_biased, :decision, :intent_repr,
                :state_snapshot, :drive_vector, :output_text,
                :idle_seconds, :summary, :importance, :tags, :dispatched_actions
            )
            """,
            episode.to_row(),
        )
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"[EpisodesDB] write_episode failed: {e}", exc_info=True)
        return False


def write_episode_async(episode: Episode) -> None:
    """Async write (fire-and-forget, non-blocking)."""
    import threading
    t = threading.Thread(target=_write_episode_bg, args=(episode,), daemon=True)
    t.start()


def _write_episode_bg(episode: Episode) -> None:
    ok = write_episode(episode)
    if ok:
        logger.debug(f"[EpisodesDB] Episode {episode.iteration_id} written")
    else:
        logger.warning(f"[EpisodesDB] Episode {episode.iteration_id} write failed, dropped")


# =============================================================================
# Episode Query APIs
# =============================================================================

def get_recent_episodes(
    limit: int = 50,
    min_importance: float = 0.0,
) -> List[Episode]:
    """Query recent episodes, newest first."""
    try:
        init_db()
        conn = _get_conn()
        rows = conn.execute(
            """
            SELECT * FROM episodes
            WHERE importance >= ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (min_importance, limit),
        ).fetchall()
        return [_row_to_episode(r) for r in rows]
    except Exception as e:
        logger.error(f"[EpisodesDB] get_recent_episodes failed: {e}")
        return []


def get_episode_by_id(iteration_id: int) -> Optional[Episode]:
    """Query episode by iteration_id."""
    try:
        init_db()
        conn = _get_conn()
        row = conn.execute(
            "SELECT * FROM episodes WHERE iteration_id = ?",
            (iteration_id,),
        ).fetchone()
        return _row_to_episode(row) if row else None
    except Exception as e:
        logger.error(f"[EpisodesDB] get_episode_by_id failed: {e}")
        return None


def get_episodes_for_induction(
    since_iteration: int = 0,
    limit: int = 200,
) -> List[Dict[str, Any]]:
    """
    Episode list for world-model induction engine.

    Returns dicts compatible with Snap.from_dict.
    """
    try:
        init_db()
        conn = _get_conn()
        rows = conn.execute(
            """
            SELECT iteration_id, timestamp, raw_input, decision,
                   state_snapshot, drive_vector, semantic_packet_biased
            FROM episodes
            WHERE iteration_id > ?
            ORDER BY timestamp ASC
            LIMIT ?
            """,
            (since_iteration, limit),
        ).fetchall()
        result = []
        for r in rows:
            row = dict(r)
            state_pre = json.loads(row["state_snapshot"] or "{}")
            result.append({
                "snap_index": row["iteration_id"],
                "timestamp": _parse_timestamp(row["timestamp"]),
                "action_type": _safe_get(json.loads(row["decision"] or "{}"), "action_type", ""),
                "target": _safe_get(json.loads(row["decision"] or "{}"), "target", ""),
                "priority": float(_safe_get(json.loads(row["decision"] or "{}"), "priority", 0.0)),
                "pre_state": state_pre,
                "post_state": state_pre,
                "raw_input": row["raw_input"],
                "emotion_polarity": _safe_get(
                    json.loads(row["semantic_packet_biased"] or "{}"), "emotion", 0.0
                ),
                "emotion_intensity": _safe_get(
                    json.loads(row["semantic_packet_biased"] or "{}"), "intensity", 0.5
                ),
            })
        return result
    except Exception as e:
        logger.error(f"[EpisodesDB] get_episodes_for_induction failed: {e}")
        return []


# =============================================================================
# Stats & Maintenance
# =============================================================================

def get_episode_count() -> int:
    """Return total episode count."""
    try:
        init_db()
        conn = _get_conn()
        row = conn.execute("SELECT COUNT(*) as cnt FROM episodes").fetchone()
        return int(row["cnt"]) if row else 0
    except Exception as e:
        logger.error(f"[EpisodesDB] get_episode_count failed: {e}")
        return 0


def get_recent_summaries(k: int = 5) -> List[str]:
    """Fetch summaries of last K conversations, oldest first."""
    try:
        init_db()
        conn = _get_conn()
        rows = conn.execute(
            """
            SELECT iteration_id, summary FROM episodes
            WHERE summary IS NOT NULL AND summary != ''
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (k,),
        ).fetchall()
        if not rows:
            return []
        rows_rev = list(reversed(rows))
        return [f"[第{r[0]}轮] {str(r[1]).strip()}" for r in rows_rev if r[1]]
    except Exception as e:
        logger.error(f"[EpisodesDB] get_recent_summaries failed: {e}")
        return []


def prune_low_importance(min_importance: float = 0.15) -> int:
    """Delete episodes below min_importance threshold. Returns deleted count."""
    try:
        init_db()
        conn = _get_conn()
        cur = conn.execute(
            "DELETE FROM episodes WHERE importance < ?",
            (min_importance,),
        )
        conn.commit()
        deleted = cur.rowcount
        if deleted > 0:
            logger.info(f"[EpisodesDB] Pruned {deleted} low-importance episodes")
        return deleted
    except Exception as e:
        logger.error(f"[EpisodesDB] prune_low_importance failed: {e}")
        return 0


# =============================================================================
# Insight CRUD
# =============================================================================

def write_insight(data: Dict[str, Any]) -> Optional[int]:
    """
    Write a single Insight (INSERT OR IGNORE, dedup).
    Returns new row id or None.
    """
    try:
        init_db()
        conn = _get_conn()
        labels_json = data.get("labels", "[]")
        if isinstance(labels_json, list):
            labels_json = json.dumps(labels_json, ensure_ascii=False)
        row = {
            "insight_type": str(data.get("insight_type", "")),
            "content": str(data.get("content", "")),
            "drive_snapshot": str(data.get("drive_snapshot", "{}")),
            "source_episode_id": data.get("source_episode_id"),
            "confidence": float(data.get("confidence", 0.8)),
            "created_at": float(data.get("created_at", _time.time())),
            "labels": labels_json,
        }
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO episode_insights (
                insight_type, content, drive_snapshot,
                source_episode_id, confidence, created_at, labels
            ) VALUES (
                :insight_type, :content, :drive_snapshot,
                :source_episode_id, :confidence, :created_at, :labels
            )
            """,
            row,
        )
        conn.commit()
        if cursor.rowcount > 0:
            return cursor.lastrowid
        return None
    except Exception as e:
        logger.error(f"[EpisodesDB] write_insight failed: {e}")
        return None


def get_recent_insights(limit: int = 20) -> List[Insight]:
    """Query recent insights, newest first."""
    try:
        init_db()
        conn = _get_conn()
        rows = conn.execute(
            """
            SELECT * FROM episode_insights
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [_row_to_insight(r) for r in rows]
    except Exception as e:
        logger.error(f"[EpisodesDB] get_recent_insights failed: {e}")
        return []


def retrieve_insights_by_labels(
    labels: List[str],
    limit: int = 5,
) -> List[Insight]:
    """Recall insights by label tags (fuzzy LIKE match)."""
    if not labels:
        return []
    try:
        init_db()
        conn = _get_conn()
        conditions = " OR ".join(["labels LIKE ?"] * len(labels))
        params = [f'%"{lab}"%' for lab in labels] + [limit]
        rows = conn.execute(
            f"""
            SELECT * FROM episode_insights
            WHERE {conditions}
            ORDER BY confidence DESC, created_at DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [_row_to_insight(r) for r in rows]
    except Exception as e:
        logger.error(f"[EpisodesDB] retrieve_insights_by_labels failed: {e}")
        return []
