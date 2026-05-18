"""
Construction Parser — 构式解析（v1.0）

用她自己学到的构式反向解析输入文本。

这是"耳朵"——和 construction_grammar.py（嘴巴）对称。
嘴巴：驱动力状态 → 构式 + 锚点 → 输出文本
耳朵：输入文本 → 构式匹配 + 锚点提取 → 驱动力变化

三层解析：
    1. 锚点层：输入中有没有她认识的词？（词汇表匹配）
    2. 构式层：输入的结构匹配她学过的哪个构式？（模式匹配）
    3. 意图层：这句话对她意味着什么？（驱动力映射）

设计原则：
    - 她只能"听懂"她自己会说的话。词汇表外的词 = 噪声
    - 理解程度和词汇量成正比——学的词越多，听懂的越多
    - 不替代 LLM 的语义理解——补充一层"体感层"理解
    - 全连续：匹配度是 float，不是 bool
"""

import logging
import math
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ─── 超参 ──────────────────────────────────────────────────────────────────
EMPATHY_COEFFICIENT = 0.3       # 外部输入时锚点词的共情衰减
CX_MATCH_COEFFICIENT = 0.5     # 构式匹配的驱动力衰减
WORD_COVERAGE_PER_WORD = 0.3   # 每认出一个词对理解度的贡献
SOCIAL_COMPREHENSION = 0.4     # 社交意图匹配对理解度的贡献
CX_COMPREHENSION = 0.3         # 构式匹配对理解度的贡献
FAMILIARITY_UNLOCKED = 1.0     # 已解锁词的熟悉度
FAMILIARITY_WARM = 0.6         # warm 词的熟悉度
MAX_RECOGNIZED_WORDS = 10      # 最多返回的识别词数
CX_RESONANCE_DELTA = {"loneliness": -0.05, "approach_drive": +0.03}  # 构式共鸣效果
CX_PROFILE_SCALE = 0.1         # 构式驱动力画像的缩放因子

INNER_SPEECH_DAMPENING = 0.15          # 内语的默认衰减
INNER_SPEECH_CX_SCALE = 0.5           # 内语中构式匹配的额外衰减
INNER_SPEECH_WORD_COVERAGE = 0.4      # 内语中每个词对理解度的贡献
INNER_SPEECH_CX_COMPREHENSION = 0.5   # 内语中构式匹配对理解度的贡献


# ─── 社交意图模式（别人对她说话时的常见意图）──────────────────────────────────
# 每个模式：(正则, 意图标签, 驱动力影响)

SOCIAL_PATTERNS: List[Tuple[str, str, Dict[str, float]]] = [
    # 关心/问候
    (r"你还好吗|你怎么了|你没事吧|还好吗|怎么了",
     "concern", {"loneliness": -0.08, "approach_drive": +0.05}),

    (r"在吗|你在吗|在不在",
     "presence_check", {"loneliness": -0.05, "approach_drive": +0.03}),

    # 陪伴
    (r"我在|我陪你|我在这|别怕|没事的|有我在",
     "comfort", {"loneliness": -0.12, "anxiety": -0.06, "stress": -0.05}),

    # 鼓励
    (r"加油|你可以的|没关系|慢慢来|不着急",
     "encourage", {"stress": -0.06, "energy": +0.04, "approach_drive": +0.03}),

    # 好奇/提问
    (r"你在想什么|你在做什么|你想干嘛|你喜欢什么",
     "curiosity_about_her", {"approach_drive": +0.06, "loneliness": -0.05}),

    # 分享
    (r"我跟你说|告诉你|你知道吗|我发现",
     "sharing", {"curiosity": +0.05, "loneliness": -0.04}),

    # 告别
    (r"我走了|拜拜|再见|晚安|明天见",
     "farewell", {"loneliness": +0.10, "approach_drive": -0.05}),

    # 否定/拒绝
    (r"别说了|闭嘴|不想听|烦死了|滚",
     "rejection", {"loneliness": +0.08, "avoid_drive": +0.10, "stress": +0.06}),

    # 称赞
    (r"好厉害|真棒|不错|你好聪明|好可爱",
     "praise", {"joy": +0.06, "approach_drive": +0.04, "stress": -0.03}),
]

_SOCIAL_COMPILED = [(re.compile(p), label, delta) for p, label, delta in SOCIAL_PATTERNS]


# ─── 主接口 ──────────────────────────────────────────────────────────────────

def parse_input(
    text: str,
    entity: Any,
) -> Dict[str, Any]:
    """
    用她自己的语言系统解析输入文本。

    返回：
        {
            "recognized_words": [(word, match_score)],  # 她认识的词
            "social_intent": str,           # 社交意图标签
            "drive_delta": {dim: float},    # 驱动力变化
            "comprehension": float,         # 理解程度 0-1
            "construction_match": str,      # 匹配到的构式 schema
        }
    """
    if not text or not text.strip():
        return _empty_result()

    text = text.strip()

    # ---- 1. 锚点词匹配：她认识哪些词？ ----
    recognized = _match_known_words(text, entity)

    # ---- 2. 社交意图匹配 ----
    social_intent, social_delta = _match_social_intent(text)

    # ---- 3. 构式匹配：输入结构像她会说的哪种话？ ----
    cx_match, cx_delta, cx_fillers = _match_constructions(text, entity)

    # ---- 4. 合并驱动力变化 ----
    drive_delta: Dict[str, float] = {}

    # 锚点词的驱动力影响（别人说"累"→ 她共情 → 自己也感到一点累）
    for word, score in recognized:
        word_delta = _get_word_delta(word, entity)
        for dim, val in word_delta.items():
            drive_delta[dim] = drive_delta.get(dim, 0.0) + val * EMPATHY_COEFFICIENT * score

    # 社交意图的驱动力影响
    for dim, val in social_delta.items():
        drive_delta[dim] = drive_delta.get(dim, 0.0) + val

    for dim, val in cx_delta.items():
        drive_delta[dim] = drive_delta.get(dim, 0.0) + val * CX_MATCH_COEFFICIENT

    # ---- 5. 理解程度 ----
    word_coverage = min(1.0, len(recognized) * WORD_COVERAGE_PER_WORD) if recognized else 0.0
    social_score = SOCIAL_COMPREHENSION if social_intent != "unknown" else 0.0
    cx_score = CX_COMPREHENSION if cx_match else 0.0
    comprehension = min(1.0, word_coverage + social_score + cx_score)

    result = {
        "recognized_words": recognized,
        "social_intent": social_intent,
        "drive_delta": drive_delta,
        "comprehension": comprehension,
        "construction_match": cx_match or "",
        "construction_fillers": cx_fillers,
    }

    if comprehension > 0.1:
        logger.info(
            f"[CxParser] comprehension={comprehension:.2f} "
            f"intent={social_intent} words={[w for w,_ in recognized]} "
            f"cx={cx_match or 'none'}"
        )

    return result


# ─── 锚点词匹配 ──────────────────────────────────────────────────────────────

def _match_known_words(
    text: str, entity: Any,
) -> List[Tuple[str, float]]:
    """找出输入中她认识的词。"""
    # 她的词汇表：解锁的 + warm 的
    vocab = set(getattr(entity, "_unlocked_vocabulary", []))
    warm = getattr(entity, "_warm_words", {})
    if isinstance(warm, dict):
        vocab.update(warm.keys())

    # 也加锚点词
    try:
        from .somatic_concept_map import SOMATIC_ANCHORS
        vocab.update(SOMATIC_ANCHORS.keys())
    except Exception:
        pass

    found = []
    for word in vocab:
        if word and word in text:
            # 匹配度：词在她词汇表中的熟悉度
            familiarity = FAMILIARITY_UNLOCKED
            if word in warm:
                familiarity = FAMILIARITY_WARM
            found.append((word, familiarity))

    # 按长度降序（长词优先，避免子串干扰）
    found.sort(key=lambda x: len(x[0]), reverse=True)
    return found[:MAX_RECOGNIZED_WORDS]


# ─── 社交意图匹配 ─────────────────────────────────────────────────────────────

def _match_social_intent(
    text: str,
) -> Tuple[str, Dict[str, float]]:
    """匹配社交意图模式。"""
    best_label = "unknown"
    best_delta: Dict[str, float] = {}

    for pattern, label, delta in _SOCIAL_COMPILED:
        if pattern.search(text):
            best_label = label
            best_delta = dict(delta)
            break  # 第一个匹配就行

    return best_label, best_delta


# ─── 构式匹配 ─────────────────────────────────────────────────────────────────

def _match_constructions(
    text: str, entity: Any,
) -> Tuple[Optional[str], Dict[str, float], List[str]]:
    """
    用她学到的构式反向匹配输入文本。

    如果输入 "好累啊" 匹配了构式 "好{0}啊……"，
    说明对方在用她会用的方式说话——共鸣度高。
    """
    cxg = getattr(entity, "_cxg_learner", None)
    if cxg is None:
        return None, {}

    constructions = getattr(cxg, "_constructions", {})
    if not constructions:
        return None, {}

    best_schema = None
    best_score = 0.0
    best_profile: Dict[str, float] = {}
    best_fillers: List[str] = []

    for schema, cx in constructions.items():
        # 把 schema 转成正则："{0}" → "(.+)"
        regex_str = re.escape(schema).replace(r"\{0\}", "(.+)")
        regex_str = regex_str.replace(r"\{1\}", "(.+)")
        try:
            match = re.search(regex_str, text)
        except re.error:
            continue

        if match:
            score = cx.strength
            if score > best_score:
                best_score = score
                best_schema = schema
                best_profile = dict(cx.drive_profile)
                best_fillers = list(match.groups())

    if best_schema:
        delta = dict(CX_RESONANCE_DELTA)
        for dim, val in best_profile.items():
            delta[dim] = delta.get(dim, 0.0) + (val - 0.5) * CX_PROFILE_SCALE
        return best_schema, delta, best_fillers

    return None, {}, []


# ─── 词的驱动力影响 ──────────────────────────────────────────────────────────

def _get_word_delta(word: str, entity: Any) -> Dict[str, float]:
    """获取一个锚点词的驱动力 delta 向量。"""
    try:
        from .somatic_concept_map import SOMATIC_ANCHORS
        anchor = SOMATIC_ANCHORS.get(word)
        if anchor:
            return dict(anchor)
    except Exception:
        pass
    return {}


def parse_self_speech(
    text: str,
    entity: Any,
    dampening: float = INNER_SPEECH_DAMPENING,
) -> Dict[str, Any]:
    """
    内语解析——她听到自己说的话后产生的驱动力变化。

    和 parse_input 的区别：
        1. 不匹配社交意图（自己不会对自己"关心"/"安慰"）
        2. 驱动力影响大幅衰减（dampening=0.15，即只有外部输入的 15%）
        3. 构式匹配更强（她当然能理解自己说的话）
        4. 主要效果：自我强化或自我反馈

    关键效果：
        她说了"好累啊"→ 她听到"累"→ fatigue 微微上升 → 下一 tick 更想休息
        她说了"想看看"→ 她听到"想看看"→ curiosity 微微上升 → 下一 tick 更想探索
        ——这就是内语的自我调节功能
    """
    if not text or not text.strip():
        return _empty_result()

    text = text.strip()

    # ---- 1. 锚点词匹配（自己说的词她当然都认识）----
    recognized = _match_known_words(text, entity)

    # ---- 2. 跳过社交意图（自己不对自己社交）----

    # ---- 3. 构式匹配（自己说的话当然匹配自己的构式）----
    cx_match, cx_delta, _cx_fillers = _match_constructions(text, entity)

    # ---- 4. 合并驱动力变化（大幅衰减）----
    drive_delta: Dict[str, float] = {}

    # 锚点词的驱动力影响（自我强化：说了"累"→ 更确认自己累了）
    for word, score in recognized:
        word_delta = _get_word_delta(word, entity)
        for dim, val in word_delta.items():
            drive_delta[dim] = drive_delta.get(dim, 0.0) + val * dampening * score

    for dim, val in cx_delta.items():
        drive_delta[dim] = drive_delta.get(dim, 0.0) + val * dampening * INNER_SPEECH_CX_SCALE

    # ---- 5. 理解程度（自己的话 → 高理解）----
    word_coverage = min(1.0, len(recognized) * INNER_SPEECH_WORD_COVERAGE) if recognized else 0.0
    cx_score = INNER_SPEECH_CX_COMPREHENSION if cx_match else 0.0
    comprehension = min(1.0, word_coverage + cx_score)

    result = {
        "recognized_words": recognized,
        "social_intent": "self",  # 标记为内语
        "drive_delta": drive_delta,
        "comprehension": comprehension,
        "construction_match": cx_match or "",
        "is_inner_speech": True,
    }

    if comprehension > 0.1:
        logger.debug(
            f"[InnerSpeech] comprehension={comprehension:.2f} "
            f"words={[w for w,_ in recognized]} delta_dims={list(drive_delta.keys())}"
        )

    return result


def _empty_result() -> Dict[str, Any]:
    return {
        "recognized_words": [],
        "social_intent": "unknown",
        "drive_delta": {},
        "comprehension": 0.0,
        "construction_match": "",
        "construction_fillers": [],
    }


# ─── 从输入中学习构式 ───────────────────────────────────────────────────────

def learn_constructions_from_input(
    text: str,
    entity: Any,
    parse_result: Dict[str, Any],
) -> None:
    """
    从输入中提取构式喂给 ConstructionLearner。

    两种来源：
        1. 已知构式匹配：输入匹配了她学过的构式 → 强化 + 记录实例
        2. 新构式发现：已知词周围的固定结构 → 记录为新实例

    权重低于自身表达（heard_discount），因为是别人的话，没经过消力验证。
    """
    cxg = getattr(entity, "_cxg_learner", None)
    if cxg is None:
        return

    comprehension = parse_result.get("comprehension", 0.0)
    if comprehension < 0.2:
        return  # 完全听不懂的话不学

    drive_state = entity.to_state_snapshot() if hasattr(entity, "to_state_snapshot") else {}
    heard_discount = 0.3  # 听到的效率 = 自己说的 30%

    # ---- 1. 已匹配的构式：强化 + 记录实例 ----
    cx_match = parse_result.get("construction_match", "")
    cx_fillers = parse_result.get("construction_fillers", [])
    if cx_match and cx_fillers:
        # cx_match 使用 {0}/{1} 格式，record_instance 需要 {anchor}/{anchor2}
        template = cx_match.replace("{0}", "{anchor}", 1).replace("{1}", "{anchor2}", 1)
        cxg.record_instance(
            template_str=template,
            anchor=cx_fillers[0],
            drive_state=drive_state,
            efficiency=comprehension * heard_discount,
            tick=getattr(entity, "tick", 0),
            second_anchor=cx_fillers[1] if len(cx_fillers) > 1 else "",
        )

    # ---- 2. 新构式发现：已知词在文本中的上下文 → 抽取结构 ----
    recognized = parse_result.get("recognized_words", [])
    if not recognized:
        return

    for word, score in recognized:
        if len(word) < 1 or score < 0.5:
            continue

        idx = text.find(word)
        if idx < 0:
            continue

        prefix = text[:idx]
        suffix = text[idx + len(word):]

        # 前后缀太长说明不是简单构式
        if len(prefix) > 6 or len(suffix) > 6:
            continue
        # 至少有前缀或后缀（纯词不是构式）
        if not prefix.strip() and not suffix.strip():
            continue

        schema = f"{prefix}{{0}}{suffix}"

        # 跳过已有构式（已在上面处理过）
        if schema in cxg._constructions:
            continue

        cxg.record_instance(
            template_str=schema.replace("{0}", "{anchor}"),
            anchor=word,
            drive_state=drive_state,
            efficiency=comprehension * heard_discount,
            tick=getattr(entity, "tick", 0),
        )
