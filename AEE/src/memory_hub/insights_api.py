"""
Insights API — 显性知识读写接口

供 insights.py 暴露公开 API。
"""

import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .insights_db import DB_PATH, init_db
from .insights_schema import Insight, _infer_type, _extract_situation, _to_dict

logger = logging.getLogger(__name__)


def write_insight(rule: Any) -> bool:
    """
    将一条 wm_rule 升级为 insight，写入数据库。

    幂等：若 wm_rule_ref 已存在则更新 confidence 和 status。
    """
    try:
        init_db()

        rule_dict = _to_dict(rule)
        wm_id = rule_dict.get("id", "")
        if not wm_id:
            return False

        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        cursor = conn.cursor()

        insight_type = _infer_type(rule_dict)
        situation = _extract_situation(rule_dict)
        content = rule_dict.get("content", "")
        confidence = float(rule_dict.get("confidence", 0.5))
        status = rule_dict.get("status", "active")

        now = datetime.now(timezone.utc).isoformat()

        cursor.execute("SELECT id FROM insights WHERE wm_rule_ref = ?", (wm_id,))
        existing = cursor.fetchone()

        if existing:
            insight_id = existing[0]
            cursor.execute(
                "UPDATE insights SET confidence=?, status=? WHERE wm_rule_ref=?",
                (confidence, status, wm_id),
            )
        else:
            insight_id = f"ins_{wm_id}"
            cursor.execute(
                """
                INSERT OR REPLACE INTO insights
                    (id, type, content, situation, wm_rule_ref, confidence, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (insight_id, insight_type, content, situation, wm_id, confidence, status, now),
            )

        conn.commit()
        conn.close()
        logger.debug(f"[Insights] write_insight {insight_id} (wm_ref={wm_id}, conf={confidence:.3f})")
        return True

    except Exception as e:
        logger.warning(f"[Insights] write_insight failed: {e}")
        return False


def write_insight_batch(rules: List[Any]) -> int:
    """批量写入 insight。返回成功写入的条数。"""
    count = 0
    for rule in rules:
        if write_insight(rule):
            count += 1
    return count


def recall_insights(
    tag_strings: List[str],
    min_confidence: float = 0.1,
) -> List[Insight]:
    """
    用概念标签的关键词与 insight.situation 做精确匹配。

    匹配规则：tag in insight.situation OR insight.situation in tag
    """
    try:
        init_db()
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row

        rows = conn.execute(
            """
            SELECT * FROM insights
            WHERE status = 'active' AND confidence >= ?
            ORDER BY confidence DESC
            """,
            (min_confidence,),
        ).fetchall()

        conn.close()

        if not rows:
            return []

        tag_set = {t.strip().lower() for t in tag_strings if t.strip()}
        matched: List[tuple[float, Insight]] = []

        for row in rows:
            situation = str(row["situation"]).lower()
            hit = any(
                (tag in situation or situation in tag)
                for tag in tag_set
            )
            if hit:
                insight = Insight(
                    id=str(row["id"]),
                    type=str(row["type"]),
                    content=str(row["content"]),
                    situation=str(row["situation"]),
                    wm_rule_ref=str(row["wm_rule_ref"]),
                    confidence=float(row["confidence"]),
                    status=str(row["status"]),
                    created_at=str(row["created_at"]),
                )
                matched.append((insight.confidence, insight))

        matched.sort(key=lambda x: x[0], reverse=True)
        return [m for _, m in matched]

    except Exception as e:
        logger.warning(f"[Insights] recall_insights failed: {e}")
        return []


def sync_decay(wm_rules: List[Any]) -> int:
    """
    同步 wm_rules 的衰减状态到 insights 表。

    逻辑：
        - wm_rule 不存在 → 忽略
        - confidence <= 0.1 或 status == "decayed" → 删除
        - 否则更新 confidence / status
    """
    try:
        init_db()
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        cursor = conn.cursor()

        affected = 0
        DECAY_FLOOR = 0.1

        for rule in wm_rules:
            rule_dict = _to_dict(rule)
            wm_id = rule_dict.get("id", "")
            if not wm_id:
                continue

            status = rule_dict.get("status", "active")
            confidence = float(rule_dict.get("confidence", 0.0))

            cursor.execute("SELECT id FROM insights WHERE wm_rule_ref = ?", (wm_id,))
            exists = cursor.fetchone()
            if not exists:
                continue

            if status == "decayed" or confidence <= DECAY_FLOOR:
                cursor.execute("DELETE FROM insights WHERE wm_rule_ref = ?", (wm_id,))
                affected += 1
            else:
                cursor.execute(
                    "UPDATE insights SET confidence=?, status=? WHERE wm_rule_ref=?",
                    (confidence, status, wm_id),
                )
                affected += 1

        conn.commit()
        conn.close()
        if affected > 0:
            logger.info(f"[Insights] sync_decay: {affected} rows affected")
        return affected

    except Exception as e:
        logger.warning(f"[Insights] sync_decay failed: {e}")
        return 0


def get_all_insights(
    min_confidence: float = 0.0,
    status: Optional[str] = None,
) -> List[Insight]:
    """查询所有 insight，支持过滤。"""
    try:
        init_db()
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row

        query = "SELECT * FROM insights WHERE confidence >= ?"
        params: List[Any] = [min_confidence]

        if status:
            query += " AND status = ?"
            params.append(status)

        rows = conn.execute(query, params).fetchall()
        conn.close()

        return [
            Insight(
                id=str(r["id"]),
                type=str(r["type"]),
                content=str(r["content"]),
                situation=str(r["situation"]),
                wm_rule_ref=str(r["wm_rule_ref"]),
                confidence=float(r["confidence"]),
                status=str(r["status"]),
                created_at=str(r["created_at"]),
            )
            for r in rows
        ]

    except Exception as e:
        logger.warning(f"[Insights] get_all_insights failed: {e}")
        return []


def get_insight_count() -> int:
    """返回 insights 表总条数。"""
    try:
        init_db()
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT COUNT(*) as cnt FROM insights").fetchone()
        conn.close()
        return int(row["cnt"]) if row else 0
    except Exception:
        return 0
