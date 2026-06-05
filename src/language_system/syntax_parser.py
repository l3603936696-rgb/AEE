"""
SyntaxParser — 轻量句法分析（v1.0）

用 jieba 词性标注提取句子的主谓宾结构：
- 施事（subject）：谁在做这件事
- 谓语（predicate）：发生了什么
- 受事（object）：对谁/什么发生的
- 否定（negated）：是否被否定
- 疑问（question）：是否是问句

受事方向：speaker（说话者=我）/ xia（她=你）/ external（外部事物）
施事方向：同上

设计原则：
- jieba 纯 Python，无模型下载，本地运行，零延迟
- 用词性启发式规则，不做完整依存句法
- 失败时静默返回空结构，不影响主流程
"""

import logging
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)

# 词性标签集合
_NOUN_FLAGS    = {"n", "nr", "ns", "nt", "nz", "vn"}  # 名词类
_VERB_FLAGS    = {"v", "vd", "vg"}                      # 动词类
_PRONOUN_FLAGS = {"r"}                                  # 代词

_SPEAKER_WORDS = {"我", "俺", "咱", "我们", "咱们"}
_XIA_WORDS     = {"你", "您", "你们"}
_NEG_WORDS     = {"不", "没", "别", "未", "莫", "勿", "没有"}
_QUESTION_WORDS = {"吗", "嘛", "呢", "吧", "？", "?", "什么", "怎么", "为什么", "哪", "谁", "几", "多少"}

_jieba_ok = False


def _ensure_jieba() -> bool:
    global _jieba_ok
    return _jieba_ok or _try_load_jieba()


def _try_load_jieba() -> bool:
    global _jieba_ok
    try:
        import jieba.posseg  # noqa: F401
        _jieba_ok = True
        logger.info("[SyntaxParser] jieba loaded")
    except ImportError:
        logger.debug("[SyntaxParser] jieba not available, syntax parsing disabled")
        _jieba_ok = False
    return _jieba_ok


def _direction(word: str) -> str:
    if word in _SPEAKER_WORDS:
        return "speaker"
    if word in _XIA_WORDS:
        return "xia"
    return "external"


def _pos_tag(text: str) -> List[Tuple[str, str]]:
    import jieba.posseg as pseg
    return [(w.word, w.flag) for w in pseg.lcut(text)]


def parse_svo(text: str) -> Dict:
    """
    对单句做轻量 SVO 提取。

    返回：
        subject      : 施事词文本
        predicate    : 谓语词文本
        object       : 受事词文本
        negated      : 是否否定
        question     : 是否疑问
        agent_dir    : 施事方向 speaker / xia / external
        patient_dir  : 受事方向 speaker / xia / external
    """
    result = {
        "subject": "", "predicate": "", "object": "",
        "negated": False, "question": False,
        "agent_dir": "external", "patient_dir": "external",
    }

    if not text:
        return result

    # 快速检测（不需要分词）
    result["question"] = any(m in text for m in _QUESTION_WORDS)
    # 多字否定词可安全子串匹配；单字否定词（不/没/别/未/莫/勿）等待分词确认，
    # 避免"撑不住""没关系"等复合词误触发 negated=True
    _QUICK_NEG = frozenset(w for w in _NEG_WORDS if len(w) > 1)
    result["negated"] = any(w in text for w in _QUICK_NEG)

    if not _ensure_jieba():
        # jieba 不可用时退回子串检测（精度低但总好过无检测）
        result["negated"] = any(w in text for w in _NEG_WORDS)
        return result

    try:
        tokens = _pos_tag(text)
        # tokens: [(word, flag), ...]

        found_verb  = False
        found_subj  = False

        # 单字否定前缀集（用于检测「不想/没想/别动」等复合词）
        _NEG_PREFIXES = frozenset(w for w in _NEG_WORDS if len(w) == 1)

        for word, flag in tokens:
            # 独立否定词（不/没/别/未/莫/勿/没有）
            # 或以否定词开头的复合词（不想/不能/没想/没法…）
            # 但排除否定词在中间的词（撑不住/了不起…）
            if word in _NEG_WORDS or any(word.startswith(p) for p in _NEG_PREFIXES):
                result["negated"] = True
                continue

            # 施事：谓语前出现的代词或名词
            if not found_verb and not found_subj:
                if flag in _PRONOUN_FLAGS or flag in _NOUN_FLAGS:
                    result["subject"]   = word
                    result["agent_dir"] = _direction(word)
                    found_subj = True
                    continue

            # 谓语：第一个动词
            if not found_verb and flag in _VERB_FLAGS:
                result["predicate"] = word
                found_verb = True
                continue

            # 受事：谓语后第一个代词或名词
            if found_verb and not result["object"]:
                if flag in _PRONOUN_FLAGS or flag in _NOUN_FLAGS:
                    result["object"]      = word
                    result["patient_dir"] = _direction(word)

    except Exception as e:
        logger.debug(f"[SyntaxParser] parse_svo failed: {e}")

    return result
