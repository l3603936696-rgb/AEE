"""
Vocabulary Acquisition — 词汇习得（v1.0）

XIA 通过"听到"外部输入中的陌生词来学习新词汇。

流程：
    1. 构式解析器处理输入后，本模块检测 somatic_dictionary 中她还没学会的词
    2. 如果她能部分理解这句话（comprehension > 阈值），触发曝光事件
    3. 曝光次数够了 → 问老师（LLM）："这个词像你认识的哪个词？"
    4. 老师用她已知的词回答 → 新词从已知词复制 drive profile
    5. 新词进入 warm 状态 → 沿用现有 warmup 机制 → 最终 unlock

设计原则：
    - 老师只用她已知的词解释，不引入外部定义
    - 词义初始来自已知词的复制，后续被自身体验覆盖
    - 曝光分自然衰减，偶尔听到一次不算数
    - 所有参数从 entity._vocab_acquisition_params 读取
"""

import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def detect_learnable_words(
    text: str,
    entity: Any,
    comprehension: float,
) -> List[str]:
    """
    检测输入中存在于 somatic_dictionary 但她还没学会的词。

    只在 comprehension > 阈值时返回结果（她得能部分理解上下文）。
    """
    params = getattr(entity, "_vocab_acquisition_params", {})
    min_comprehension = params.get("min_comprehension", 0.3)

    if comprehension < min_comprehension:
        return []

    try:
        from .somatic_dictionary import get_all_words
        all_words = get_all_words()
    except Exception:
        return []

    known = set(getattr(entity, "_unlocked_vocabulary", []))
    warm = set(getattr(entity, "_warm_words", {}).keys()) if isinstance(
        getattr(entity, "_warm_words", None), dict) else set()
    known_or_warm = known | warm

    learnable = []
    for word in all_words:
        if word not in known_or_warm and word in text:
            learnable.append(word)

    return learnable


def update_exposure(
    words: List[str],
    entity: Any,
) -> List[str]:
    """
    更新曝光分。返回达到阈值、可以问老师的词列表。
    """
    if not words:
        return []

    params = getattr(entity, "_vocab_acquisition_params", {})
    exposure_per_hit = params.get("exposure_per_hit", 0.2)
    ask_threshold = params.get("ask_threshold", 1.0)

    tracker = getattr(entity, "_word_exposure_tracker", None)
    if tracker is None:
        tracker = {}
        entity._word_exposure_tracker = tracker

    ready_to_ask = []
    for word in words:
        entry = tracker.get(word, {"score": 0.0, "asked": False, "last_tick": 0})
        if entry.get("asked", False):
            continue  # 已经问过老师了
        entry["score"] = entry.get("score", 0.0) + exposure_per_hit
        entry["last_tick"] = getattr(entity, "tick", 0)
        tracker[word] = entry

        if entry["score"] >= ask_threshold:
            ready_to_ask.append(word)

    return ready_to_ask


def decay_exposure(entity: Any) -> None:
    """每 tick 调用：曝光分自然衰减。"""
    params = getattr(entity, "_vocab_acquisition_params", {})
    decay_rate = params.get("exposure_decay", 0.99)

    tracker = getattr(entity, "_word_exposure_tracker", None)
    if tracker is None:
        return

    for word in list(tracker.keys()):
        entry = tracker[word]
        if entry.get("asked", False):
            continue  # 已问过的不衰减
        entry["score"] = entry.get("score", 0.0) * decay_rate
        if entry["score"] < 0.01:
            del tracker[word]  # 清理忘掉的


def build_teacher_prompt(
    word: str,
    entity: Any,
) -> Optional[str]:
    """
    构建问老师的 prompt。

    老师的任务：从她已知的词中找一个最接近的词。
    如果已知词太少（< 5），不问。
    """
    known_words = list(getattr(entity, "_unlocked_vocabulary", []))
    if len(known_words) < 5:
        return None

    # 限制已知词列表长度，避免 prompt 太长
    display_words = known_words[:50]
    word_list_str = "、".join(display_words)

    prompt = (
        f"一个正在学说话的个体，目前认识这些词：\n"
        f"{word_list_str}\n\n"
        f"她在别人说的话里反复听到了一个她不认识的词：「{word}」\n\n"
        f"请从她已经认识的词里，选一个体感最接近的词。\n"
        f"只回答那一个词，不要解释。如果没有接近的，回答「无」。"
    )
    return prompt


def process_teacher_response(
    new_word: str,
    known_word: str,
    entity: Any,
) -> bool:
    """
    处理老师的回答：用已知词的 drive profile 作为新词的初始 profile。
    新词进入 _warm_words。

    返回 True 表示成功习得。
    """
    known_word = known_word.strip()

    if known_word == "无" or not known_word:
        return False

    # 验证老师回答的确实是她认识的词
    known_vocab = set(getattr(entity, "_unlocked_vocabulary", []))
    if known_word not in known_vocab:
        # 老师回了个她不认识的词，忽略
        logger.debug(f"[VocabAcq] teacher returned unknown word: {known_word}")
        return False

    # 从 somatic_dictionary 获取已知词的 profile
    try:
        from .somatic_dictionary import SOMATIC_DICTIONARY
        source_profile = None
        for category, entries in SOMATIC_DICTIONARY.items():
            if known_word in entries:
                source_profile = dict(entries[known_word])
                break

        if source_profile is None:
            # 已知词不在字典里（可能是通过其他途径解锁的），跳过
            return False
    except Exception:
        return False

    # 新词进入 warm_words，drive profile 复制自已知词
    warm = getattr(entity, "_warm_words", None)
    if warm is None:
        warm = {}
        entity._warm_words = warm

    warm[new_word] = {
        "source_word": known_word,
        "profile": source_profile,
        "acquired_tick": getattr(entity, "tick", 0),
    }

    # 标记已问过
    tracker = getattr(entity, "_word_exposure_tracker", {})
    if new_word in tracker:
        tracker[new_word]["asked"] = True

    logger.info(
        f"[VocabAcq] acquired '{new_word}' via teacher "
        f"(≈'{known_word}'), profile={source_profile}"
    )
    return True


async def try_acquire_words(
    text: str,
    entity: Any,
    comprehension: float,
    llm_callable: Any = None,
) -> List[str]:
    """
    完整的词汇习得流程（供管线调用）。

    返回本次新习得的词列表。
    """
    # 1. 检测可学的词
    learnable = detect_learnable_words(text, entity, comprehension)
    if not learnable:
        return []

    # 2. 更新曝光，找出达到阈值的词
    ready = update_exposure(learnable, entity)
    if not ready or llm_callable is None:
        return []

    # 3. 限流：每次最多问一个词
    params = getattr(entity, "_vocab_acquisition_params", {})
    max_per_tick = params.get("max_asks_per_tick", 1)
    ready = ready[:max_per_tick]

    acquired = []
    for word in ready:
        prompt = build_teacher_prompt(word, entity)
        if prompt is None:
            continue

        try:
            # 调用 LLM
            response = llm_callable(prompt)
            if isinstance(response, dict):
                answer = response.get("text", "").strip()
            else:
                answer = str(response).strip()

            # 取第一行第一个词（防止 LLM 啰嗦）
            answer = answer.split("\n")[0].strip().strip("「」\"'")

            if process_teacher_response(word, answer, entity):
                acquired.append(word)
        except Exception as e:
            logger.debug(f"[VocabAcq] LLM call failed for '{word}': {e}")

    return acquired


def try_acquire_words_sync(
    text: str,
    entity: Any,
    comprehension: float,
    llm_callable: Any = None,
) -> List[str]:
    """
    同步版本的词汇习得（供非 async 管线调用）。
    """
    learnable = detect_learnable_words(text, entity, comprehension)
    if not learnable:
        return []

    ready = update_exposure(learnable, entity)
    if not ready or llm_callable is None:
        return []

    params = getattr(entity, "_vocab_acquisition_params", {})
    max_per_tick = params.get("max_asks_per_tick", 1)
    ready = ready[:max_per_tick]

    acquired = []
    for word in ready:
        prompt = build_teacher_prompt(word, entity)
        if prompt is None:
            continue

        try:
            response = llm_callable(prompt)
            if isinstance(response, dict):
                answer = response.get("text", "").strip()
            else:
                answer = str(response).strip()

            answer = answer.split("\n")[0].strip().strip("「」\"'")

            if process_teacher_response(word, answer, entity):
                acquired.append(word)
        except Exception as e:
            logger.debug(f"[VocabAcq] LLM call failed for '{word}': {e}")

    return acquired
