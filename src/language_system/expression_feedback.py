"""
Expression Feedback Loop — 表达反馈闭环（v1.0）

核心哲学：
    现有消力闭环只看内部张力衰减——她说一句话，张力自己衰减了，
    就以为"这句话有用"，哪怕没人理她。这是自欺。

    本模块把 efficiency 的来源换成"外界回应对需求的实际满足"：

        驱动力 → 表达（带意图）→ 外界回应 → 需求是否真被满足 → 强化/弱化

    她说的话得到有效回应 → 对应词/句式 efficiency 真实升高 → 被偏好；
    石沉大海 → efficiency 为低 → 自然淘汰。这是"语言作为工具"的学习。

合法性（和"输入是材料"自洽）：
    回应修改的不是状态总账，而是"她上一拍主动表达时挂账的那股驱动力"。
    因果起点在她内部（action→outcome），不是外界推动（stimulus→response）。
    结构护栏：
        1. 没有挂账 → 不修改任何状态（堵死 stimulus→response）
        2. 修改幅度正比于"输入与她那句话的相关度"

设计见 PLAN_expression_feedback_loop.md。
"""

import logging
import math
from collections import deque
from typing import Any, Deque, Dict, List

logger = logging.getLogger(__name__)

# ── 可入闭环的驱动力 ─────────────────────────────────────────────
# 判据：这股力的缺口能否被"一段文字回应"填上。
# fatigue/energy 需要休息不是话，强接会造假满足，故不入闭环。
_ELIGIBLE_DRIVES = ("loneliness", "info_gap", "unresolved")

# ── 满足→驱动力下降的系数（来源见 PLAN §3）────────────────────────
# 实测单次事件级自然变化 ≈ 0.1（真实用户输入让 loneliness -0.1）。
# 反馈推动取其零头——"轻推不覆盖"，不让回应盖过她自身的动力学。
_K_SATISFY: Dict[str, float] = {
    "loneliness": 0.05,   # 回应=陪伴，明显但不超过真实输入的 0.1
    "info_gap":   0.03,   # 信息满足较慢
    "unresolved": 0.03,   # 推进悬而未决较慢
}

# ── 诚实奖励 → 身体后果（标量即时通道，见 PLAN_honest_reward_somatic_coupling §3/§5）──
# 缺口：consume_response / settle_epistemic_credit 的奖励原本只写 quenching（升温词、打分句式）
# 和轻推 drive，从不碰 somatic_tone/relief_debt → 她被真正理解/印证时"什么都感觉不到"。
# 这两组系数把诚实奖励（幅度已含外界 grounding）翻译成真实体感：被懂了→暖、想通了→踏实/松一口气。
# 标量四组已与 bcyq 锁定（2026-05-30）。
_SOMA_FROM_SATISFY: Dict[str, float] = {   # ×satisfaction → somatic_tone +=（[-1,1] 钳位）
    "loneliness": 0.10,   # 被陪伴回应=暖意，与老 somatic_comfort(0.15) 同量级偏低
    "info_gap":   0.05,   # 信息满足体感弱于陪伴
    "unresolved": 0.06,   # 介于二者
}
_RELIEF_FROM_SATISFY: Dict[str, float] = { # ×satisfaction → relief_debt -=（[0,1] 钳位，降低=松一口气）
    "loneliness": 0.0,
    "info_gap":   0.04,
    "unresolved": 0.08,   # 悬而未决被推进=松一口气主通道
}
_SOMA_FROM_EPISTEMIC = 0.20    # ×reward → somatic_tone +=（reward 量级小，系数大一档才可感知）
_RELIEF_FROM_EPISTEMIC = 0.15  # ×reward → relief_debt -=（"想通了"主要是 relief）

# ── 诚实奖励 → 情绪粒子（持续余韵通道）──
# 标量给即时效价，粒子给"被感动"的余韵：按半衰期着色后续多拍的表达节奏。
# 三常量为本期新增标定（缺旧锚点），bcyq 同意先上提议值再微调。
_PARTICLE_FROM_SATISFY = 0.50    # ×satisfaction → 粒子 intensity
_PARTICLE_FROM_EPISTEMIC = 2.0   # ×reward → 粒子 intensity（reward ~0.013，需放大才成形）
_FEELING_HALF_LIFE = 600.0       # 秒；≈20 拍，余韵跨多拍但不久滞
_FEELING_QUEUE_MAXLEN = 8        # 待注入粒子队列上限，deque 自动驱逐最旧
_FEELING_LABEL: Dict[str, str] = {   # 来源 → 粒子维度标签
    "loneliness": "被理解", "info_gap": "明白了", "unresolved": "推进了",
    "_epistemic": "想通了",
}

# 意图新近度衰减时间常数（tick）。约 8 tick（≈4 分钟 @30s）后权重降到 1/e。
# 她不会无限期等一句话的回音。
_TAU_INTENT = 8.0

# 待回应意图内存队列上限。deque 自动驱逐最旧，不用比较门控。
_INTENT_QUEUE_MAXLEN = 6

# ── 认知信用（洞②）常量（来源见 PLAN_language_as_tool.md §3）─────────
# 认知信用新近度时间常数。与 _TAU_INTENT 同源同量纲。
# §6 标定：_SETTLE_DELAY 拉到 11 后，age=11 处 recency=exp(-11/8)=0.25 会把奖励砍掉 3/4；
# 调到 12 → recency=exp(-11/12)≈0.40，思考回报不至于刚记账就被新近度抹平。
_TAU_EPISTEMIC = 12.0
# 异步世界模型更新一个周期的拍数。给 verify 留出时序窗口。
# §6 日志标定（2026-05-30）：WM 归纳由 tick_engine `tick % 10 == 0` 触发 = 每 10 拍一次。
# 种子 2 远短于此 → 认知信用永远在"能抬升规则 conf 的 WM 周期"之前就到期结算 → gain 恒 0。
# 改 11 = 一整个 WM 周期(10) + 1 拍余量，保证结算时那条规则已有机会被更新过。
_SETTLE_DELAY = 11
# gain→efficiency 系数。gain 本身已 [0,1] 量纲，种子 1.0。
_K_EPISTEMIC = 1.0
# 认知信用挂账队列上限。deque 自动驱逐最旧。
# 必须 >= _SETTLE_DELAY，否则挂账速率高时认知信用会在到期(age=_SETTLE_DELAY)前被挤出 → gain 恒 0。
# §6 标定：delay=11 → 取 16（= 11 + 5 余量），容下一整个结算窗口内累积的挂账。种子 8 是配 delay=2 的。
_EPISTEMIC_QUEUE_MAXLEN = 16

# ── 抗回声 novelty（洞④）常量 ───────────────────────────────────────
# 参与 novelty 比较的"最近对话历史"句数（双方混合）。N 越大重复检测越严。
# 取 3：覆盖最近几轮一来一回，又不至于误杀隔几轮的正常重提。
_NOVELTY_HISTORY = 3


# 复用 thinking_system 的规则访问器（置信度 / 规则号）。
# 失败回退到等价内联实现，保持模块自洽。
try:
    from ..thinking_system.thinking_system import _conf as _rule_conf, _rid as _rule_id
except Exception:  # pragma: no cover - 仅在导入异常时启用
    def _rule_conf(rule: Dict[str, Any]) -> float:
        return float(rule.get("confidence") or rule.get("confidence_score")
                     or rule.get("weight") or 0.5)

    def _rule_id(rule: Dict[str, Any]) -> str:
        return str(rule.get("id") or rule.get("rule_id")
                   or rule.get("pattern") or str(rule))


# ============================================================================
# 待回应意图队列（内存，不持久化）
# ============================================================================

def _get_queue(entity: Any) -> Deque[Dict[str, Any]]:
    """取/建 entity 上的待回应意图队列。deque(maxlen) 自动驱逐最旧。"""
    q = getattr(entity, "_pending_intents", None)
    is_deque = isinstance(q, deque)
    # 不存在或类型不对时重建（dict 分发，避免 if 门控）
    factory = {
        True:  lambda: q,
        False: lambda: deque(maxlen=_INTENT_QUEUE_MAXLEN),
    }[is_deque]
    new_q = factory()
    entity._pending_intents = new_q
    return new_q


# ============================================================================
# 模块 A — 表达意图挂账
# ============================================================================

def tag_intent(entity: Any, expression: str, tick: int) -> None:
    """
    她每次自主表达后，记录这次表达"为了哪股驱动力"。

    从三个可入闭环维度里取 argmax 作为意图驱动力，强度取该维度当前值。
    强度趋零时进队也无害——后续满足量正比于强度，强度≈0 自然无效。

    挂账只写内存队列，不碰任何持久化字段。
    """
    if not expression:
        return

    values = {d: float(getattr(entity, d, 0.0)) for d in _ELIGIBLE_DRIVES}
    drive, strength = max(values.items(), key=lambda kv: kv[1])

    # 洞①：记下这次表达选中的句式号，让信用落到具体句式而非词串。
    template_idx = int(getattr(entity, "_last_template_idx", -1))

    q = _get_queue(entity)
    q.append({
        "drive": drive,
        "strength": strength,
        "expression": expression,
        "tick": int(tick),
        "template_idx": template_idx,
    })
    logger.debug(
        f"[ExprFeedback] 挂账意图: drive={drive} strength={strength:.3f} "
        f"expr='{expression[:20]}' tpl={template_idx} tick={tick}"
    )

    # 洞②：若她带着某个思考层疑问说了这句话，挂账认知信用（延迟结算）。
    _tag_epistemic_credit(entity, expression, template_idx, tick)

    # 洞④：把她自己这句表达纳入对话历史，使"对方原样复读她"的回应 novelty→0。
    _get_dialogue_history(entity).append(expression)


# ============================================================================
# 模块 A' — 认知信用挂账（洞②，延迟结算前半段）
# ============================================================================

def _get_epistemic_queue(entity: Any) -> Deque[Dict[str, Any]]:
    """取/建 entity 上的认知信用挂账队列。deque(maxlen) 自动驱逐最旧。"""
    q = getattr(entity, "_pending_epistemic_credit", None)
    is_deque = isinstance(q, deque)
    factory = {
        True:  lambda: q,
        False: lambda: deque(maxlen=_EPISTEMIC_QUEUE_MAXLEN),
    }[is_deque]
    new_q = factory()
    entity._pending_epistemic_credit = new_q
    return new_q


def _tag_epistemic_credit(entity: Any, expression: str, template_idx: int, tick: int) -> None:
    """
    她带着具体疑问表达时，快照"这个疑问当时的置信度"。

    取 _pending_questions 里优先级最高的一条（带 predicts 规则的提问），
    记下 rule_id + 提问时置信度。后续某拍（异步 WM 跑过 verify 后）再读
    该规则的当前置信度，正向印证（confidence 升）才给认知奖励。

    挂账只写内存队列，不碰持久化字段。无疑问 → 不挂账。
    """
    questions = getattr(entity, "_pending_questions", None) or []
    if not questions:
        return

    top_q = max(questions, key=lambda x: float(x.get("priority", 0.0)))
    q = _get_epistemic_queue(entity)
    q.append({
        "q_rule_id": str(top_q.get("rule_id", "")),
        "q_conf_at_ask": float(top_q.get("confidence_at_ask", 0.0)),
        "template_idx": int(template_idx),
        "expression": expression,
        "tick": int(tick),
    })
    logger.debug(
        f"[ExprFeedback] 挂账认知信用: rule={top_q.get('rule_id','')} "
        f"conf@ask={float(top_q.get('confidence_at_ask',0.0)):.3f} "
        f"tpl={template_idx} tick={tick}"
    )


# ============================================================================
# 模块 B + C — 回应检测 + 满足回写
# ============================================================================

def consume_response(entity: Any, input_text: str, tick: int) -> Dict[str, Any]:
    """
    输入到达时，结算她之前挂账的每条表达意图。

    对每条意图：
        relevance    = 相关度(input, 她那句话)           — BGE，回退汉字重叠
        recency      = exp(-(tick - 意图tick) / TAU)      — 新近度衰减
        satisfaction = 意图强度 × relevance × recency

    然后：
        1. 驱动力满足：只对 intent.drive 这一维做下降（其它维不动）
        2. 消力回写：用真实 satisfaction 当 efficiency 写入 quenching
                     → 这是闭环最终改变她语言能力的出口

    结算后清空队列（已结算的意图不重复结算）。

    返回结算摘要（供日志/调试）。
    """
    q = getattr(entity, "_pending_intents", None)
    if not q:
        return {"settled": 0}

    # 洞④：这句回应相对最近双方对话历史的新颖度。原样复读/打转 → novelty→0。
    # 整批意图共用同一 novelty（只取决于 input vs 历史），故循环外算一次。
    history = _get_dialogue_history(entity)
    novelty = _compute_novelty(input_text, history)

    settled: List[Dict[str, Any]] = []
    for intent in list(q):
        relevance = _similarity(input_text, intent["expression"])
        age = float(int(tick) - int(intent["tick"]))
        recency = min(1.0, math.exp(-age / _TAU_INTENT))
        satisfaction = float(intent["strength"]) * relevance * recency * novelty

        drive = intent["drive"]
        k = _K_SATISFY[drive]
        cur = float(getattr(entity, drive, 0.0))
        setattr(entity, drive, _clamp(cur - satisfaction * k))

        # 诚实满足 → 真实身体后果：标量即时（暖/松）+ 粒子余韵。
        _soma = satisfaction * _SOMA_FROM_SATISFY.get(drive, 0.0)
        _relief = satisfaction * _RELIEF_FROM_SATISFY.get(drive, 0.0)
        _apply_somatic_consequence(entity, _soma, _relief)
        _queue_feeling(entity, _FEELING_LABEL.get(drive, "被回应"),
                       satisfaction * _PARTICLE_FROM_SATISFY)

        _writeback_quenching(
            entity, intent["expression"], satisfaction, tick,
            template_idx=int(intent.get("template_idx", -1)),
        )

        settled.append({
            "drive": drive,
            "relevance": round(relevance, 3),
            "recency": round(recency, 3),
            "novelty": round(novelty, 3),
            "satisfaction": round(satisfaction, 4),
            "soma": round(_soma, 4),
            "relief": round(_relief, 4),
            "expression": intent["expression"][:20],
        })

    q.clear()
    # 结算完把这句回应纳入历史，供后续 novelty 比较（不与自身比，故循环后压）。
    history.append(input_text)

    total_sat = sum(s["satisfaction"] for s in settled)
    logger.info(
        f"[ExprFeedback] 结算 {len(settled)} 条意图，总满足={total_sat:.4f} "
        f"(novelty={novelty:.3f})"
    )
    return {"settled": len(settled), "total_satisfaction": total_sat,
            "novelty": novelty, "detail": settled}


# ============================================================================
# 模块 B' — 认知信用结算（洞②，延迟结算后半段）
# ============================================================================

def settle_epistemic_credit(entity: Any, tick: int) -> Dict[str, Any]:
    """
    在后续某拍（异步 WM 已跑过 verify 之后）结算挂账的认知信用。

    对每条到期（age >= _SETTLE_DELAY）挂账：
        cur_conf = 该 rule_id 的当前世界模型置信度
        gain     = max(0, cur_conf - 提问时置信度)   — 只奖正向印证
        recency  = exp(-(tick - 挂账tick) / TAU)
        reward   = gain × recency × _K_EPISTEMIC

    reward 走 _writeback_quenching（带 template_idx）强化该句式，
    并按比例轻推 unresolved↓（疑问真被解决对应的维度变化）。

    回声防线：confidence 只在 verify 判定"预测兑现"时升。对方复述她的话
    不产生确认性状态变化 → gain=0 → 无奖励。echo 拿不到认知信用。

    未到期的条目保留；到期的结算后移除。返回结算摘要。
    """
    q = getattr(entity, "_pending_epistemic_credit", None)
    if not q:
        return {"settled": 0}

    rules = getattr(entity, "wm_rules", None) or []
    conf_by_id = {_rule_id(r): _rule_conf(r) for r in rules}

    settled: List[Dict[str, Any]] = []
    keep: List[Dict[str, Any]] = []

    for credit in list(q):
        age = float(int(tick) - int(credit["tick"]))
        mature = age >= _SETTLE_DELAY

        def _settle(credit=credit, age=age):
            cur_conf = float(conf_by_id.get(credit["q_rule_id"], credit["q_conf_at_ask"]))
            gain = max(0.0, cur_conf - float(credit["q_conf_at_ask"]))
            recency = min(1.0, math.exp(-age / _TAU_EPISTEMIC))
            reward = gain * recency * _K_EPISTEMIC

            _writeback_quenching(
                entity, credit["expression"], reward, tick,
                template_idx=int(credit.get("template_idx", -1)),
            )
            # 疑问真被推进 → unresolved 按比例轻推下降（复用满足系数）。
            cur_ur = float(getattr(entity, "unresolved", 0.0))
            setattr(entity, "unresolved", _clamp(cur_ur - reward * _K_SATISFY["unresolved"]))

            # 想通了 → 真实身体后果：踏实/松一口气（标量）+ 余韵粒子。
            _soma = reward * _SOMA_FROM_EPISTEMIC
            _relief = reward * _RELIEF_FROM_EPISTEMIC
            _apply_somatic_consequence(entity, _soma, _relief)
            _queue_feeling(entity, _FEELING_LABEL["_epistemic"], reward * _PARTICLE_FROM_EPISTEMIC)

            settled.append({
                "rule_id": credit["q_rule_id"],
                "gain": round(gain, 4),
                "recency": round(recency, 3),
                "reward": round(reward, 4),
                "soma": round(_soma, 4),
                "relief": round(_relief, 4),
                "expression": credit["expression"][:20],
            })

        def _hold(credit=credit):
            keep.append(credit)

        # dict 分发替代 if：到期结算，未到期保留。
        {True: _settle, False: _hold}[mature]()

    # 重建队列只留未到期条目。
    new_q = _get_epistemic_queue(entity)
    new_q.clear()
    new_q.extend(keep)

    total_reward = sum(s["reward"] for s in settled)
    _log_summary = {
        True:  lambda: logger.info(
            f"[ExprFeedback] 认知信用结算 {len(settled)} 条，总奖励={total_reward:.4f}，"
            f"待结算 {len(keep)} 条"
        ),
        False: lambda: None,
    }[bool(settled)]
    _log_summary()
    return {"settled": len(settled), "total_reward": total_reward,
            "pending": len(keep), "detail": settled}


def _writeback_quenching(
    entity: Any,
    expression: str,
    satisfaction: float,
    tick: int,
    template_idx: int = -1,
) -> None:
    """
    用真实满足量当 efficiency 回写消力记录。

    efficiency = max(0, before - after) = satisfaction（after 取 0）。
    这替代了 reading_acquisition 里写死的 0.0 efficiency——
    说了能换来回应的表达，efficiency 才高，才会被升温/句式系统强化。

    注意：word_warmup 读的是持久化字段 entity._quenching_data（dict），
    不是 live tracker。所以记录后必须把 tracker 同步回 _quenching_data，
    否则升温系统看不到这条记录。
    """
    try:
        quench = _ensure_tracker(entity)
        entity._quenching = quench

        state = entity.to_state_snapshot() if hasattr(entity, "to_state_snapshot") else {}
        quench.record(
            drive_state=state,
            expression=expression,
            delta_unresolved_before=float(satisfaction),
            delta_unresolved_after=0.0,
            tick=int(tick),
            template_idx=int(template_idx),
        )
        # 同步回持久化字段，供 word_warmup 读取 + 落盘
        entity._quenching_data = quench.to_dict()
    except Exception as e:
        logger.debug(f"[ExprFeedback] quenching writeback skipped: {e}")


# ============================================================================
# 相关度：BGE 优先，回退汉字重叠
# ============================================================================

def _similarity(a: str, b: str) -> float:
    """文本相关度 [0,1]。BGE 嵌入余弦优先，不可用时回退汉字 Jaccard。"""
    if not a or not b:
        return 0.0
    try:
        from .bge_analyzer import _get_bge_model
        import numpy as np

        model = _get_bge_model()
        embs = model.encode([a, b], normalize_embeddings=True)
        return max(0.0, float(np.dot(embs[0], embs[1])))
    except Exception:
        return _char_overlap(a, b)


def _as_dict(x: Any) -> Dict[str, Any]:
    """类型归一：非 dict 一律视为空 dict。无分支。"""
    return {True: lambda: x, False: lambda: {}}[isinstance(x, dict)]()


def _ensure_tracker(entity: Any):
    """取/重建 QuenchingTracker。tracker 缺失时从持久化字段重建（空 dict 也安全）。"""
    from .quenching import QuenchingTracker

    existing = getattr(entity, "_quenching", None)
    data = _as_dict(getattr(entity, "_quenching_data", None))
    return {
        True:  lambda: existing,
        False: lambda: QuenchingTracker.from_dict(data),
    }[isinstance(existing, QuenchingTracker)]()


def _char_overlap(a: str, b: str) -> float:
    """汉字 Jaccard 相似度——共享字越多越相关。"""
    sa, sb = set(a), set(b)
    union = sa | sb
    inter = sa & sb
    return len(inter) / max(1, len(union))


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


# ============================================================================
# 诚实奖励的身体后果（标量即时 + 粒子余韵）
# ============================================================================

def _apply_somatic_consequence(entity: Any, soma_delta: float, relief_delta: float) -> None:
    """把诚实奖励的标量身体后果写回。自带钳位——②跑在 pipeline 外，无 s07a 兜底。

    soma_delta  >=0：抬 somatic_tone（[-1,1] 钳位）
    relief_delta>=0：降 relief_debt（[0,1] 钳位，降低=体验到松一口气）
    """
    cur_tone = float(getattr(entity, "somatic_tone", 0.0))
    setattr(entity, "somatic_tone", max(-1.0, min(1.0, cur_tone + soma_delta)))
    cur_relief = float(getattr(entity, "relief_debt", 0.0))
    setattr(entity, "relief_debt", max(0.0, min(1.0, cur_relief - relief_delta)))


def _queue_feeling(entity: Any, dimension: str, intensity: float) -> None:
    """把一颗待注入情绪粒子挂到 entity 内存队列，留给下一拍 s03 drain 进活粒子场。

    粒子场活对象只在 pipeline 内（s03→s07b）存在，②够不着，故此处只排队不直接注入。
    intensity<=0 视为无感受，不挂账（与 ParticleField.add_particle 的零强度守卫一致）。
    """
    intensity = max(0.0, min(1.0, float(intensity)))
    if intensity <= 0.0:
        return
    q = getattr(entity, "_pending_feeling_injections", None)
    is_deque = isinstance(q, deque)
    q = {True: lambda: q, False: lambda: deque(maxlen=_FEELING_QUEUE_MAXLEN)}[is_deque]()
    q.append({"dimension": str(dimension), "intensity": intensity, "half_life": _FEELING_HALF_LIFE})
    entity._pending_feeling_injections = q


# ============================================================================
# 抗回声 novelty（洞④）——堵 relevance 的回声漏洞
# ============================================================================
# relevance=相似度(对方回应, 她那句话)：对方逐字复读她的话时 relevance≈1，
# 奖励反而最高——这是回声室的结构漏洞。novelty 衡量"这句回应相对最近双方
# 对话历史是否带来新内容"：原样复读/车轱辘打转 → novelty→0 掐灭；话题相关
# 但新措辞 → relevance 高且 novelty 高，拿满分。satisfaction 末项乘 novelty。

def _get_dialogue_history(entity: Any) -> Deque[str]:
    """取/建 entity 上的最近对话历史（双方原文混合）。deque(maxlen) 自动驱逐。"""
    h = getattr(entity, "_recent_dialogue", None)
    is_deque = isinstance(h, deque)
    factory = {
        True:  lambda: h,
        False: lambda: deque(maxlen=_NOVELTY_HISTORY),
    }[is_deque]
    new_h = factory()
    entity._recent_dialogue = new_h
    return new_h


def _compute_novelty(text: str, history: Deque[str]) -> float:
    """
    text 相对最近对话历史的新颖度 ∈ [0,1]。

    novelty = 1 - max(相似度(text, 历史每一句))。
    空历史（无可比）→ max(default=0) → novelty=1.0（完全新颖）。
    """
    sims = [_similarity(text, prev) for prev in history]
    max_sim = max(sims, default=0.0)
    return _clamp(1.0 - max_sim)
