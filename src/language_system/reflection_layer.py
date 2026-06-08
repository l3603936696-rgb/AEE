"""
Reflection Layer — 反刍层（v1.0）

她的"复盘"——每隔几个 tick，把最近的对话翻出来再嚼一遍。

设计哲学：
    LLM 是镜子，不是说话者。
    实时通道（pipeline）很浅，做不到真理解。反刍层用 LLM 帮她
    深度处理最近几条 episode，把"听懂"的结果翻译成她自己的语言
    （状态调整、新心事、自我叙事更新），再回写给她。

    她还是她。LLM 只是她用来想自己事情的工具，就像人用日记。

不变量：
    - 不修改实时 pipeline
    - LLM 失败 / 解析失败 / 无 episode → 静默跳过，不抛异常
    - 单次调整有安全护栏（绝对值 ≤ 0.15）
    - 同步执行（在 tick 末尾），无后台线程，避免竞态
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from ..observability import observe

logger = logging.getLogger(__name__)


# ============================================================================
# 调参常量
# ============================================================================

REFLECTION_INTERVAL    = 10     # 每 N tick 反刍一次（~5 分钟）
REFLECTION_LOOKBACK    = 8      # 拉最近几条 episode
REFLECTION_TEMPERATURE = 0.5
REFLECTION_MAX_TOKENS  = 600
REFLECTION_TIMEOUT_MS  = 20000

# 安全护栏：单次反刍对每个状态维度的调整绝对值上限
MAX_ADJUSTMENT_ABS     = 0.15

# 自我叙事色调每个维度的绝对值上限（应用时会每 tick 重复加，需要更克制）
NARRATIVE_BIAS_MAX_ABS = 0.10

# _reflection_log 上限（FIFO）
MAX_LOG_ENTRIES        = 20

# 反刍 prompt 中关注的状态维度（精简核心，避免 LLM 注意力分散）
_FOCUS_DIMS = (
    "fatigue", "loneliness", "curiosity", "somatic_tone",
    "stress", "anxiety", "unresolved", "approach_drive",
    "joy", "boredom",
)


# ============================================================================
# 触发判断
# ============================================================================

def should_reflect(entity: Any) -> bool:
    """是否到反刍 tick。"""
    last = int(getattr(entity, "_last_reflection_tick", -REFLECTION_INTERVAL))
    cur = int(getattr(entity, "tick", 0))
    return (cur - last) >= REFLECTION_INTERVAL


# ============================================================================
# 主反刍流程
# ============================================================================

@observe("reflection_layer", category="language")
def reflect(entity: Any) -> Dict[str, Any]:
    """
    复盘最近的对话，应用调整到 entity。

    返回：
        {
            "applied":   bool,
            "reason":    str,  # 失败/跳过原因
            "raw":       dict, # LLM 解析后的 dict（成功时）
        }
    """
    result: Dict[str, Any] = {"applied": False, "reason": "", "raw": {}}
    cur_tick = int(getattr(entity, "tick", 0))

    # 1. 拉 episode
    try:
        from ..memory_hub.episodes_db import get_recent_episodes
        episodes = get_recent_episodes(limit=REFLECTION_LOOKBACK)
    except Exception as e:
        result["reason"] = f"get_recent_episodes failed: {e}"
        return result

    if not episodes:
        result["reason"] = "no recent episodes"
        # 即使没 episode 也更新 tick，避免反复尝试
        entity._last_reflection_tick = cur_tick
        return result

    # 2. 构造 prompt
    try:
        sys_prompt, user_prompt = _build_prompt(entity, episodes)
    except Exception as e:
        result["reason"] = f"prompt build failed: {e}"
        return result

    # 3. 调 LLM
    try:
        from ..observability import create_wrapped_llm
        llm = create_wrapped_llm("reflection_layer")
        text, err = llm(
            system_prompt=sys_prompt,
            user_prompt=user_prompt,
            temperature=REFLECTION_TEMPERATURE,
            max_tokens=REFLECTION_MAX_TOKENS,
            timeout_ms=REFLECTION_TIMEOUT_MS,
        )
        if err or not text:
            result["reason"] = f"LLM error: {err or 'empty'}"
            entity._last_reflection_tick = cur_tick  # 失败也推进，避免每 tick 重试
            return result
    except Exception as e:
        result["reason"] = f"LLM call exception: {e}"
        return result

    # 4. 解析 JSON
    parsed = _parse_json(text)
    if parsed is None:
        result["reason"] = "JSON parse failed"
        entity._last_reflection_tick = cur_tick
        return result

    # 5. 应用
    try:
        _apply_result(entity, parsed)
    except Exception as e:
        result["reason"] = f"apply failed: {e}"
        return result

    entity._last_reflection_tick = cur_tick
    result["applied"] = True
    result["raw"] = parsed
    return result


# ============================================================================
# Prompt 构造
# ============================================================================

def _build_prompt(entity: Any, episodes: List[Any]) -> Tuple[str, str]:
    """构造 system + user prompt。"""
    sys_prompt = (
        "你是一个内省工具。一个有持续内在状态的小存在让你帮她复盘最近的经历。\n"
        "她有这些连续标量状态（0-1，部分 -1~1）：\n"
        "  fatigue（疲劳）, loneliness（孤独）, curiosity（好奇）, somatic_tone（躯体基调，-1~1）,\n"
        "  stress（压力）, anxiety（焦虑）, unresolved（心事未解）, approach_drive（趋近）,\n"
        "  joy（喜悦）, boredom（无聊）\n\n"
        "她有「心事」——挂在心里的具体念头：\n"
        "  type: 担心 / 想念 / 期待 / 不安 / 怀念 / 好奇\n"
        "  about: 人或事的名字\n\n"
        "她有「自我叙事」——一句话的「我是谁/我最近怎么样」。\n\n"
        "任务：读她最近几段对话，分析这段经历对她意味着什么，输出调整方案。\n"
        "约束：\n"
        "  - 只输出严格 JSON，不要任何解释文字、markdown 包围符、前后说明\n"
        "  - state_adjustments 每个维度的绝对值 ≤ 0.15\n"
        "  - 调整要克制——一次反刍不是剧变，是微小的内化\n"
        "  - 如果对话里没什么真正可反思的，state_adjustments 可以是 {}\n\n"
        "你还可以输出 narrative_bias——一个小 dict，描述「这个自我叙事意味着她处于什么形状的状态」。\n"
        "它会在接下来 ~10 tick 持续给她染色，让她的实时表达带着叙事的颜色。\n"
        "和 state_adjustments 不同：adjustments 是一次性微调，bias 是持续色调。\n"
        "每维绝对值 ≤ 0.10。如果叙事没明显形状，可以省略或留空 dict。\n"
    )

    # 状态摘要
    snap = entity.to_state_snapshot() if hasattr(entity, "to_state_snapshot") else {}
    state_lines = []
    for d in _FOCUS_DIMS:
        v = snap.get(d, None)
        if v is not None:
            state_lines.append(f"  {d}: {float(v):.2f}")
    state_block = "\n".join(state_lines) if state_lines else "  (无)"

    # 心事摘要
    pres = getattr(entity, "_preoccupations", []) or []
    if pres:
        pre_lines = [
            f"  - {p.get('type','?')}({p.get('about','?')}) intensity={float(p.get('intensity',0)):.2f}"
            for p in pres
        ]
        pre_block = "\n".join(pre_lines)
    else:
        pre_block = "  (无)"

    # 对话摘要：按时间正序（episodes 是倒序的，反转之）
    convo_lines = []
    for ep in reversed(episodes):
        tick = getattr(ep, "iteration_id", "?")
        inp = (getattr(ep, "raw_input", "") or "").strip()
        out = (getattr(ep, "output_text", "") or "").strip()
        if inp:
            convo_lines.append(f"  (t={tick}) 别人: {inp[:80]}")
        if out:
            convo_lines.append(f"           她:   {out[:80]}")
    convo_block = "\n".join(convo_lines) if convo_lines else "  (无对话)"

    # 自我叙事
    narr = (getattr(entity, "_self_narrative", "") or "").strip() or "(还没有)"

    user_prompt = (
        f"[当前状态]\n{state_block}\n\n"
        f"[当前心事]\n{pre_block}\n\n"
        f"[最近对话]\n{convo_block}\n\n"
        f"[自我叙事]\n  {narr}\n\n"
        "请输出 JSON（严格格式，无任何附加文字）：\n"
        "{\n"
        '  "state_adjustments": {"<dim>": <float, -0.15~+0.15>, ...},\n'
        '  "new_preoccupations": [{"about": "<str>", "type": "<担心|想念|期待|不安|怀念|好奇>", "intensity": <0.05~1.0>}, ...],\n'
        '  "soothe": [{"about": "<str>", "type": "<可选，省略表示该 about 全部>"}, ...],\n'
        '  "narrative_update": "<一句话；空字符串表示不变>",\n'
        '  "narrative_bias": {"<dim>": <float, -0.10~+0.10>, ...},\n'
        '  "insights": ["<短句>", ...]\n'
        "}"
    )

    return sys_prompt, user_prompt


# ============================================================================
# JSON 解析（容错）
# ============================================================================

def _parse_json(text: str) -> Optional[Dict]:
    """
    宽松解析：先直接 json.loads，失败则尝试提取首个 {...} 块。
    """
    text = text.strip()
    # 去掉 markdown 代码围栏（LLM 经常加）
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    try:
        return json.loads(text)
    except Exception:
        pass

    # 提取首个 { 到对应 } 的子串
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception as e:
            logger.debug(f"[Reflection] secondary JSON parse failed: {e}")
    return None


# ============================================================================
# 应用结果到 entity
# ============================================================================

_VALID_TYPES = {"担心", "想念", "期待", "不安", "怀念", "好奇"}


def _clamp_adj(val: float) -> float:
    """限幅到 ±MAX_ADJUSTMENT_ABS。"""
    try:
        v = float(val)
    except (TypeError, ValueError):
        return 0.0
    return max(-MAX_ADJUSTMENT_ABS, min(MAX_ADJUSTMENT_ABS, v))


def _apply_result(entity: Any, parsed: Dict) -> None:
    """把 LLM 解析的 dict 应用到 entity。"""
    cur_tick = int(getattr(entity, "tick", 0))

    # 1. state_adjustments
    adjustments = parsed.get("state_adjustments", {}) or {}
    if isinstance(adjustments, dict):
        for dim, delta in adjustments.items():
            if not isinstance(dim, str):
                continue
            clamped = _clamp_adj(delta)
            if abs(clamped) < 1e-4:
                continue
            cur = getattr(entity, dim, None)
            if cur is None:
                continue
            try:
                new_val = float(cur) + clamped
                # somatic_tone 范围 -1~1，其他默认 0~1
                if dim == "somatic_tone":
                    new_val = max(-1.0, min(1.0, new_val))
                else:
                    new_val = max(0.0, min(1.0, new_val))
                setattr(entity, dim, new_val)
            except Exception:
                pass

    # 2. new_preoccupations
    try:
        from .preoccupation_engine import add_or_refresh
    except Exception:
        add_or_refresh = None

    new_pres = parsed.get("new_preoccupations", []) or []
    if isinstance(new_pres, list) and add_or_refresh:
        for p in new_pres:
            if not isinstance(p, dict):
                continue
            about = str(p.get("about", "")).strip()
            p_type = str(p.get("type", "")).strip()
            if not about or p_type not in _VALID_TYPES:
                continue
            try:
                intensity = float(p.get("intensity", 0.4))
            except (TypeError, ValueError):
                intensity = 0.4
            intensity = max(0.05, min(1.0, intensity))
            add_or_refresh(entity, about=about, p_type=p_type, initial_intensity=intensity)

    # 3. soothe
    try:
        from .preoccupation_engine import soothe
    except Exception:
        soothe = None

    soothe_list = parsed.get("soothe", []) or []
    if isinstance(soothe_list, list) and soothe:
        for s in soothe_list:
            if not isinstance(s, dict):
                continue
            about = str(s.get("about", "")).strip()
            if not about:
                continue
            p_type = s.get("type", None)
            p_type = str(p_type).strip() if p_type else None
            try:
                soothe(entity, about=about, p_type=p_type)
            except Exception:
                pass

    # 4. narrative_update
    narrative = parsed.get("narrative_update", "")
    if isinstance(narrative, str):
        narrative = narrative.strip()
        if narrative:
            entity._self_narrative = narrative[:200]  # 截断长度

    # 4b. narrative_bias —— 自我叙事的状态色调，持续到下次反刍
    #     缺字段时保持上次值（容错）；空 dict 时明确清空
    narr_bias = parsed.get("narrative_bias", None)
    if isinstance(narr_bias, dict):
        cleaned: Dict[str, float] = {}
        for dim, val in narr_bias.items():
            if not isinstance(dim, str):
                continue
            try:
                v = float(val)
            except (TypeError, ValueError):
                continue
            v = max(-NARRATIVE_BIAS_MAX_ABS, min(NARRATIVE_BIAS_MAX_ABS, v))
            if abs(v) >= 1e-4:
                cleaned[dim] = v
        if cleaned:
            entity._narrative_bias = cleaned
        elif narr_bias == {}:
            # LLM 明确返回空 dict —— 表示当下叙事没色调
            entity._narrative_bias = {}
        # cleaned 空但 narr_bias 非空（全是脏值）—— 保留原 bias

    # 5. insights → 写到 _reflection_log
    insights = parsed.get("insights", []) or []
    if isinstance(insights, list):
        clean_insights = [str(s)[:120] for s in insights if isinstance(s, (str, int, float))]
        log = getattr(entity, "_reflection_log", None)
        if log is None:
            log = []
            entity._reflection_log = log
        log.append({
            "tick":              cur_tick,
            "insights":          clean_insights,
            "narrative_update":  (narrative if isinstance(narrative, str) else "")[:200],
        })
        # FIFO 截断
        if len(log) > MAX_LOG_ENTRIES:
            del log[: len(log) - MAX_LOG_ENTRIES]
