"""
Reading Acquisition — 阅读习得模块（v1.0）

核心哲学：
    她不是从外部语料库学统计分布，而是从阅读中筛选
    能准确描述自己状态的词。只有通过锚点验证的词才被接纳。

机制：
    1. 从 explore 动作的返回文本中提取候选短语（2-6 字）
    2. BGE 相似度过滤：只保留和现有锚点语义相近的词
    3. 驱动力场着色：用当前状态计算 propagated delta 向量
    4. 注入升温系统：候选走正常的 冷→温→解锁 流程
    5. 消力反馈决定留下哪些：不是读到就会，是用对了才学会

约束：
    - 每次 explore 最多习得 3 个候选（不过载）
    - 已在锚点表里的词跳过
    - BGE 相似度 < 0.35 的词跳过（语义太远）
    - 纯函数，不写文件
"""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# 中文短语提取正则：2-10 个汉字
# 体感表达常 7-9 字（"紧张的时候手心出汗"），6 字会截断
_CHINESE_PHRASE_RE = re.compile(r"[一-鿿]{2,10}")

# 停词：太通用的词不值得学
_STOP_WORDS = frozenset({
    "什么", "这个", "那个", "可以", "不是", "就是",
    "因为", "所以", "但是", "而且", "或者", "如果",
    "已经", "没有", "他们", "我们", "你们", "自己",
    "一个", "这些", "那些", "的话", "时候", "知道",
    "觉得", "应该", "需要", "开始", "进行", "使用",
    "通过", "其中", "之后", "之前", "关于", "为了",
    "目前", "最近", "今天", "昨天", "明天", "现在",
    "根据", "以及", "还是", "虽然", "然后", "不过",
})

# 断句残片首字：结构助词 / 语气助词 / 趋向补语
# 正则在标点处断开 CJK 序列，导致 "觉\n得身体轻飘飘" → "得身体轻飘飘"
# 这些字几乎不可能是体感短语的合法开头
_BAD_STARTS = frozenset("的地得了着过们把被让向给往")


def _extract_phrases(text: str, max_phrases: int = 100) -> List[str]:
    """从文本中提取候选中文短语，去重。"""
    if not text:
        return []
    phrases = _CHINESE_PHRASE_RE.findall(text)
    seen = set()
    result = []
    for p in phrases:
        if p in seen or p in _STOP_WORDS:
            continue
        if p[0] in _BAD_STARTS:
            continue
        seen.add(p)
        result.append(p)
        if len(result) >= max_phrases:
            break
    return result


def store_reading_paragraph(entity, text: str, tick: int) -> None:
    """
    explore 读取后，将原始段落存入 entity._reading_paragraphs。

    缓冲区策略：
        - 含 warm words 的段落：优先存储（驱逐旧段落）
        - 不含 warm words 的段落：仅在缓冲区有空位时存储
    这能防止"无效"文本驱逐包含有效词汇的旧段落。
    """
    MAX_STORED_PARAGRAPHS = 20

    # 快速热词过滤
    try:
        from .word_warmup import get_warm_words
        warm_words = get_warm_words(entity, min_hits=1, min_best_efficiency=0.0)
        has_warm_word = bool(warm_words) and any(w in text for w in warm_words)
    except Exception:
        has_warm_word = True  # 出错时保守保留

    paragraphs = getattr(entity, "_reading_paragraphs", None)
    if paragraphs is None:
        entity._reading_paragraphs = []
        paragraphs = entity._reading_paragraphs

    if not has_warm_word:
        # 无效段落：仅在有空位时追加
        if len(paragraphs) < MAX_STORED_PARAGRAPHS:
            paragraphs.append({"text": text, "tick": tick})
    else:
        # 有效段落：追加并驱逐最老的
        paragraphs.append({"text": text, "tick": tick})
        if len(paragraphs) > MAX_STORED_PARAGRAPHS:
            paragraphs.pop(0)


def harvest_from_reading(
    text: str,
    entity_state: Any,
    max_candidates: int = 3,
    min_similarity: float = 0.35,
) -> List[Dict[str, Any]]:
    """
    从阅读文本中习得候选词汇。

    参数：
        text           : explore 动作返回的文本
        entity_state   : 当前实体状态（用于驱动力着色）
        max_candidates : 最多返回的候选数
        min_similarity : BGE 最低相似度阈值

    返回：
        List[dict]，每个元素：
        {
            "word": str,           # 候选词
            "delta": dict,         # propagated delta 向量
            "similarity": float,   # 与最近锚点的相似度
            "source_anchor": str,  # 最近的锚点词
        }
    """
    from .somatic_concept_map import (
        SOMATIC_ANCHORS,
        get_somatic_delta,
        get_state_match_score,
    )

    # Step 1: 提取候选短语
    phrases = _extract_phrases(text)
    if not phrases:
        return []

    # Step 2: 过滤已知锚点
    existing = set(SOMATIC_ANCHORS.keys())
    phrases = [p for p in phrases if p not in existing]
    if not phrases:
        return []

    # Step 3: 获取每个词的 delta 向量
    # 优先用 BGE 传播；BGE 不可用时回退到汉字重叠匹配
    scored: List[Tuple[str, Dict, float, str]] = []
    _use_bge = True
    try:
        from .bge_analyzer import _get_bge_model
        if _get_bge_model() is None:
            _use_bge = False
    except Exception:
        _use_bge = False

    state_dict = _entity_to_state_dict(entity_state)

    for phrase in phrases:
        delta = None
        source_anchor = ""

        if _use_bge:
            # BGE 路径：语义嵌入传播
            delta = get_somatic_delta(
                phrase,
                top_k=3,
                min_similarity=min_similarity,
                propagation_weight=0.50,
            )
            if delta:
                source_anchor = _find_nearest_anchor(phrase)
        else:
            # 回退路径：汉字重叠匹配
            # 中文的"凉意"包含锚点"凉"——共享字 = 共享语义场
            delta, source_anchor = _char_overlap_delta(phrase, SOMATIC_ANCHORS)

        if not delta:
            continue

        # Step 4: 驱动力场着色 — 当前状态下这个词的匹配度
        match_score = get_state_match_score(phrase, state_dict)

        # 综合评分
        relevance = match_score * 0.7 + 0.3
        scored.append((phrase, delta, relevance, source_anchor))

    if not scored:
        return []

    # Step 5: 按综合评分排序，取 top-K
    scored.sort(key=lambda x: x[2], reverse=True)

    results = []
    for word, delta, relevance, source in scored[:max_candidates]:
        results.append({
            "word": word,
            "delta": delta,
            "similarity": relevance,
            "source_anchor": source,
        })
        logger.info(
            f"[ReadAcq] Candidate: '{word}' "
            f"(source='{source}', relevance={relevance:.3f})"
        )

    # ── 存入阅读历史（供 rest 期间句式提取用）───────────────────────
    try:
        _tick = getattr(entity_state, "tick", 0)
        store_reading_paragraph(entity_state, text, _tick)
    except Exception as _store_err:
        logger.debug(f"[ReadAcq] store_reading_paragraph skipped: {_store_err}")

    return results


def _char_overlap_delta(
    phrase: str, anchors: Dict[str, Dict[str, float]]
) -> Tuple[Optional[Dict[str, float]], str]:
    """
    无 BGE 回退：用汉字重叠找最相关的锚点。

    "凉意" 包含锚点字 "凉" → 用 "凉" 的 delta（衰减 0.5）。
    多字重叠时取 delta 维度最多的那个锚点。

    锚点密度加权：锚点字占比越低，衰减越重。
    "胸口闷"（3字2锚点=0.67）→ 权重 0.33
    "可如果芬格尔不主动跳"（10字1锚点=0.10）→ 权重 0.05 → 近乎过滤
    """
    best_anchor = ""
    best_delta: Optional[Dict[str, float]] = None
    best_dims = 0

    # 锚点密度 = 匹配锚点的唯一字数 / 短语总字数
    _matching = sum(1 for c in set(phrase) if c in anchors)
    _density = _matching / len(phrase)  # 0.0 ~ 1.0

    for char in phrase:
        if char in anchors:
            d = anchors[char]
            if len(d) > best_dims:
                best_dims = len(d)
                best_anchor = char
                # 平方衰减：低密度短语快速淘汰，高密度保留更多
                # density=0.5 → 权重0.125；density=0.3 → 权重0.045；density=0.1 → 权重0.005
                _weight = (_density ** 2) * 0.5
                best_delta = {k: v * _weight for k, v in d.items()}

    return best_delta, best_anchor


def _find_nearest_anchor(word: str) -> str:
    """找到与 word BGE 最近的锚点词名。"""
    from .somatic_concept_map import _ensure_anchor_embeddings, _anchor_embeddings, _anchor_words

    _ensure_anchor_embeddings()
    if not _anchor_embeddings or not _anchor_words:
        return "unknown"

    try:
        from .bge_analyzer import _get_bge_model
        import numpy as np

        model = _get_bge_model()
        if model is None:
            return "unknown"

        word_emb = model.encode([word], normalize_embeddings=True)[0]
        best_sim = -1.0
        best_word = "unknown"
        for anchor_word, anchor_emb in _anchor_embeddings.items():
            sim = float(np.dot(word_emb, anchor_emb))
            if sim > best_sim:
                best_sim = sim
                best_word = anchor_word
        return best_word
    except Exception:
        return "unknown"


def _entity_to_state_dict(entity: Any) -> Dict[str, float]:
    """从 entity 提取状态 dict。"""
    if isinstance(entity, dict):
        return entity
    if hasattr(entity, "to_state_snapshot"):
        return entity.to_state_snapshot()
    # 回退：提取常见字段
    result = {}
    for field in [
        "energy", "loneliness", "fatigue", "stress", "somatic_tone",
        "approach_drive", "avoid_drive", "curiosity", "boredom",
        "unresolved", "anxiety", "sadness", "joy", "fear", "anger",
        "excitement", "serenity", "info_gap",
    ]:
        val = getattr(entity, field, None)
        if val is not None:
            result[field] = float(val)
    return result


def inject_reading_candidates(
    entity: Any,
    candidates: List[Dict[str, Any]],
) -> int:
    """
    将阅读习得的候选词注入升温系统。

    通过记录到 entity 的消力追踪器中，让候选走正常的
    冷→温→解锁流程。不是直接解锁——她要用对了才算学会。

    返回实际注入的候选数。
    """
    if not candidates:
        return 0

    # 获取消力追踪器
    quenching = getattr(entity, "_quenching", None)
    if quenching is None:
        return 0

    injected = 0
    state_dict = _entity_to_state_dict(entity)

    for c in candidates:
        word = c["word"]
        # 用最低效率记录一次——让系统知道这个词存在
        # 后续的消力验证决定它是否被保留
        try:
            quenching.record(
                drive_state=state_dict,
                expression=word,
                delta_unresolved_before=0.0,
                delta_unresolved_after=0.0,
                tick=getattr(entity, "tick", 0),
                template_idx=-1,
            )
            injected += 1
            logger.debug(f"[ReadAcq] Injected '{word}' into warmup pipeline")
        except Exception as e:
            logger.debug(f"[ReadAcq] Inject failed for '{word}': {e}")

    if injected > 0:
        logger.info(f"[ReadAcq] {injected} candidates injected from reading")

    return injected
