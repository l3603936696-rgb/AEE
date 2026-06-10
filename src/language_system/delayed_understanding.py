"""
Delayed Understanding — 延迟生效层（反刍机制，v1.0）

职责：
    实现纲领第九节"延迟生效层"。

    某些输入被理解了但没有立即嵌入，进入休眠状态。
    等待未来某个触发点——一个相关的新输入、一个状态变化——
    才被激活，完成迟到的理解。

    反刍：消化不在摄入的瞬间完成。

设计原则：
    - 不强制等待，而是持续在后台低优先级检查
    - 触发匹配用余弦相似度（输入文本语义）
    - 不修改 entity 状态（queue 存储在 ctx 中，不持久化）
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ============================================================================
# 常量
# ============================================================================

# 进入 pending 的理解置信度阈值（低于此值才进 pending）
UNDERSTANDING_THRESHOLD: float = 0.3
# 每次最多处理的 pending 条目数（避免每次 tick 处理过多）
MAX_PROCESS_PER_TICK: int = 3
# 最大 pending 条目数（超出时移除最早的）
MAX_PENDING_SIZE: int = 10
# 相似度阈值：新输入与 pending 条目达到此值则激活重新理解
ACTIVATION_SIM_THRESHOLD: float = 0.4
# 每个 pending 条目最多等待激活的 tick 数（超时后丢弃）
MAX_PENDING_TICKS: int = 500


# ============================================================================
# 数据类
# ============================================================================

class PendingUnderstanding:
    """一个未完成的理解条目。"""

    def __init__(
        self,
        input_text: str,
        interpretation_confidence: float,
        winner_interpretation: Optional[str],
        tick_created: int,
        retry_count: int = 0,
    ):
        self.input_text: str = input_text
        self.interpretation_confidence: float = interpretation_confidence
        self.winner_interpretation: Optional[str] = winner_interpretation
        self.tick_created: int = tick_created
        self.retry_count: int = retry_count

    def to_dict(self) -> dict:
        return {
            "input_text": self.input_text,
            "interpretation_confidence": round(self.interpretation_confidence, 4),
            "winner_interpretation": self.winner_interpretation,
            "tick_created": self.tick_created,
            "retry_count": self.retry_count,
        }


# ============================================================================
# 简单相似度（TF-IDF，余弦）
# ============================================================================

def _text_similarity(a: str, b: str) -> float:
    """简单词集合相似度（无需 BGE）。"""
    if not a or not b:
        return 0.0
    words_a = set(a.lower().split())
    words_b = set(b.lower().split())
    if not words_a or not words_b:
        return 0.0
    intersection = len(words_a & words_b)
    union = len(words_a | words_b)
    if union == 0:
        return 0.0
    return intersection / union


# ============================================================================
# 核心函数
# ============================================================================

def check_should_pend(
    interpretation_confidence: float,
    has_interpretation: bool,
) -> bool:
    """
    判断当前理解结果是否应该进入 pending 队列。

    进入条件：
        - 置信度低于阈值 AND
        - 有候选解释（说明有一定理解但不确定）
    """
    if interpretation_confidence >= UNDERSTANDING_THRESHOLD:
        return False
    if not has_interpretation:
        return False
    return True


def add_to_pending(
    pending_queue: List[PendingUnderstanding],
    new_item: PendingUnderstanding,
    max_size: int = MAX_PENDING_SIZE,
) -> List[PendingUnderstanding]:
    """
    将新条目加入 pending 队列。

    如果队列已满，移除最老的条目。
    如果队列已有相同 input_text 的条目，用置信度更高的替换。
    """
    # 去重：相同 input_text 保留更高置信度
    filtered = [
        p for p in pending_queue
        if p.input_text != new_item.input_text
    ]

    filtered.append(new_item)

    # 超出容量时按 tick_created 移除最老的
    if len(filtered) > max_size:
        filtered.sort(key=lambda p: p.tick_created)
        filtered = filtered[:max_size]

    return filtered


def process_pending_queue(
    pending_queue: List[PendingUnderstanding],
    new_input_text: str,
    current_tick: int,
    max_process: int = MAX_PROCESS_PER_TICK,
    sim_threshold: float = ACTIVATION_SIM_THRESHOLD,
) -> tuple[List[PendingUnderstanding], List[PendingUnderstanding]]:
    """
    检查 pending 队列，对可能激活的条目进行处理。

    激活条件：
        - 新输入与 pending 条目相似度超过阈值
        - 或者 pending 条目已等待超过 MAX_PENDING_TICKS（超时强制尝试）

    返回：
        (remaining_pending, activated_items)

    activated_items 会触发重新理解流程（由调用方处理）。
    """
    if not pending_queue or not new_input_text:
        return pending_queue, []

    remaining: List[PendingUnderstanding] = []
    activated: List[PendingUnderstanding] = []

    for item in pending_queue:
        age = current_tick - item.tick_created

        # 超时强制激活
        if age >= MAX_PENDING_TICKS:
            activated.append(item)
            continue

        # 相似度检查（只检查最新的 max_process 条，避免每次 tick 全量扫描）
        sim = _text_similarity(new_input_text, item.input_text)
        if sim >= sim_threshold:
            item.retry_count += 1
            activated.append(item)
        else:
            remaining.append(item)

    return remaining[:MAX_PENDING_SIZE], activated[:max_process]


def run_delayed_understanding_stage(
    ctx,
    entity,
    interpretation_confidence: float,
    winner_interpretation: Optional[str],
) -> None:
    """
    Pipeline stage: 延迟生效层。

    读取：
        ctx.raw_input

    写入 ctx：
        ctx._pending_understandings : 当前 pending 队列
        ctx._activated_understandings : 本 tick 被激活的 pending 条目
        ctx._understandingly_confidence : 本 tick 的理解置信度

    也写回 entity：
        entity._pending_understandings
    """
    current_tick = entity.tick
    raw_input = str(ctx.raw_input or "")

    # ---- 获取当前理解置信度 ----
    comp_result = getattr(entity, "_last_interpretation_result", None)
    tension_level = getattr(entity, "_last_tension_level", 0.0)

    # 张力悬置状态本身意味着置信度较低
    effective_confidence = interpretation_confidence
    if comp_result is not None:
        try:
            tension_type = getattr(comp_result, "tension_type", "none")
            if tension_type == "suspended":
                effective_confidence = min(
                    effective_confidence,
                    1.0 - tension_level
                )
        except Exception:
            pass

    # ---- 检查是否应该进入 pending ----
    has_interpretation = (
        comp_result is not None
        and getattr(comp_result, "winner", None) is not None
    )
    should_pend = check_should_pend(effective_confidence, has_interpretation)

    # ---- 获取现有 pending 队列 ----
    pending = getattr(entity, "_pending_understandings", [])
    if not isinstance(pending, list):
        pending = []

    # ---- 处理激活（检查新输入是否能激活 pending 条目）----
    activated: List[PendingUnderstanding] = []
    if pending and raw_input:
        pending, activated = process_pending_queue(
            pending,
            raw_input,
            current_tick,
        )

    # ---- 将当前输入加入 pending（如果需要）----
    if should_pend and raw_input:
        new_item = PendingUnderstanding(
            input_text=raw_input,
            interpretation_confidence=effective_confidence,
            winner_interpretation=winner_interpretation,
            tick_created=current_tick,
        )
        pending = add_to_pending(pending, new_item)

    # ---- 写回 ctx 和 entity ----
    ctx._pending_understandings = pending
    ctx._activated_understandings = activated
    ctx._understanding_confidence = effective_confidence

    entity._pending_understandings = pending

    # ---- 激活条目反馈给刻板印象学习器 ----
    if activated:
        try:
            from .stereotype_learner import quick_learn
            for item in activated:
                text_to_learn = (
                    item.winner_interpretation
                    if item.winner_interpretation
                    else item.input_text
                )
                if text_to_learn:
                    quick_learn(entity, "external", text_to_learn, emotion=0.0)
        except Exception:
            pass

    # ---- 首次理解成功（不需 pending）也写入刻板印象树 ----
    if not should_pend and winner_interpretation and raw_input:
        try:
            from .stereotype_learner import quick_learn
            quick_learn(entity, "external", raw_input, emotion=0.0)
        except Exception:
            pass

    # ---- 日志 ----
    if activated and entity.tick % 10 == 0:
        logger.info(
            f"[DelayedUnderstand] t={current_tick} "
            f"activated={len(activated)} pending_size={len(pending)} "
            f"current_conf={effective_confidence:.3f}"
        )
