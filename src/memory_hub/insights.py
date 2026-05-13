"""
Insights DB — 显性知识持久化层

第三层：结构化知识存储 (Insights) —— 本地 SQLite

来源：世界模型归纳出的高置信规律升级而来（world_model_update管线触发）。
不属于推理生成，不走 LLM。

存储位置：data/episodes.db（与 episodes 共用同一个 DB 文件，不同表）

写入时机：world_model_update 管线完成，且规则升为 active 且置信度 >= 0.7
衰减时机：随 wm_rules 同步衰减（规则降级/衰减时对应 insight 同步衰减或删除）

表结构：
    id          : insight 唯一标识
    type        : "user_preference" | "situation_pattern"
    content     : 可读描述（来自规则的 content 字段）
    situation   : 触发情境关键词（精确匹配用，来自规则的 context 标签）
    wm_rule_ref : 关联的 wm_rule ID（用于追溯和同步衰减）
    confidence  : 置信度（跟随 wm_rule.confidence）
    status      : "active" | "decayed"
    created_at  : 创建时间戳
"""

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ============================================================================
# 路径常量（与 episodes_db.py 共用同一 DB 文件）
# ============================================================================

def _get_db_path() -> Path:
    """动态计算 DB 路径，避免模块导入时 __file__ 相对路径陷阱。"""
    # __file__ 解析到 /home/bcyq/XIA/src/memory_hub/insights.py
    # .resolve() → 绝对路径，无论从哪里 import 都正确
    data_dir = Path(__file__).resolve().parent.parent.parent / "data"
    return data_dir / "episodes.db"

DB_PATH = _get_db_path()


# ============================================================================
# 数据库初始化
# ============================================================================

_Initialized = False


def init_db() -> None:
    """初始化 insights 表（幂等）。"""
    global _Initialized
    if _Initialized:
        return
    try:
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        # 检测旧表（episodes_db 创建的版本，列名不兼容）并清理
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
        # 迁移：旧表可能缺少 situation / status / wm_rule_ref 列
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


# ============================================================================
# 数据结构
# ============================================================================

@dataclass
class Insight:
    """显性知识条目。"""
    id: str
    type: str           # "user_preference" | "situation_pattern"
    content: str        # 可读描述
    situation: str      # 触发情境关键词
    wm_rule_ref: str    # 关联的 wm_rule ID
    confidence: float
    status: str         # "active" | "decayed"
    created_at: str


# ============================================================================
# 字段提取规则（纯代码，不走 LLM）
# ============================================================================

def _infer_type(rule: Dict[str, Any]) -> str:
    """
    从规则字段自动判定 insight type。

    规则：
        - context 含 "correction" / "用户纠正" / "纠正" → user_preference
        - context 含 "偏好" / "preference" → user_preference
        - context 含 "pattern" / "情境" / "pattern" → situation_pattern
        - 否则默认 user_preference（用户意图相关）
    """
    context = rule.get("context", "").lower()
    content = rule.get("content", "").lower()

    preference_signals = {"correction", "纠正", "preference", "偏好", "用户", "不喜欢", "喜欢", "不要"}
    pattern_signals = {"pattern", "情境", "模式", "反复", "重复"}

    for sig in pattern_signals:
        if sig in context or sig in content:
            return "situation_pattern"

    for sig in preference_signals:
        if sig in context or sig in content:
            return "user_preference"

    return "user_preference"


def _extract_situation(rule: Dict[str, Any]) -> str:
    """
    从规则 trigger 字段提取触发情境关键词。

    格式：action_{type}_in_{context_label}
    示例：action_seek_in_high_energy → "high_energy"
    """
    trigger = rule.get("predicts", {}).get("trigger", "")
    if not trigger:
        # 兜底：用 context 字段
        return rule.get("context", "").lower()

    # 去掉前缀 "action_XXX_in_"
    if "_in_" in trigger:
        return trigger.split("_in_", 1)[-1]
    return trigger.lower()


# ============================================================================
# 核心写入 API
# ============================================================================

def write_insight(rule: Dict[str, Any]) -> bool:
    """
    将一条 wm_rule 升级为 insight，写入数据库。

    幂等：若 wm_rule_ref 已存在则更新 confidence 和 status。

    参数：
        rule : wm_rule 字典（Rule.to_dict() 格式或 Rule 对象）
               必须包含：id, content, context, predicts

    返回：
        bool : 写入是否成功
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

        # 检查是否已存在
        cursor.execute("SELECT id FROM insights WHERE wm_rule_ref = ?", (wm_id,))
        existing = cursor.fetchone()

        if existing:
            insight_id = existing[0]
            # 更新置信度和状态
            cursor.execute(
                """
                UPDATE insights
                SET confidence=?, status=?
                WHERE wm_rule_ref=?
                """,
                (confidence, status, wm_id),
            )
        else:
            # 写入新记录
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


def write_insight_batch(rules: List[Dict[str, Any]]) -> int:
    """
    批量写入 insight。返回成功写入的条数。
    """
    count = 0
    for rule in rules:
        if write_insight(rule):
            count += 1
    return count


# ============================================================================
# 召回 API（精确匹配）
# ============================================================================

def recall_insights(
    tag_strings: List[str],
    min_confidence: float = 0.1,
) -> List[Insight]:
    """
    用概念标签的关键词与 insight.situation 做精确匹配。

    匹配规则：
        tag in insight.situation OR insight.situation in tag

    参数：
        tag_strings    : 概念标签列表，如 ["求助", "负面情绪", "高强度"]
        min_confidence : 最低置信度阈值，默认 0.1

    返回：
        List[Insight] : 匹配到的 insight 列表（按 confidence 降序）
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
            # 精确匹配：标签词是否出现在 situation 中，或 situation 是否是标签的子串
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

        # 按置信度降序
        matched.sort(key=lambda x: x[0], reverse=True)
        return [m for _, m in matched]

    except Exception as e:
        logger.warning(f"[Insights] recall_insights failed: {e}")
        return []


# ============================================================================
# 衰减同步 API
# ============================================================================

def sync_decay(wm_rules: List[Dict[str, Any]]) -> int:
    """
    同步 wm_rules 的衰减状态到 insights 表。

    逻辑：
        - wm_rule 不存在于表中 → 忽略（可能是新规则，尚未升级）
        - wm_rule.confidence 低于移除阈值（0.1）→ 删除对应 insight
        - wm_rule.status == "decayed" → 删除对应 insight
        - wm_rule 存在且 confidence 有效 → 更新 confidence

    参数：
        wm_rules : 当前 wm_rules 列表（Rule 字典或对象）

    返回：
        int : 同步影响的行数
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

            # 检查是否存在
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


# ============================================================================
# 查询 API
# ============================================================================

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


# ============================================================================
# 内部辅助
# ============================================================================

def _to_dict(rule: Any) -> Dict[str, Any]:
    """将 Rule 对象或字典统一转换为 dict。"""
    if isinstance(rule, dict):
        return rule
    if hasattr(rule, "to_dict"):
        return rule.to_dict()
    return {}


# ============================================================================
# 测试入口
# ============================================================================

if __name__ == "__main__":
    import time

    print("=" * 60)
    print("Insights DB — 单元测试")
    print("=" * 60)

    # 测试环境清理：删除残留数据，确保测试独立性
    init_db()
    import sqlite3 as _sq3
    _c = _sq3.connect(str(DB_PATH))
    _c.execute("DELETE FROM insights")
    _c.commit()
    _c.close()

    # 测试 1: 写入
    print("\n【测试 1】write_insight — 正常写入")
    rule1 = {
        "id": "wmu_abc12345",
        "content": "高能量时执行seek动作，信息差下降均值-0.100，对照组自然变化均值-0.010，区分度0.090",
        "confidence": 0.75,
        "status": "active",
        "context": "high_energy",
        "predicts": {"trigger": "action_seek_in_high_energy", "expect": "info_gap_decrease"},
    }
    ok1 = write_insight(rule1)
    print(f"  {'✓' if ok1 else '✗'} write_insight = {ok1}")

    # 测试 2: 幂等写入（重复调用不报错）
    print("\n【测试 2】write_insight — 幂等更新")
    rule1_updated = dict(rule1)
    rule1_updated["confidence"] = 0.82
    ok2 = write_insight(rule1_updated)
    count = get_insight_count()
    ok2 = ok2 and count == 1
    print(f"  {'✓' if ok2 else '✗'} 幂等写入后 count = {count}（期望 1）")

    # 测试 3: recall_insights — 精确匹配命中
    print("\n【测试 3】recall_insights — 命中")
    matched = recall_insights(["high_energy", "seek"])
    ok3 = len(matched) >= 1
    print(f"  {'✓' if ok3 else '✗'} tag=[high_energy] 命中 {len(matched)} 条")
    if matched:
        print(f"     → {matched[0].content[:50]}...")

    # 测试 4: recall_insights — 不匹配
    print("\n【测试 4】recall_insights — 未命中")
    matched4 = recall_insights(["完全不相关", "xyz"])
    ok4 = len(matched4) == 0
    print(f"  {'✓' if ok4 else '✗'} tag=[完全不相关] 命中 {len(matched4)} 条（期望 0）")

    # 测试 5: 字段提取规则
    print("\n【测试 5】_infer_type — 自动类型判定")
    rule_correction = {"context": "用户纠正", "content": "bcyq不喜欢被叫老师"}
    rule_pattern = {"context": "高能量情境", "content": "seek动作导致info_gap下降"}
    t1 = _infer_type(rule_correction)
    t2 = _infer_type(rule_pattern)
    ok5 = t1 == "user_preference" and t2 == "situation_pattern"
    print(f"  {'✓' if ok5 else '✗'} 纠正类→{t1}，情境类→{t2}")

    # 测试 6: _extract_situation
    print("\n【测试 6】_extract_situation — trigger 解析")
    rule_trigger = {"predicts": {"trigger": "action_seek_in_high_energy"}, "context": ""}
    s1 = _extract_situation(rule_trigger)
    rule_fallback = {"context": "high_loneliness", "predicts": {}}
    s2 = _extract_situation(rule_fallback)
    ok6 = s1 == "high_energy" and s2 == "high_loneliness"
    print(f"  {'✓' if ok6 else '✗'} trigger→{s1}，fallback→{s2}")

    # 测试 7: sync_decay — 置信度降级（用独立ID，不影响rule1）
    print("\n【测试 7】sync_decay — 置信度降低触发删除")
    write_insight({"id": "wmu_decay_t7", "content": "衰减测试7",
                   "confidence": 0.75, "status": "active",
                   "context": "decay_t7", "predicts": {}})
    sync_decay([{"id": "wmu_decay_t7", "confidence": 0.05, "status": "active"}])
    count_after7 = get_insight_count()
    # 此时剩 rule1 + decay_t7(被删)，count应为1
    ok7 = count_after7 == 1
    print(f"  {'✓' if ok7 else '✗'} conf=0.05后insight被删除，count={count_after7}（期望1）")

    # 测试 8: sync_decay — decayed状态（用独立ID）
    print("\n【测试 8】sync_decay — decayed状态")
    write_insight({"id": "wmu_decayed_t8", "content": "衰减测试8",
                   "confidence": 0.5, "status": "active",
                   "context": "test8", "predicts": {}})
    sync_decay([{"id": "wmu_decayed_t8", "confidence": 0.3, "status": "decayed"}])
    count8 = get_insight_count()
    # 此时剩 rule1 + decay_t7(已删)，count应为1
    ok8 = count8 == 1
    print(f"  {'✓' if ok8 else '✗'} status=decayed后insight删除，count={count8}（期望1）")

    # 测试 9: get_all_insights
    print("\n【测试 9】get_all_insights")
    write_insight({"id": "wmu_test9", "content": "测试9",
                   "confidence": 0.6, "status": "active",
                   "context": "test9", "predicts": {}})
    all_ins = get_all_insights()
    ok9 = len(all_ins) >= 1
    print(f"  {'✓' if ok9 else '✗'} get_all_insights 返回 {len(all_ins)} 条")

    # 测试 10: get_insight_count
    print("\n【测试 10】get_insight_count")
    count10 = get_insight_count()
    print(f"  当前 insight 总数: {count10}")

    print("\n" + "=" * 60)
    all_ok = ok1 and ok2 and ok3 and ok4 and ok5 and ok6 and ok7 and ok8 and ok9
    print(f"测试结果: {'全部通过 ✓' if all_ok else '部分失败 ✗'}")
    print("=" * 60)
