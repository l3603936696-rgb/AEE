"""
Insights DB — 数据库初始化与路径管理

供 insights_api.py 调用。
"""

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)


def _get_db_path() -> Path:
    """动态计算 DB 路径，避免模块导入时 __file__ 相对路径陷阱。"""
    data_dir = Path(__file__).resolve().parent.parent.parent.parent / "data"
    return data_dir / "episodes.db"


DB_PATH = _get_db_path()

_Initialized = False


def init_db() -> None:
    """初始化 insights 表（幂等）。"""
    global _Initialized
    if _Initialized:
        return
    try:
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        try:
            _cols = {row[1] for row in conn.execute("PRAGMA table_info(insights)")}
            if "insight_type" in _cols and "type" not in _cols:
                conn.execute("DROP TABLE insights")
                logger.info("[Insights] 清理旧版表（episodes_db 创建），重建兼容版本")
        except Exception:
            pass
        conn.execute("""
            CREATE TABLE IF NOT EXISTS insights (
                id           TEXT PRIMARY KEY,
                type         TEXT NOT NULL,
                content      TEXT NOT NULL,
                situation    TEXT NOT NULL DEFAULT '',
                wm_rule_ref  TEXT NOT NULL,
                confidence   REAL NOT NULL,
                status       TEXT NOT NULL DEFAULT 'active',
                created_at   TEXT NOT NULL
            )
        """)
        try:
            _existing = {row[1] for row in conn.execute("PRAGMA table_info(insights)")}
            for _col, _typedef in [
                ("wm_rule_ref", "TEXT NOT NULL DEFAULT ''"),
                ("situation", "TEXT NOT NULL DEFAULT ''"),
                ("status", "TEXT NOT NULL DEFAULT 'active'"),
            ]:
                if _col not in _existing:
                    conn.execute(f"ALTER TABLE insights ADD COLUMN {_col} {_typedef}")
                    logger.info(f"[Insights] 迁移：添加缺失列 {_col}")
        except Exception:
            pass
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_insights_situation
            ON insights(situation)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_insights_wm_rule_ref
            ON insights(wm_rule_ref)
        """)
        conn.commit()
        conn.close()
        _Initialized = True
        logger.info(f"Insights table ready at {DB_PATH}")
    except Exception as e:
        logger.warning(f"[Insights] init_db failed: {e}")


def get_db_path() -> Path:
    """暴露 DB_PATH 给测试文件。"""
    return DB_PATH
