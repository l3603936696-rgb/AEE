"""
跨 session 学习恢复 — 启动时从 episode 回溯恢复热身词进度。
"""

import logging
import sqlite3
import json
import os
from collections import Counter
from typing import List

logger = logging.getLogger(__name__)

_RECOVERED = False


def recover_learning_from_episodes(entity, limit: int = 50) -> List[str]:
    """
    从最近的自主 episode 恢复消力记录和热身词进度。
    返回: 恢复后解锁的热身词列表
    """
    global _RECOVERED
    if _RECOVERED:
        return []

    try:
        db_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "data", "episodes.db"
        )
        db_path = os.path.abspath(db_path)
        if not os.path.exists(db_path):
            _RECOVERED = True
            return []

        db = sqlite3.connect(db_path)
        db.row_factory = sqlite3.Row
        rows = db.execute(
            "SELECT * FROM episodes WHERE tags LIKE '%autonomous%' ORDER BY iteration_id ASC LIMIT ?",
            (limit,)
        ).fetchall()
        db.close()

        if not rows:
            _RECOVERED = True
            return []

        from .language_system.quenching import QuenchingTracker
        from .language_system.somatic_concept_map import SOMATIC_ANCHORS
        from .language_system.word_warmup import inject_warmup_candidates, get_warm_words

        _q = getattr(entity, "_quenching", None)
        _qd = getattr(entity, "_quenching_data", None)
        if _q is None and _qd and _qd.get("records"):
            _q = QuenchingTracker.from_dict(_qd)
        if _q is None:
            _q = QuenchingTracker()

        recovered_count = 0

        for r in rows:
            ep = dict(r)
            output_text = ep.get("output_text", "") or ""
            state_snapshot = ep.get("state_snapshot")
            if isinstance(state_snapshot, str):
                try:
                    state_snapshot = json.loads(state_snapshot)
                except Exception:
                    continue
            if not isinstance(state_snapshot, dict):
                continue

            for w in output_text.replace("又", " ").split():
                w = w.strip()
                if w and w in SOMATIC_ANCHORS:
                    _q.record(
                        drive_state=state_snapshot,
                        expression=w,
                        delta_unresolved_before=0.0,
                        delta_unresolved_after=0.0,
                        tick=int(ep.get("iteration_id", 0)),
                    )
                    recovered_count += 1

        entity._quenching = _q
        entity._quenching_data = _q.to_dict()

        inject_warmup_candidates(entity, [], min_hits=3, min_best_efficiency=0.15)
        warm = get_warm_words(entity)
        _RECOVERED = True

        logger.info(
            f"[Recover] {len(rows)} episodes → {recovered_count} records → {len(warm)} words: {warm}"
        )
        return warm

    except Exception as e:
        logger.warning(f"[Recover] failed: {e}")
        _RECOVERED = True
        return []
