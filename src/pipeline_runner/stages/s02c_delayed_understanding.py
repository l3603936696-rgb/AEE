"""
Stage s02c — 延迟理解层（反刍机制）。

职责：在解释竞争之后检查理解置信度，未达标的进入 pending 队列，
      每个 tick 检查 pending 是否有可激活的条目。

前置阶段：s02b_input_drive_map（输入→drive映射）+ interpretation_competition（解释竞争）

输入：ctx.raw_input, ctx._interpretation_result, ctx._tension_level
输出：ctx._pending_understandings, ctx._activated_understandings, ctx._understanding_confidence
"""

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# 语言熟悉度地板：全是生词的输入仍保留的置信度比例（不归零，避免对任何陌生输入
# 都暴跌成"完全没懂"）。偏小提议值，先跑再调，待 Owner 追认。
_FAMILIARITY_FLOOR: float = 0.20


def _familiarity_coverage(text: str, entity) -> float:
    """输入字符落在她已知词汇上的连续覆盖率 ∈ [0,1]（中文按字算，鲁棒）。

    经验共鸣给的置信度只反映"这让我想起什么"，不反映"我读懂了没"——满是生词的
    输入也可能强共鸣 → 虚高自信。覆盖率给一条独立的"这内容我熟不熟"的连续信号，
    用来把置信度往下拉，让真正陌生的输入掉到悬置阈值下（她才"知道自己没把握"）。

    空输入（如 daemon tick 无 raw_input）返回 1.0 = 不拉低，熟悉度只作用于真实输入。
    """
    chars = [c for c in str(text or "") if c.strip()]
    n = len(chars)
    # 空输入：覆盖率记满（不参与下拉）。max + 符号避免分支门控。
    known = set()
    for w in (getattr(entity, "_unlocked_vocabulary", []) or []):
        known.update(str(w))
    for w in (getattr(entity, "_word_exposure_tracker", {}) or {}):
        known.update(str(w))
    hit = sum(1 for c in chars if c in known)
    # n==0 → (0+1)/(0+1)=1.0；n>0 → hit/n。无 if 门控。
    return (hit + (1 - min(1, n))) / max(1, n)


def run_stage(ctx, entity) -> None:
    try:
        from ...language_system.delayed_understanding import (
            run_delayed_understanding_stage as _run_delayed,
            PendingUnderstanding,
        )

        # 获取解释竞争结果
        comp_result = getattr(ctx, "_interpretation_result", None)
        tension_level = getattr(ctx, "_tension_level", 0.0)

        # 计算有效理解置信度
        effective_confidence = 0.5  # 默认值
        winner_interpretation: str | None = None

        if comp_result is not None:
            try:
                tension_type = getattr(comp_result, "tension_type", "none")
                winner = getattr(comp_result, "winner", None)

                if winner is not None:
                    winner_interpretation = getattr(winner, "interpretation", None)

                # 张力悬置 → 置信度降低
                if tension_type == "suspended":
                    effective_confidence = max(0.0, 1.0 - tension_level)
                elif tension_type == "attractor":
                    effective_confidence = 0.7 + tension_level * 0.3
                else:
                    effective_confidence = 0.4
            except Exception:
                pass

        # 语言熟悉度下拉：经验共鸣置信度 × 熟悉度因子。熟悉度=输入落在已知词汇上的
        # 覆盖率，floor 兜底。全熟悉(cov=1)→不变；越生→越往 floor 拉，掉破 0.3 阈值
        # 就进悬置。这给她"这输入我陌生→没把握"的诚实信号（结构性误读需命题骨架，见 B）。
        _cov = _familiarity_coverage(getattr(ctx, "raw_input", ""), entity)
        _familiarity = _FAMILIARITY_FLOOR + (1.0 - _FAMILIARITY_FLOOR) * _cov
        effective_confidence = effective_confidence * _familiarity
        # 也写到 entity，供输出阶段（s06c 锚点路径）读取，让"没懂"显形到她的表达
        entity._understanding_confidence = effective_confidence

        _run_delayed(
            ctx=ctx,
            entity=entity,
            interpretation_confidence=effective_confidence,
            winner_interpretation=winner_interpretation,
        )

        _trace = getattr(ctx, "_trace", lambda *a, **kw: None)
        _trace("delayed_understanding", True, {
            "pending_size": len(getattr(ctx, "_pending_understandings", [])),
            "activated_count": len(getattr(ctx, "_activated_understandings", [])),
            "confidence": round(effective_confidence, 3),
            "familiarity": round(_familiarity, 3),
            "coverage": round(_cov, 3),
        })
    except Exception as e:
        logger.warning(f"[s02c delayed_understanding] failed: {e}")
        ctx._pending_understandings = getattr(entity, "_pending_understandings", [])
        ctx._activated_understandings = []
        ctx._understanding_confidence = 0.5
