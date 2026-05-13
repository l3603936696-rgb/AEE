"""
Episodes DB — 原始事件日志持久化层

第一层：原始事件日志 (Episodes) —— 本地 SQLite，永远先写

这是记忆系统的绝对底线。不依赖 TetraMem、不依赖 JSON、不依赖任何外部服务。
每次管线结束后立刻写入，记录"发生了什么"的完整事实。

存储位置：data/episodes.db（SQLite）

写入时机：每轮管线结束后，在主迭代引擎的异步循环里立刻写入。

数据内容（每条 Episode）：
    - iteration_id  ：轮次编号
    - timestamp     ：UTC 时间戳
    - raw_input     ：用户输入原文
    - semantic_packet_biased ：感性认识 + 记忆偏置后的语义包
    - decision      ：裁决系统输出的完整决策
    - intent_repr   ：意图编码器输出的生成上下文
    - state_snapshot：实体状态快照
    - drive_vector  ：驱动力向量
    - output_text   ：输出层生成的回复
    - idle_seconds  ：本轮空闲时间
    - summary       ：自动摘要（预留，当前为空）
    - importance    ：重要性评分（基于情绪强度）
    - tags          ：标签列表（JSON 序列化）
"""

import json
import logging
import math
import os
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ============================================================================
# 路径常量
# ============================================================================

DATA_DIR = Path(__file__).parent.parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "episodes.db"


# ============================================================================
# 数据库初始化
# ============================================================================

_Connection: Optional[sqlite3.Connection] = None
_Initialized = False


def _get_conn() -> sqlite3.Connection:
    """获取数据库连接（单例懒加载）。"""
    global _Connection
    if _Connection is None:
        _Connection = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _Connection.row_factory = sqlite3.Row
    return _Connection


def init_db() -> None:
    """初始化数据库表。若表已存在则跳过，并确保所有列都存在。"""
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
    # 旧数据库可能没有 dispatched_actions 列，补充添加
    try:
        conn.execute("ALTER TABLE episodes ADD COLUMN dispatched_actions TEXT DEFAULT '[]'")
    except Exception:
        pass
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_episodes_timestamp
        ON episodes(timestamp DESC)
    """)

    # v11.0 新增：episode_insights 表（高情绪冲击事件的显性认知重组）
    # 注：独立于 insights.py 的 insights 表，两者结构不同各司其职
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


# ============================================================================
# 重要性计算
# ============================================================================

def compute_importance(
    emotion_intensity: float,
    emotion_polarity: float,
    priority: float,
    is_failed_decision: bool = False,
) -> float:
    """
    计算单条 Episode 的重要性评分。

    公式：
        base = |polarity| * 0.3 + intensity * 0.3 + priority * 0.2
        bonus = 0.3 if is_failed_decision else 0.0
        return min(base + bonus, 1.0)

    参数：
        emotion_intensity    : 情绪强度 [0, 1]
        emotion_polarity    : 情绪极性 [-1, 1]
        priority            : 决策优先级 [0, 1]
        is_failed_decision  : 是否失败决策

    返回：
        importance : [0.0, 1.0]
    """
    base = (
        abs(emotion_polarity) * 0.3
        + emotion_intensity * 0.3
        + priority * 0.2
    )
    bonus = 0.3 if is_failed_decision else 0.0
    return min(base + bonus, 1.0)


# ============================================================================
# 数据结构
# ============================================================================

@dataclass
class Episode:
    """
    原始事件日志条目。

    对应 episodes.db 中的一条记录。
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
        """转换为数据库行格式。失败时记日志并返回最小行。"""

        def _sanitize_text(text):
            """移除无效UTF-8代理字符，防止UnicodeEncodeError导致整条写入失败。"""
            if not isinstance(text, str):
                return text
            try:
                text.encode("utf-8", errors="strict")
                return text
            except UnicodeEncodeError:
                # lone surrogates → 替换为问号（安全降级，不丢弃整条记录）
                return text.encode("utf-8", errors="replace").decode("utf-8")

        def _json(val):
            """安全序列化，失败时返回空字符串并记警告。"""
            try:
                return json.dumps(val, ensure_ascii=False, default=str)
            except Exception as e:
                import logging as _log
                _log.warning(
                    f"[EpisodesDB] to_row: json.dumps failed for {type(val).__name__}: {e}"
                )
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


# ============================================================================
# 核心写入 API
# ============================================================================

def write_episode(episode: Episode) -> bool:
    """
    写入单条 Episode 到 SQLite。

    参数：
        episode : Episode 对象

    返回：
        bool : 写入是否成功
    """
    try:
        init_db()
        conn = _get_conn()
        row = episode.to_row()
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
            row,
        )
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"[EpisodesDB] write_episode failed: {e}", exc_info=True)
        return False


def write_episode_async(episode: Episode) -> None:
    """
    异步写入 Episode（fire-and-forget）。

    在同步管线完成后立即调用，不阻塞主流程。
    失败只记日志，不阻断任何逻辑。
    """
    import threading
    t = threading.Thread(target=_write_episode_bg, args=(episode,), daemon=True)
    t.start()


def _write_episode_bg(episode: Episode) -> None:
    """后台线程写入（不应被主线程等待）。"""
    ok = write_episode(episode)
    if ok:
        logger.debug(f"[EpisodesDB] Episode {episode.iteration_id} written")
    else:
        logger.warning(f"[EpisodesDB] Episode {episode.iteration_id} write failed, dropped")


# ============================================================================
# 查询 API
# ============================================================================

def get_recent_episodes(
    limit: int = 50,
    min_importance: float = 0.0,
) -> List[Episode]:
    """
    查询最近的 Episode 列表。

    参数：
        limit          : 返回条数上限
        min_importance : 最小重要性过滤

    返回：
        List[Episode] : 按时间倒序
    """
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
    """按 iteration_id 查询单条 Episode。"""
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
    供世界模型归纳引擎读取的 Episode 列表。

    专门为 world_model_update.induct 准备，返回 dict 而非 Episode 对象，
    与 Snap.from_dict 兼容。

    参数：
        since_iteration : 从哪个 iteration_id 开始（不含）
        limit           : 最大返回条数

    返回：
        List[Dict] : 适配 world_model_update/rules.py Snap 格式的 dict 列表
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
                "post_state": state_pre,  # episodes 表暂不区分 pre/post，以 state_snapshot 代替
                "raw_input": row["raw_input"],
                "emotion_polarity": _safe_get(
                    json.loads(row["semantic_packet_biased"] or "{}"),
                    "emotion", 0.0
                ),
                "emotion_intensity": _safe_get(
                    json.loads(row["semantic_packet_biased"] or "{}"),
                    "intensity", 0.5
                ),
            })
        return result
    except Exception as e:
        logger.error(f"[EpisodesDB] get_episodes_for_induction failed: {e}")
        return []


# ============================================================================
# 语义相似召回 — TF-IDF + 余弦相似度
# ============================================================================

def _tokenize(text: str) -> List[str]:
    """
    中文 + 英文分词，返回词级 token 和字 bigram。

    策略：
    - 英文/数字：按空格拆分，保留长度>=2 的词
    - 中文词：提取连续汉字序列（长度>=2）
    - 中文 bigram：逐字生成 bigram，捕捉单字相似性
    - 停用词过滤（词级 token）
    """
    if not text:
        return []
    text = text.replace("\u3000", " ").replace("　", " ")

    tokens: list[str] = []

    # 英文/数字词
    for part in re.split(r"[^\w]+", text.lower()):
        if part and len(part) >= 2 and part.isalpha():
            tokens.append(part)

    # 中文词：连续汉字序列（长度>=2）
    chinese_seqs = re.findall(r"[\u4e00-\u9fff]{2,}", text)
    stopwords = {
        "一个", "这个", "那个", "什么", "怎么", "为什么",
        "没有", "不是", "都是", "还是", "可以", "已经",
        "现在", "就是", "然后", "但是", "所以", "因为",
        "如果", "虽然", "或者", "以及", "而且", "只是",
        "的时候", "一下", "什么", "怎么", "没有",
    }
    for seq in chinese_seqs:
        if seq not in stopwords:
            tokens.append(seq)
        # 同时生成 bigram（短词也能捕捉）
        for i in range(len(seq) - 1):
            tokens.append(seq[i : i + 2])

    return tokens


def _compute_tf(tokens: List[str]) -> Dict[str, float]:
    """计算词频 TF。"""
    if not tokens:
        return {}
    counts = Counter(tokens)
    total = len(tokens)
    return {word: count / total for word, count in counts.items()}


def _compute_idf(documents: List[List[str]]) -> Dict[str, float]:
    """计算逆文档频率 IDF。N = 文档总数，df = 包含该词的文档数。"""
    n = len(documents)
    if n == 0:
        return {}
    df: Counter = Counter()
    for tokens in documents:
        for word in set(tokens):
            df[word] += 1
    return {
        word: math.log(n / (df[word] + 1)) + 1.0
        for word in df
    }


def _cosine(a: Dict[str, float], b: Dict[str, float]) -> float:
    """计算两个 TF-IDF 向量的余弦相似度。"""
    common = set(a.keys()) & set(b.keys())
    if not common:
        return 0.0
    dot = sum(a[w] * b[w] for w in common)
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def retrieve_episodes_by_text(
    query: str,
    limit: int = 3,
    min_similarity: float = 0.05,
    exclude_iteration_id: Optional[int] = None,
) -> List[Episode]:
    """
    基于用户输入文本，从 episodes 表中召回语义相似的经验。

    使用 TF-IDF + 余弦相似度，无需外部嵌入服务。

    参数：
        query               : 用户输入文本
        limit               : 最多返回条数
        min_similarity      : 最低相似度阈值（低于此值不返回）
        exclude_iteration_id : 排除的 iteration_id（通常传当前轮次，避免召回自己）

    返回：
        List[Episode] : 按相似度降序排列
    """
    try:
        init_db()
        conn = _get_conn()

        # 查询所有有 raw_input 的 episodes
        rows = conn.execute(
            """
            SELECT * FROM episodes
            WHERE raw_input IS NOT NULL AND raw_input != ''
            ORDER BY timestamp DESC
            LIMIT 200
            """,
        ).fetchall()

        if not rows:
            return []

        # 排除当前轮次
        candidates = [
            r for r in rows
            if exclude_iteration_id is None or int(r["iteration_id"]) != exclude_iteration_id
        ]
        if not candidates:
            return []

        # 构建语料库
        corpus: List[List[str]] = []
        episode_map: Dict[int, sqlite3.Row] = {}
        for r in candidates:
            idx = int(r["iteration_id"])
            episode_map[idx] = r
            tokens = _tokenize(str(r["raw_input"] or ""))
            corpus.append(tokens)

        # 查询文本分词
        query_tokens = _tokenize(query)
        if not query_tokens:
            return []
        query_tf = _compute_tf(query_tokens)
        query_idf = _compute_idf(corpus)

        # 计算查询的 TF-IDF
        query_tfidf: Dict[str, float] = {
            word: query_tf[word] * query_idf.get(word, 1.0)
            for word in query_tf
        }

        # 计算每条记录的相似度
        scored: List[Tuple[float, int]] = []  # (similarity, iteration_id)
        for idx, tokens in zip(episode_map.keys(), corpus):
            if not tokens:
                continue
            doc_tf = _compute_tf(tokens)
            doc_tfidf = {word: doc_tf[word] * query_idf.get(word, 1.0) for word in doc_tf}
            sim = _cosine(query_tfidf, doc_tfidf)
            if sim >= min_similarity:
                scored.append((sim, idx))

        scored.sort(key=lambda x: x[0], reverse=True)
        top_ids = [idx for _, idx in scored[:limit]]

        return [_row_to_episode(episode_map[idx]) for idx in top_ids]

    except Exception as e:
        logger.warning(f"[EpisodesDB] retrieve_episodes_by_text failed: {e}")
        return []


# ============================================================================
# 统计 & 维护
# ============================================================================

def get_episode_count() -> int:
    """返回 episodes 表总条数。"""
    try:
        init_db()
        conn = _get_conn()
        row = conn.execute("SELECT COUNT(*) as cnt FROM episodes").fetchone()
        return int(row["cnt"]) if row else 0
    except Exception as e:
        logger.error(f"[EpisodesDB] get_episode_count failed: {e}")
        return 0


def get_recent_summaries(k: int = 5) -> List[str]:
    """
    从 episodes_db 取最近 K 轮对话的 summary 字段。

    返回按时间升序（最早在前，最新在后），
    每条带 [第N轮] 时间前缀，供 prompt 按时间线顺序注入。

    参数：
        k : 返回条数上限

    返回：
        List[str] : 非空 summary 列表（升序，[第N轮] 前缀）
    """
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
        # DB 返回倒序（最新在前），反转得升序
        rows_rev = list(reversed(rows))
        return [
            f"[第{r[0]}轮] {str(r[1]).strip()}"
            for r in rows_rev
            if r[1]
        ]
    except Exception as e:
        logger.error(f"[EpisodesDB] get_recent_summaries failed: {e}")
        return []


def prune_low_importance(min_importance: float = 0.15) -> int:
    """
    清理低重要性 Episode，保留高价值记忆。

    参数：
        min_importance : 低于此值的 Episode 将被删除

    返回：
        int : 删除的条数
    """
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


# ============================================================================
# 内部辅助
# ============================================================================

def _row_to_episode(row: sqlite3.Row) -> Episode:
    """将数据库行转换为 Episode 对象。"""
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


def _parse_timestamp(ts: str) -> float:
    """将 ISO 时间戳字符串解析为 Unix 时间戳。"""
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.timestamp()
    except Exception:
        return 0.0


def _safe_get(d: Dict[str, Any], key: str, default: Any) -> Any:
    """安全取值。"""
    return d.get(key, default)


def _current_utc_time() -> str:
    return datetime.now(timezone.utc).isoformat()


# ============================================================================
# Episode 构造器（供 entity_zero_iteration 调用）
# ============================================================================

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
    从管线输出构建 Episode 对象。

    参数：
        iteration_id           : 当前轮次编号
        raw_input              : 用户输入原文
        semantic_packet_biased : 感性认识 + 偏置后的语义包
        decision               : 裁决输出
        intent_repr            : 意图编码输出
        state_snapshot         : 实体状态快照
        drive_vector           : 驱动力向量
        output_text            : 生成的回复
        idle_seconds           : 本轮空闲时间
        was_override           : 决策是否被覆盖（失败决策标记）
        tags                   : 额外标签

    返回：
        Episode : 完整的 Episode 对象
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


# ============================================================================
# Insights 表 CRUD（v11.0）
# ============================================================================

@dataclass
class Insight:
    """
    高情绪冲击事件的显性认知重组记录。

    对应 insights 表中的一条记录。
    """
    insight_type: str          # 认知类型，如 "关键教训", "经验偏差"
    content: str               # 领悟内容描述
    drive_snapshot: str        # JSON：触发时的驱动力场快照
    source_episode_id: Optional[int] = None
    confidence: float = 0.8
    created_at: float = 0.0
    labels: List[str] = field(default_factory=list)
    id: Optional[int] = None

    def to_row(self) -> Dict[str, Any]:
        """转换为数据库行格式。"""
        def _json(val):
            try:
                return json.dumps(val, ensure_ascii=False, default=str)
            except Exception:
                return "[]"

        return {
            "insight_type": str(self.insight_type),
            "content": str(self.content),
            "drive_snapshot": self.drive_snapshot,
            "source_episode_id": self.source_episode_id,
            "confidence": float(self.confidence),
            "created_at": float(self.created_at),
            "labels": _json(self.labels),
        }


def write_insight(data: Dict[str, Any]) -> Optional[int]:
    """
    写入单条 Insight 到 SQLite（INSERT OR IGNORE 防重复）。

    参数：
        data : dict，含以下字段：
            insight_type, content, drive_snapshot,
            source_episode_id, confidence, labels

    返回：
        新记录 id，或 None（写入失败 / 重复）
    """
    try:
        import time as _time

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
    """
    查询最近的 Insight 列表。

    返回：
        List[Insight] : 按时间倒序
    """
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
    """
    按标签召回相关的 Insights。

    参数：
        labels : 概念标签列表
        limit  : 返回条数上限

    返回：
        List[Insight] : 按相似度降序
    """
    if not labels:
        return []

    try:
        init_db()
        conn = _get_conn()

        # 模糊匹配：任意一个标签匹配即返回
        # SQLite 没有原生 JSON 数组查询，用 LIKE 模拟
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


def _row_to_insight(row: sqlite3.Row) -> Insight:
    """将数据库行转换为 Insight 对象。"""
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


# ============================================================================
# 测试入口
# ============================================================================

if __name__ == "__main__":
    import time

    print("=" * 64)
    print("Episodes DB — 单元测试")
    print("=" * 64)

    # 初始化
    init_db()
    print(f"\n数据库路径: {DB_PATH}")
    print(f"当前记录数: {get_episode_count()}")

    # 测试 1: 写入
    print("\n【测试 1】write_episode")
    ep = Episode(
        iteration_id=1,
        timestamp=_current_utc_time(),
        raw_input="你好呀！",
        semantic_packet_biased={"emotion": 0.3, "intent": "greet", "intensity": 0.5},
        decision={"action_type": "greet", "target": "user", "priority": 0.6},
        intent_repr={"tone": "warm", "goal": "connect"},
        state_snapshot={"energy": 0.8, "fatigue": 0.1},
        drive_vector={"curiosity": 0.3},
        output_text="你好呀！有什么想聊的吗？",
        idle_seconds=0.0,
        importance=0.5,
        tags=["greet", "social"],
    )
    ok1 = write_episode(ep)
    print(f"  {'✓' if ok1 else '✗'} 写入 {'1' if ok1 else '0'} 条")

    # 测试 2: 查询
    print("\n【测试 2】get_recent_episodes")
    recent = get_recent_episodes(limit=5)
    ok2 = len(recent) >= 1
    print(f"  {'✓' if ok2 else '✗'} 查询到 {len(recent)} 条")
    if recent:
        print(f"     最新: iter={recent[0].iteration_id}, input={recent[0].raw_input}")

    # 测试 3: 按 ID 查询
    print("\n【测试 3】get_episode_by_id")
    ep_found = get_episode_by_id(1)
    ok3 = ep_found is not None
    print(f"  {'✓' if ok3 else '✗'} iteration_id=1 {'找到' if ok3 else '未找到'}")

    # 测试 4: 构造器
    print("\n【测试 4】build_episode")
    built = build_episode(
        iteration_id=2,
        raw_input="我今天很开心！",
        semantic_packet_biased={"emotion": 0.8, "intent": "share", "intensity": 0.9},
        decision={"action_type": "share", "target": "user", "priority": 0.7},
        intent_repr={"tone": "warm"},
        state_snapshot={"energy": 0.8},
        drive_vector={"curiosity": 0.4},
        output_text="太棒了！",
        idle_seconds=10.0,
        was_override=False,
        tags=["positive"],
    )
    ok4 = built.importance >= 0.5 and "intent:share" in built.tags and "high_emotion" in built.tags
    print(f"  {'✓' if ok4 else '✗'} importance={built.importance:.3f}, tags={built.tags}")

    # 测试 5: get_episodes_for_induction
    print("\n【测试 5】get_episodes_for_induction")
    for_ind = get_episodes_for_induction(since_iteration=0, limit=10)
    ok5 = isinstance(for_ind, list) and len(for_ind) >= 1
    print(f"  {'✓' if ok5 else '✗'} 返回 {len(for_ind)} 条适配 Snap 格式的 dict")

    # 测试 6: 异步写入（iter=3）
    # iter=2 在测试 4 中只构造未写入，所以当前应有 3 条（iter=1, 2未写, 3已写）
    ep_async = Episode(
        iteration_id=3,
        timestamp=_current_utc_time(),
        raw_input="异步测试",
        semantic_packet_biased={"emotion": 0.1},
        decision={"action_type": "wait"},
        intent_repr={},
        state_snapshot={},
        drive_vector={},
        output_text="",
        idle_seconds=0.0,
    )
    write_episode_async(ep_async)
    time.sleep(0.5)
    count_after = get_episode_count()
    # iter=1 和 iter=3 已写入，iter=2 未写入（测试4只构造）
    ok6 = count_after >= 2  # 至少这 2 条已确认写入
    print(f"  {'✓' if ok6 else '✗'} 异步写入后共 {count_after} 条（iter=1 sync + iter=3 async）")

    # 测试 7: 失败决策 importance 提升
    print("\n【测试 7】失败决策 importance 提升")
    normal = compute_importance(0.5, 0.3, 0.5, False)
    failed = compute_importance(0.5, 0.3, 0.5, True)
    ok7 = failed > normal
    print(f"  {'✓' if ok7 else '✗'} 失败决策 importance={failed:.3f} > 正常={normal:.3f}")

    print("\n" + "=" * 64)
    all_ok = ok1 and ok2 and ok3 and ok4 and ok5 and ok6 and ok7
    print(f"测试结果: {'全部通过 ✓' if all_ok else '部分失败 ✗'}")
    print(f"最终记录数: {get_episode_count()}")
    print("=" * 64)
