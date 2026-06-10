"""
内源校准模块 — 读自己的 episode，回溯验证锚点选择是否准确。

哲学：
    训练时 Hermes 校准（外部反馈），daemon 时她自我校准（内源反馈）。
    不直接修改锚点权重（那是铺路），而是调整淬火效率——
    被验证过的词加速解锁，未验证的保持原速。
"""

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def calibrate_from_episodes(
    entity,
    state: dict,
    limit: int = 5,
) -> dict:
    """
    从最近的自主 episode 回溯验证锚点表达。

    参数:
        entity: EntityState 实例
        state: 当前状态快照（用于元数据记录）
        limit: 回溯 episode 条数

    返回:
        {
            "verified_count": int,       # 验证通过的条数
            "mismatch_count": int,       # 表达和锚点不匹配的条数
            "verification_rate": float,  # 通过率
            "details": [...],            # 每条验证详情
        }
    """
    report = {
        "verified_count": 0,
        "mismatch_count": 0,
        "verification_rate": 0.0,
        "details": [],
    }

    try:
        from .memory_hub.episodes_db import init_db
        import sqlite3, json, os

        db_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "data", "episodes.db"
        )
        init_db()
        db = sqlite3.connect(db_path)
        db.row_factory = sqlite3.Row

        # 读最近的自主锚点 episode（tag 含 "autonomous"）
        rows = db.execute(
            """SELECT * FROM episodes 
               WHERE tags LIKE '%autonomous%' 
               ORDER BY iteration_id DESC LIMIT ?""",
            (limit,)
        ).fetchall()
        db.close()

        episodes = []
        for r in rows:
            ep = dict(r)
            # 解析 JSON 字段
            for field in ('state_snapshot', 'tags'):
                val = ep.get(field)
                if isinstance(val, str) and val.strip():
                    try:
                        ep[field] = json.loads(val)
                    except Exception:
                        pass
            episodes.append(ep)

        if not episodes:
            return report

        from .language_system.somatic_concept_map import SOMATIC_ANCHORS

        # 复用的匹配函数
        def _compute_match(word, anchor, st):
            ok = total = 0
            for dim, delta in anchor.items():
                if dim not in st:
                    continue
                total += 1
                cur = st[dim]
                if (delta >= 0.03 and cur >= 0.5) or (delta <= -0.03 and cur <= 0.3):
                    ok += 1
            if total >= 2:
                return (ok / total) * 0.7 + (total / len(anchor)) * 0.3
            return 0.0

        for ep in episodes:
            # 已通过 SQL WHERE 过滤，只包含 autonomous 标签的 episode
            tags_val = ep.get("tags", [])
            if isinstance(tags_val, list) and "autonomous" not in tags_val:
                continue

            # 提取输出词和状态
            output_text = ep.get("output_text", "")
            if not output_text:
                continue

            state_snapshot = ep.get("state_snapshot", {})
            if not isinstance(state_snapshot, dict) or not state_snapshot:
                continue

            # 从 "又冷又重" 样的表达中提取词
            words = []
            for w in output_text.replace("又", " ").split():
                w = w.strip()
                if w and len(w) <= 8 and w in SOMATIC_ANCHORS:
                    words.append(w)

            if not words:
                continue

            # 对每个词跑锚点匹配
            scores = {}
            for word in words:
                anchor = SOMATIC_ANCHORS.get(word)
                if anchor:
                    scores[word] = _compute_match(word, anchor, state_snapshot)

            if not scores:
                continue

            # 找到该状态下理论上的 TOP 锚点
            top_scored = []
            for _w, _a in SOMATIC_ANCHORS.items():
                s = _compute_match(_w, _a, state_snapshot)
                if s > 0.2:
                    top_scored.append((_w, s))
            top_scored.sort(key=lambda x: x[1], reverse=True)
            theoretical_top = top_scored[0][0] if top_scored else None

            # 验证：说的词是否在理论 TOP 3 里
            actual_words = list(scores.keys())
            theoretical_top3 = [w for w, _ in top_scored[:3]]
            verified = any(w in theoretical_top3 for w in actual_words)

            detail = {
                "iteration_id": ep.get("iteration_id"),
                "said": output_text[:40],
                "words": actual_words,
                "word_scores": {w: round(s, 3) for w, s in scores.items()},
                "theoretical_top": theoretical_top,
                "verified": verified,
            }
            report["details"].append(detail)

            if verified:
                report["verified_count"] += 1
            else:
                report["mismatch_count"] += 1

        total = report["verified_count"] + report["mismatch_count"]
        if total > 0:
            report["verification_rate"] = report["verified_count"] / total

    except Exception as e:
        logger.warning(f"calibrate_from_episodes failed: {e}")

    return report


def apply_calibration(entity, report: dict) -> None:
    """
    根据校准报告调整淬火效率。

    验证通过率高 → 当前锚点选择可靠 → 轻微加速解锁
    验证通过率低 → 当前选择不稳定 → 不做加速，保持谨慎
    """
    if not report or report["verified_count"] + report["mismatch_count"] < 3:
        return

    try:
        rate = report["verification_rate"]
        _q = getattr(entity, "_quenching", None)
        if _q is None:
            return

        # 验证率 ≥ 0.7 → 淬火效率 × 1.1（加速解锁）
        # 验证率 < 0.3 → 不做调整（保持谨慎，等待更多数据）
        if rate >= 0.70:
            old_eff = getattr(_q, "efficiency", 1.0)
            new_eff = min(2.0, old_eff * 1.05)
            _q.efficiency = new_eff
            logger.info(
                f"[Calibration] rate={rate:.0%} → efficiency {old_eff:.2f}→{new_eff:.2f}"
            )
    except Exception:
        pass
