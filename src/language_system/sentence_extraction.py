"""
Sentence Extraction from Reading — 句式提取（v1.0）

从阅读历史（entity._reading_paragraphs）中提取含 warm word 的短句，
调用 DeepSeek LLM 抽象为构式模板，记录到 ConstructionGrammar。

原料为可丢弃物——抽象完句式后段落立即丢弃，不进记忆系统。

设计原则：
    - 纯函数，无状态写入（除 entity._reading_paragraphs）
    - LLM 调用在 rest 期间，每 10 tick 最多 1 次，每次最多 2 条
    - 二手差异化：is_heard=True → ConstructionGrammar.reinforce() 自动应用衰减
"""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ─── 超参 ───────────────────────────────────────────────────────────────────
LLM_EXTRACT_INTERVAL = 10      # 每 10 个 rest tick 触发一次
MAX_SENTENCES_PER_EXTRACT = 2  # 每次最多抽象 2 条短句
HEARD_INSTANCE_EFFICIENCY = 0.08  # 二手实例的效率值

# LLM 提示词模板
LLM_PROMPT_TEMPLATE = """你是一个语言学分析助手。用户会给你一些中文句子和已知的词汇。
任务：识别每个句子中包含已知词汇的部分，抽象出可复用的句式模板。

规则：
1. 只抽象包含"已知词汇"的句子片段
2. 用[类别]标注可替换的槽位
3. 类别只用：感受、动作、对象、原因、程度、时间
4. 保持原句的语气和情感色彩
5. 如果句子中不包含已知词汇，输出：跳过

输入格式：
句子：「xxx」
已知词汇：[a, b, c]

输出格式（最多2条）：
模板1：「[感受]了，不想[动作]」
槽位1：感受=身体/情感状态词，动作=行为词
模板2：...
"""


# ─── 核心函数 ────────────────────────────────────────────────────────────────

def _extract_sentence_patterns(entity: Any, action_type: str = "rest") -> int:
    """
    从阅读历史中提取含 warm word 的短句，LLM 抽象后记录到 ConstructionGrammar。

    参数：
        entity       : EntityState 实例
        action_type  : 当前行为类型，从 emergent_behavior_dict 传入

    返回：注入 ConstructionGrammar 的 schema 实例数量（0 表示未触发）
    """
    if action_type not in ("rest", "comfort"):
        return 0

    current_tick = getattr(entity, "tick", 0)
    if current_tick % LLM_EXTRACT_INTERVAL != 0:
        return 0

    paragraphs = getattr(entity, "_reading_paragraphs", None)
    if not paragraphs:
        return 0

    warm_words = _get_warm_words(entity)
    if not warm_words:
        return 0

    # 找含 warm word 的短句
    candidates = _find_sentences_with_warm_words(paragraphs, warm_words)
    if not candidates:
        return 0

    # 发 LLM 抽象
    schemas = _llm_abstract_schemas(candidates, warm_words)
    if not schemas:
        return 0

    # 记录到 ConstructionGrammar（is_heard=True → 二手差异化生效）
    cxg = getattr(entity, "_cxg_learner", None)
    if cxg is None:
        return 0

    drive_state = _entity_to_drive_state(entity)
    injected = 0
    for schema, anchor_word in schemas:
        cxg.record_instance(
            template_str=schema,
            anchor=anchor_word,
            drive_state=drive_state,
            efficiency=HEARD_INSTANCE_EFFICIENCY,
            tick=current_tick,
            is_heard=True,
        )
        injected += 1

    if injected > 0:
        _sch_strs = [s for s, _ in schemas]
        logger.info(f"[SentenceExtract] {injected} schemas extracted: {_sch_strs}")
        print(f"[SentenceExtract] {injected} schemas extracted: {_sch_strs}", flush=True)

    return injected


def _find_sentences_with_warm_words(
    paragraphs: List[Dict[str, Any]],
    warm_words: List[str],
) -> List[Tuple[str, str]]:
    """
    从段落中找含 warm word 的短句。

    返回：(句子文本, 匹配的warm_word) 列表，最多 MAX_SENTENCES_PER_EXTRACT 条。
    """
    sentence_split = re.compile(r'[，。！？\n]')
    results: List[Tuple[str, str]] = []
    warm_set = set(warm_words)

    for para in paragraphs:
        text = para.get("text", "")
        for sentence in sentence_split.split(text):
            sentence = sentence.strip()
            if len(sentence) < 4 or len(sentence) > 30:
                continue
            for word in warm_set:
                if word in sentence:
                    results.append((sentence, word))
                    break
            if len(results) >= MAX_SENTENCES_PER_EXTRACT:
                return results

    return results


def _llm_abstract_schemas(
    sentences: List[Tuple[str, str]],
    warm_words: List[str],
) -> List[Tuple[str, str]]:
    """
    调用 DeepSeek LLM 将短句抽象为 schema 模板。

    接口：create_wrapped_llm() → 带观测的 LLM callable
    签名：(system_prompt, user_prompt, temperature, max_tokens, timeout_ms) → (text, error)
    """
    from ..observability import create_wrapped_llm

    input_lines = "\n".join(f"句子：「{s}」" for s, _ in sentences)
    prompt = LLM_PROMPT_TEMPLATE + f"\n\n{input_lines}\n已知词汇：{warm_words[:10]}"

    try:
        _llm = create_wrapped_llm("sentence_extraction")
        response, err = _llm(
            system_prompt="你是一个语言学分析助手。",
            user_prompt=prompt,
            temperature=0.7,
            max_tokens=300,
            timeout_ms=15000,
        )
        if err or not response:
            logger.debug(f"[SentenceExtract] LLM call failed: {err}")
            return []

        schemas = _parse_llm_response(response, sentences)
        return schemas

    except Exception as e:
        logger.debug(f"[SentenceExtract] LLM call failed: {e}")
        return []


def _parse_llm_response(
    response: str,
    sentences: List[Tuple[str, str]],
) -> List[Tuple[str, str]]:
    """
    从 LLM 响应中解析出 schema 模板列表。

    格式：模板1：「[感受]了，不想[动作]」
    返回：(schema模板字符串, anchor词) 列表
    """
    results: List[Tuple[str, str]] = []
    # 匹配「...」或"[...]"中的内容
    pattern = re.compile(r'[「\[](.+?)[」\]]')
    for m in pattern.finditer(response):
        template = m.group(1).strip()
        # 有效模板必须包含槽位标记且不太长
        if "[" in template and "]" in template and len(template) < 40:
            anchor = _find_anchor_word(template, sentences)
            results.append((template, anchor))
        if len(results) >= MAX_SENTENCES_PER_EXTRACT:
            break
    return results


def _find_anchor_word(
    template: str,
    sentences: List[Tuple[str, str]],
) -> str:
    """在源句子中找模板包含的槽位词，作为 anchor。"""
    slot_pattern = re.compile(r'\[([^\]]+)\]')
    slots = slot_pattern.findall(template)
    for slot in slots:
        for sentence, warm_word in sentences:
            if warm_word in sentence:
                return warm_word
    # fallback：返回第一个 warm word
    if sentences:
        return sentences[0][1]
    return "未知"


# ─── 辅助函数 ────────────────────────────────────────────────────────────────

def _get_warm_words(entity: Any) -> List[str]:
    """从 entity 提取当前 warm words。"""
    try:
        from .word_warmup import get_warm_words
        return get_warm_words(entity, min_hits=1, min_best_efficiency=0.0)
    except Exception:
        return []


def _entity_to_drive_state(entity: Any) -> Dict[str, float]:
    """从 entity 提取驱动力状态字典。"""
    fields = [
        "loneliness", "fatigue", "curiosity", "somatic_tone",
        "approach_drive", "avoid_drive", "info_gap", "unresolved",
        "boredom", "stress", "energy",
    ]
    result: Dict[str, float] = {}
    for f in fields:
        val = getattr(entity, f, None)
        if val is not None:
            result[f] = float(val)
    return result
