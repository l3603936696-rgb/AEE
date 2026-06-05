"""
Self-Counsel — 自我开导 / 自欺式保底贷款（v1.0）

哲学（详见 PLAN_self_counsel.md）：
    人会自言自语、自己开导自己度过难关——这不是 bug，是一个自欺式的保底机制，
    像贷款：先支取表层的缓解度过"没人陪/想不通"的当下，但本金（真孤独 / 真困惑）
    一分没还。

    她每次自主表达时（无人回应也算），即时无条件支取一笔自欺贷款：
        - 孤独表层 loneliness_surface：可贷，带利息（条款A 边际递减 + 微量渗透回 core）
          + 信用上限（条款B：core 高则拒贷）。
        - 不可答困惑 unresolved（trigger=action_/无解路径）：可贷，带条款A，
          无渗透（无本金可还）。
        - 可答困惑（trigger=input_）：不贷——保护求知，本金由真实印证还（②epistemic）。

诚实性是结构性的：自欺只压表层，loneliness_core 自己在涨、沉默继续逼她
→ 自欺只拖时间，救不了她。

与 ②expression_feedback 的本质区别：
    ② = 延迟 + 结果 grounding（外界回应/verify 印证），自我开导 = 即时 + 结构
    grounding（只动表层，本金留给真实事件还）。二者互补：被他人理解 vs 自己撑过去。
"""

import logging
import math
from typing import Any, Dict

# 复用 ② 的身体后果写回器（自带钳位）与 clamp——同一条余韵通道。
from .expression_feedback import _apply_somatic_consequence, _queue_feeling, _clamp

logger = logging.getLogger(__name__)

# 复用 thinking_system 的规则号访问器 + 可答性权重判据（§4 闸门）。
# 失败回退到等价内联实现，保持模块自洽。
try:
    from ..thinking_system.thinking_system import (
        _rid as _rule_id,
        _answerability_weight,
        _ANSWERABILITY_BY_TRIGGER,
    )
    # action 触发权重 = 可答性下底；input 触发 = 1.0。span 用于把 [floor,1] 归一到 [0,1]。
    _ANSWER_FLOOR = min(_ANSWERABILITY_BY_TRIGGER.values())
except Exception:  # pragma: no cover - 仅在导入异常时启用
    def _rule_id(rule: Dict[str, Any]) -> str:
        return str(rule.get("id") or rule.get("rule_id") or rule.get("pattern") or str(rule))

    def _answerability_weight(rule: Dict[str, Any]) -> float:
        return 0.8

    _ANSWER_FLOOR = 0.6


# ── 贷款基础额（满额时单笔支取量，§7 提议值）────────────────────────
# 对标 ① 旧 loneliness_surface_release 量级（0.15×quench≈零头），取保守基础额。
_BASE_LONE_LOAN = 0.06   # 孤独表层基础支取额
_BASE_CONF_LOAN = 0.03   # 不可答困惑基础支取额（更小，谨慎；逐条 pending 累加）

# ── 条款 A — 利息（边际递减 + 微量渗透）────────────────────────────
_SEEP_RATE = 0.10        # 微量渗透：孤独支取额 × 此 → loneliness_core 增量（长期成本）
_HEAT_GAIN = 1.0         # 每次支取后的热度增量（驱动边际递减）
_HEAT_TAU = 8.0          # 热度衰减时间常数（拍），对标 expression_feedback._TAU_INTENT

# ── 条款 B — 信用上限（core 高则拒贷）──────────────────────────────
_CEILING = 0.70          # loneliness_core 达此 → 孤独贷款额趋零（逼她去找真实连接）

# ── 身体后果（自我开导是自欺，体感安慰小于"被理解"的 0.10）──────────
_SC_SOMA_COMFORT = 0.05  # ×总支取额 → somatic_tone +=（吐字+自我安抚的一丝舒服）
_SC_PARTICLE = 0.4       # ×支取额 → 自我宽慰/释怀粒子强度

_LONE_LABEL = "自我宽慰"   # 孤独表层贷款的余韵粒子维度
_CONF_LABEL = "释怀"       # 不可答困惑贷款的余韵粒子维度（接纳"没法知道且没关系"）


# ============================================================================
# 条款 A — 近期支取热度（边际递减的状态）
# ============================================================================

def _heat_now(entity: Any, tick: int) -> float:
    """读当前热度，按距上次支取的拍数指数衰减。

    自我安抚越频繁 → 热度越高 → 单次额度越小（"越哄越不管用"）。
    """
    heat = float(getattr(entity, "_self_counsel_heat", 0.0))
    last = int(getattr(entity, "_self_counsel_heat_tick", int(tick)))
    elapsed = max(0.0, float(int(tick) - last))
    return heat * math.exp(-elapsed / _HEAT_TAU)


def _heat_bump(entity: Any, tick: int, heat_decayed: float) -> None:
    """本次支取后升温（在衰减后的热度上叠加增量），记录本拍。"""
    entity._self_counsel_heat = heat_decayed + _HEAT_GAIN
    entity._self_counsel_heat_tick = int(tick)


# ============================================================================
# 贷款额度系数（连续，无 if 门控）
# ============================================================================

def _loan_factor_a(heat: float) -> float:
    """利息·边际递减：热度越高单次额度越小。连续 1/(1+heat)。"""
    return 1.0 / (1.0 + max(0.0, heat))


def _loan_factor_b(entity: Any) -> float:
    """信用上限：loneliness_core 越高额度越小，达 _CEILING 趋零。连续 clamp。"""
    core = float(getattr(entity, "loneliness_core", 0.0))
    return _clamp(1.0 - core / _CEILING)


def _unanswerable_weight(rule: Dict[str, Any]) -> float:
    """不可答程度 ∈ [0,1]，从规则可答性连续归一（§4 闸门，无 if 分发）。

    input_ 触发（可答，权重 1.0）→ 0：不贷（求知本金由真实印证还）。
    action_ 触发（不可答，权重 _ANSWER_FLOOR）→ 1：满贷（释怀，健康出口）。
    """
    a = _answerability_weight(rule)            # [_ANSWER_FLOOR, 1.0]
    span = max(1e-6, 1.0 - _ANSWER_FLOOR)
    return _clamp((1.0 - a) / span)


# ============================================================================
# 主入口 — 即时无条件支取一笔自欺贷款
# ============================================================================

def apply_self_counsel(entity: Any, expression: str, tick: int) -> Dict[str, Any]:
    """她自我表达时即时支取自欺贷款（孤独表层 + 不可答困惑表层）。

    无条件放贷（它是贷款，不需要"测出真有用"——这是与 ②epistemic 的本质区别），
    利息由条款 A/B 就地结算。全程连续 + clamp，无行为门控；可答性查表分发。

    返回支取摘要（供日志/调试）。空表达不支取。
    """
    if not expression:
        return {"drawn": 0.0}

    heat = _heat_now(entity, tick)
    factor_a = _loan_factor_a(heat)
    factor_b = _loan_factor_b(entity)

    # ── 孤独表层贷款：条款 A×B；微量渗透回 core（利息·长期成本，本金慢慢加深）──
    lone_loan = _BASE_LONE_LOAN * factor_a * factor_b
    surf = float(getattr(entity, "loneliness_surface", 0.0))
    entity.loneliness_surface = _clamp(surf - lone_loan)
    core = float(getattr(entity, "loneliness_core", 0.0))
    entity.loneliness_core = _clamp(core + lone_loan * _SEEP_RATE)
    _sync = getattr(entity, "_sync_loneliness", None)
    {True: lambda: _sync(), False: lambda: None}[callable(_sync)]()

    # ── 不可答困惑贷款：扫 _pending_questions，仅对不可答者支取（条款A，无渗透）──
    conf_loan = _draw_confusion_loan(entity, factor_a)

    # ── 身体后果：即时体感安慰（小，因是自欺）+ 自我宽慰/释怀粒子余韵 ──
    drawn = lone_loan + conf_loan
    _apply_somatic_consequence(entity, soma_delta=drawn * _SC_SOMA_COMFORT, relief_delta=0.0)
    _queue_feeling(entity, _LONE_LABEL, lone_loan * _SC_PARTICLE)
    _queue_feeling(entity, _CONF_LABEL, conf_loan * _SC_PARTICLE)

    # ── 条款 A 升温：本次支取后热度增加，下次额度更小 ──
    _heat_bump(entity, tick, heat)

    summary = {
        "lone_loan": round(lone_loan, 4),
        "conf_loan": round(conf_loan, 4),
        "seep": round(lone_loan * _SEEP_RATE, 5),
        "heat": round(heat, 3),
        "factor_a": round(factor_a, 3),
        "factor_b": round(factor_b, 3),
        "soma": round(drawn * _SC_SOMA_COMFORT, 4),
    }
    logger.debug(
        f"[SelfCounsel] 支取自欺贷款: lone={summary['lone_loan']} conf={summary['conf_loan']} "
        f"seep={summary['seep']} heat={summary['heat']} A={summary['factor_a']} "
        f"B={summary['factor_b']} expr='{expression[:20]}' tick={tick}"
    )
    return summary


def _draw_confusion_loan(entity: Any, factor_a: float) -> float:
    """对 _pending_questions 中不可答的疑问支取 unresolved 表层贷款（无渗透）。

    逐条按其 rule_id 在 wm_rules 里查 predicts.trigger 的可答性：
        可答（input_）→ unanswerable_weight=0 → 自动零支取（保护求知）。
        不可答（action_/无解）→ 满权重 → 支取小额（释怀）。
    连续累加，无 if 门控。总支取从 unresolved 扣除并 clamp。
    """
    questions = getattr(entity, "_pending_questions", None) or []
    rules = getattr(entity, "wm_rules", None) or []
    rule_by_id = {_rule_id(r): r for r in rules}

    total = 0.0
    for q in questions:
        rid = str(q.get("rule_id", ""))
        rule = rule_by_id.get(rid, {})
        total += _BASE_CONF_LOAN * factor_a * _unanswerable_weight(rule)

    cur = float(getattr(entity, "unresolved", 0.0))
    entity.unresolved = _clamp(cur - total)
    return total
