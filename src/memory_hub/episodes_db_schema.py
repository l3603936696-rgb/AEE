"""
Episodes DB Schema — database initialization and table definitions.

Extracted from episodes_db.py to keep it below 400 lines.
"""

import logging
import sqlite3
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent.parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "episodes.db"


# Singleton connection
_Connection: Optional[sqlite3.Connection] = None
_Initialized = False


def _get_conn() -> sqlite3.Connection:
    """Get DB connection (lazy singleton)."""
    global _Connection
    if _Connection is None:
        _Connection = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _Connection.row_factory = sqlite3.Row
    return _Connection


def init_db() -> None:
    """Initialize database tables. Skips if already initialized."""
    global _Initialized
    if _Initialized:
        return
    conn = _get_conn()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS episodes (
            iteration_id    INTEGER PRIMARY KEY,
            timestamp       TEXT    NOT NULL,
            raw_input       TEXT,
            semantic_packet_biased TEXT,
            decision        TEXT,
            intent_repr     TEXT,
            state_snapshot  TEXT,
            drive_vector    TEXT,
            output_text     TEXT,
            idle_seconds    REAL    DEFAULT 0.0,
            summary         TEXT    DEFAULT '',
            importance      REAL    DEFAULT 1.0,
            tags            TEXT    DEFAULT '[]',
            dispatched_actions TEXT  DEFAULT '[]'
        )
    """)
    try:
        conn.execute("ALTER TABLE episodes ADD COLUMN dispatched_actions TEXT DEFAULT '[]'")
    except Exception:
        pass

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_episodes_timestamp
        ON episodes(timestamp DESC)
    """)

    # v11.0: episode_insights table (distinct from insights.py)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS episode_insights (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            insight_type   TEXT    NOT NULL,
            content        TEXT    NOT NULL,
            drive_snapshot TEXT    NOT NULL,
            source_episode_id INTEGER,
            confidence     REAL    DEFAULT 0.8,
            created_at     REAL    NOT NULL,
            labels         TEXT    DEFAULT '[]'
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_epinsights_created_at
        ON episode_insights(created_at DESC)
    """)

    conn.commit()
    _Initialized = True
    logger.info(f"Episodes DB initialized at {DB_PATH}")


def reset_connection() -> None:
    """Reset singleton connection (for testing only)."""
    global _Connection, _Initialized
    _Connection = None
    _Initialized = False
