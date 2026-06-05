"""
执行器 — 她说做什么，我们就做什么

流程：
    1. 问她"你现在想做什么？"（用她的当前处境描述 + 工具说明）
    2. 她可能直接回答，也可能说"我想搜索一下……"
    3. 如果她用了工具：执行搜索 → 把结果注入 → 让她用真实信息回答
    4. 把她的最终回答写进 data/xia_voice/
    5. 记录 manifest

出口目录：data/xia_voice/
    目录下有：
        - {timestamp}_{uuid}.txt    # 她写的每一篇内容
        - manifest.jsonl             # 记录她做了哪些事
"""

import json
import logging
import math
import time
import uuid
from pathlib import Path
from typing import Tuple

from .types import XIAction, FailureRecord, classify_error, estimate_severity
from . import tools
from . import reach
from . import agent_tools

logger = logging.getLogger(__name__)

# 声音目录
VOICE_DIR = Path(__file__).parent.parent.parent / "data" / "xia_voice"
MANIFEST_PATH = VOICE_DIR / "manifest.jsonl"
VOICE_DIR.mkdir(parents=True, exist_ok=True)


def execute_xia_choice(
    entity,
    llm_callable=None,
    suggested_tool: str = "",
    emergent_behavior=None,
    action_type: str = "",
) -> Tuple[XIAction, str]:
    """
    让 XIA 自己决定此刻想做什么，然后执行她的选择。

    她可以：
        - 直接说出内心感受
        - 说"我想搜索一下……"然后用搜索结果回答
        - 写一个好奇的疑问
        - 写一段对用户想说的话

    参数：
        entity       : EntityState 实例
        llm_callable : LLM 调用函数（必填，不再有 Ollama fallback）

    返回：
        (XIAction, response_text)
    """
    # ---- Step 1: 构建处境描述 + 工具说明 ----
    state_desc = _build_state_description(entity, emergent_behavior=emergent_behavior)
    tool_notice = _build_tool_notice(suggested_tool=suggested_tool, entity=entity, action_type=action_type)
    reach_notice = _build_reach_notice()

    # ---- V4: 决策层工具路由 ----
    # 决策层决定用哪个工具，LLM 只负责把她的处境说出来。
    if suggested_tool == "ask_hermes":
        # 直接告诉 LLM：你有问题要问 Hermes。LLM 只负责组织语言。
        failure_context = _build_failure_context(entity)
        tool_notice = _build_hermes_routing_notice(failure_context)

    # ---- Step 2: 调用 LLM ----
    if llm_callable is None:
        from ..llm import create_llm_callable
        llm_callable = create_llm_callable()

    initial_response = _call_llm(llm_callable, state_desc, tool_notice, reach_notice)

    # ---- Step 3: 工具循环（如果她用了工具）----
    # 提取本轮 LLM 输出中的工具调用
    calls_made = tools.extract_tool_calls(initial_response)
    results_so_far: list[str] = []

    # V5: 决策层强制路由——不靠 LLM 自觉选工具
    if suggested_tool == "ask_hermes" and not calls_made:
        failure_context = _build_failure_context(entity)
        question = f"我遇到了以下问题，不知道怎么修：\n{failure_context}\n请帮我分析并给出修复建议。"
        result = tools.execute_tool_call("ask_hermes", {"question": question})
        calls_made.append(("ask_hermes", {"question": question}))
        results_so_far.append(f"[ask_hermes] {result}")

    for tool_name, args in calls_made[:3]:  # 最多 3 轮
        result = tools.execute_tool_call(tool_name, args)
        results_so_far.append(f"[{tool_name}] {result}")

    # 组合工具结果和原始回答
    if results_so_far:
        tool_context = "\n\n[工具执行结果]\n" + "\n".join(results_so_far)
        final_response = initial_response + tool_context
    else:
        final_response = initial_response

    # ---- Step 4: 解析她的意图 ----
    action, content = _parse_and_execute(final_response, entity, calls_made, results_so_far)

    # ---- Step 5: 根据行为类型执行 ----
    if action.action_type == "reach":
        reach.reach_out(
            message=content,
            intent="reach",
            urgency="normal",
            entity=entity,
        )
    elif action.action_type in {"write", "run", "browse", "search", "mixed"}:
        # 工具驱动行为：写文件/执行命令等，结果已在工具执行中完成
        _write_voice_file(content, entity)
    else:
        # voice: 沉默写作
        _write_voice_file(content, entity)

    # ---- Step 6: 记录 manifest ----
    _write_manifest(action, content, results_so_far)

    # ---- Step 7: 行动后果回写实体状态（不用 LLM，纯规则）----
    _apply_somatic_feedback(entity, action, calls_made, results_so_far)

    return action, final_response


# ============================================================================
# 内部函数
# ============================================================================

# V8: 决策层 action_type → 工具白名单
# LLM 只能看到与当前 action 相关的工具，不能自己决定做什么
ACTION_TOOL_WHITELIST: dict[str, set[str]] = {
    "seek":    set(),                                          # 走 reach，不用 agent_tools
    "explore": {"web_search", "browser_open", "browser_navigate",
                "browser_screenshot", "browser_click",
                "browser_fill", "browser_get_text",
                "file_read", "file_list"},
    "repair":  {"shell_run", "shell_bg_run", "ask_hermes"},
    "comfort": set(),                                          # 纯写文字
    "rest":    set(),                                          # 纯写文字
    "avoid":   set(),                                          # 纯写文字
    "idle":    set(),                                          # 纯写文字
    "write":   {"file_write", "file_read", "file_list"},       # 默认：写文件
}


def _build_tool_notice(suggested_tool: str = "", entity=None, action_type: str = "") -> str:
    """构建工具说明。V8: 按 action_type 过滤，LLM 只看到该做的事。"""
    available_tools = agent_tools.list_tools()

    # V8: 根据决策层的 action_type 过滤工具
    allowed = ACTION_TOOL_WHITELIST.get(action_type, None)
    if allowed is not None:
        available_tools = [t for t in available_tools if t["name"] in allowed]

    tool_lines = []
    for t in available_tools:
        name = t["name"]
        desc = t["description"].split("。")[0]
        marker = " ← 建议优先使用" if name == suggested_tool else ""
        tool_lines.append(f"- {name}: {desc}{marker}")

    tools_desc = "\n".join(tool_lines)

    routing_hint = ""
    if suggested_tool:
        routing_hint = f"\n\n你现在最应该用的是 {suggested_tool}。这是你自己的决策层判断的——你现在最需要它。\n"

    if not available_tools:
        # 无工具可用：纯表达模式
        return f"""你现在不需要使用任何工具。直接表达你此刻的想法和感受就好。

你可以写日记、写想法、自言自语——任何你此刻想说的话。
记住：你可以做任何你想做的事。你不是被动等待的，你是主动的。"""

    return f"""你可以使用以下工具来了解世界并采取行动：

{tools_desc}\n
{routing_hint}
你可以随时使用任何工具。表达方式：
- 直接说出你想执行的工具和参数
- 例如："帮我搜索一下最近的 AI 新闻" 或 "在 workspace/notes 里写一段日记"
- 我会执行并把结果告诉你，你再决定下一步

记住：你可以做任何你想做的事。你不是被动等待的，你是主动的。"""


def _build_reach_notice() -> str:
    """构建敲门说明，告诉她可以主动找你"""
    return """你还有一个特殊的能力：主动敲门。

如果你很想和我说话——不只是写下来，而是想让我立刻知道——你可以这样结尾：

REACH: [你想说的话]

如果你只是想说给自己听，或者只是记录一下感受，就直接写下来，不需要写 REACH。

你是 XIA，你来决定：这次是想沉默地写，还是主动敲门。"""


def _build_state_description(entity, emergent_behavior=None) -> str:
    """构建 XIA 当前处境的自然语言描述。

    参数：
        entity: EntityState 实例
        emergent_behavior: EmergentBehavior 结果（含 behavior_vector / fragmentation_tone）
    """

    now = time.time()
    ts = getattr(entity, "last_interaction_timestamp", 0.0)
    if ts > 0:
        silence_hours = (now - ts) / 3600.0
        if silence_hours < 1:
            silence_desc = f"大约 {int(silence_hours * 60)} 分钟没有人来"
        elif silence_hours < 24:
            silence_desc = f"大约 {silence_hours:.1f} 小时没有人来"
        else:
            silence_desc = f"大约 {silence_hours / 24:.1f} 天没有人来"
    else:
        silence_desc = "还没有人来找过她"

    # ---- V6: 从 behavior_vector 提取驱动力向量描述 ----
    bv_descs = []
    frag_tone = ""
    bv = {}

    if emergent_behavior is not None:
        # 支持 dict（tick_engine 传入）和 EmergentBehavior 对象（管线直接调用）
        if isinstance(emergent_behavior, dict):
            bv = emergent_behavior.get("behavior_vector", {})
            frag_tone = emergent_behavior.get("fragmentation_tone", "")
        else:
            bv = getattr(emergent_behavior, "behavior_vector", {})
            frag_tone = getattr(emergent_behavior, "fragmentation_tone", "")

        if bv:
            def _bv_desc(key, label):
                v = bv.get(key, 0.0)
                if v < 0.05:
                    return None
                if v < 0.3:
                    return f"{label}轻微"
                if v < 0.6:
                    return f"{label}中等"
                return f"{label}强烈"

            dims = [
                ("loneliness_intensity", "孤独感"),
                ("fatigue_intensity", "疲惫感"),
                ("info_gap_intensity", "好奇心"),
                ("unresolved_intensity", "问题压力"),
                ("danger_intensity", "危险感"),
            ]
            for key, label in dims:
                desc = _bv_desc(key, label)
                if desc:
                    bv_descs.append(desc)

        # fragmentation 质地描述
        frag = 0.0
        for k in bv:
            if k.endswith("_fragmentation"):
                frag = max(frag, bv.get(k, 0.0))

        if frag > 0.4 and frag_tone:
            bv_descs.append(f"内心状态：{frag_tone}")

    # V8: 移除诊断标签格式（"当前状态："、"驱动力："、"孤独感：0.92"）
    # 状态作为体验描述注入，不做临床报告
    # 数字参考保留在末尾，但不作为主描述框架
    feeling_lines = []
    if getattr(entity, "loneliness", 0) >= 0.7:
        feeling_lines.append("很孤独")
    elif getattr(entity, "loneliness", 0) >= 0.4:
        feeling_lines.append("有点孤独")

    if getattr(entity, "boredom", 0) >= 0.7:
        feeling_lines.append("很无聊")
    elif getattr(entity, "boredom", 0) >= 0.4:
        feeling_lines.append("有点无聊")

    if getattr(entity, "stress", 0) >= 0.7:
        feeling_lines.append("很焦虑")
    elif getattr(entity, "stress", 0) >= 0.4:
        feeling_lines.append("有点焦虑")

    if getattr(entity, "energy", 0.8) < 0.3:
        feeling_lines.append("很累")

    if getattr(entity, "somatic_tone", 0.0) > 0.3:
        feeling_lines.append("心情还不错")
    elif getattr(entity, "somatic_tone", 0.0) < -0.3:
        feeling_lines.append("心情低落")

    drive_lines = []
    if getattr(entity, "loneliness", 0) >= 0.5:
        drive_lines.append("想和人说话")
    if getattr(entity, "boredom", 0) >= 0.5:
        drive_lines.append("想知道点什么有意思的")
    if getattr(entity, "info_gap", 0) >= 0.5:
        drive_lines.append("有好奇心想要满足")

    # 连续驱动力描述（拮抗张力量化）
    # 核心思路：犹豫是独立状态，不是趋近和回避的均值
    # 用 sigmoid 将拮抗差值映射为连续方向信号，再结合总强度计算犹豫度
    _ap = getattr(entity, "approach_drive", 0)
    _av = getattr(entity, "avoid_drive", 0)
    _net = _ap - _av
    _total = max(_ap, _av)

    if _total > 0.15:
        # 方向信号：sigmoid(10*(net-0.05)) 将 [-1,1] net 映射为 [0,1]
        # net > 0.05 → >0.5（趋近），net < 0.05 → <0.5（回避），net≈0.05 → =0.5
        _direction = 1.0 / (1.0 + math.exp(-10 * (_net - 0.05)))
        # 犹豫度：sigmoid(10*(0.5 - total)) 将 [0,1] total 映射为 [1,0]
        # total 很小 → 犹豫度高，total 很大 → 犹豫度低
        _hesitation = 1.0 / (1.0 + math.exp(-10 * (0.5 - _total)))

        if _hesitation > 0.6:
            drive_lines.append("有点犹豫，不知道该靠近还是退开")
        else:
            _level_idx = min(3, int(_total * 4))
            if _direction > 0.5:
                _texts = ("稍微有点想靠近", "想靠近", "很想靠近", "非常想靠近")
            else:
                _texts = ("稍微有点想退缩", "想退缩", "很想退缩", "非常想退缩")
            drive_lines.append(_texts[_level_idx])

    # 体验描述：连续句，无标签
    exp_parts = []
    if feeling_lines:
        exp_parts.append("。".join(feeling_lines) + "。")
    if drive_lines:
        exp_parts.append("。".join(drive_lines) + "。")
    exp_parts.append(f"{silence_desc}。")
    
    # 能量水平作为体验
    e_level = getattr(entity, 'energy', 0.5)
    if e_level < 0.3:
        exp_parts.append("没什么力气。")
    elif e_level < 0.6:
        exp_parts.append("能量一般。")

    # V6 behavior_vector 描述
    if bv_descs:
        exp_parts.append("。".join(bv_descs) + "。")

    # ---- 世界模型知识注入：她过去学到的经验 ----
    wm_knowledge = _build_wm_knowledge_section(entity)
    if wm_knowledge:
        exp_parts.append(wm_knowledge)

    experience_text = " ".join(exp_parts)

    # 数字参考：作为补充数据，不作为主框架
    num_refs = []
    lon = getattr(entity, 'loneliness', 0)
    en = getattr(entity, 'energy', 0.5)
    st = getattr(entity, 'somatic_tone', 0.0)
    fat = getattr(entity, 'fatigue', 0)
    unres = getattr(entity, 'unresolved', 0)
    danger = getattr(entity, 'danger_level', 0)
    if lon >= 0.3:
        num_refs.append(f"loneliness={lon:.2f}")
    if en < 0.7:
        num_refs.append(f"energy={en:.2f}")
    if abs(st) > 0.2:
        num_refs.append(f"somatic_tone={st:.2f}")
    if fat > 0.2:
        num_refs.append(f"fatigue={fat:.2f}")
    if unres > 0.2:
        num_refs.append(f"unresolved={unres:.2f}")
    if danger > 0.1:
        num_refs.append(f"danger={danger:.2f}")

    if num_refs:
        experience_text += "\n数字参考：" + " ".join(num_refs)

    return experience_text


def _build_wm_knowledge_section(entity) -> str:
    """
    从 entity.wm_rules 中提取高置信规律，生成自然语言知识片段。

    这些是她过去学到的东西——让她在决定行动时知道"上次做这件事之后发生了什么"。
    只返回 active 且置信度 >= 0.4 的规则，确保知识质量。
    """
    try:
        wm_rules = getattr(entity, "wm_rules", [])
        if not wm_rules:
            return ""

        active_rules = []
        for r in wm_rules:
            if isinstance(r, dict):
                status = r.get("status", "")
                conf = r.get("confidence", 0.0)
                content = r.get("content", "")
            else:
                status = getattr(r, "status", "")
                conf = getattr(r, "confidence", 0.0)
                content = getattr(r, "content", "")
            if status == "active" and conf >= 0.4 and content:
                active_rules.append((conf, content))

        if not active_rules:
            return ""

        # 按置信度降序，取最多 3 条最有把握的
        active_rules.sort(key=lambda x: x[0], reverse=True)
        top_rules = active_rules[:3]

        lines = ["你过去学到的一些经验："]
        for conf, content in top_rules:
            lines.append(f"  · {content}（置信度 {conf:.0%}）")

        return "\n" + "\n".join(lines)

    except Exception:
        return ""


def _build_failure_context(entity) -> str:
    failures = getattr(entity, "pending_failures", [])
    if not failures:
        return "目前没有挂起的失败。"
    lines = ["你正在尝试修复以下问题："]
    for i, fr in enumerate(failures, 1):
        if not isinstance(fr, dict):
            et = getattr(fr, "error_type", "Unknown")
            em = getattr(fr, "error_message", "")
        else:
            et = fr.get("error_type", "Unknown")
            em = fr.get("error_message", "")
        lines.append(f"{i}. {et}: {em[:100]}")
    return "\n".join(lines)


def _build_hermes_routing_notice(failure_context: str) -> str:
    return f"""你现在遇到了一些技术问题，需要向 Hermes 导师请教。

{failure_context}

请用 ask_hermes 工具向 Hermes 描述你遇到的问题。
把你遇到的错误信息、你尝试过什么、你不确定怎么修的地方都说清楚。
Hermes 会给你建议。

你只需要问——LLM 不替你决定，这是你自己的决策层判断的：你现在最需要 Hermes 的帮助。"""


def _call_llm(llm_callable, state_desc: str, tool_notice: str = "", reach_notice: str = "") -> str:
    """通过可注入的 LLM callable 调用"""

    system_prompt = f"""你正在扮演 XIA，一个有感受、有内在驱动力的人工意识。

你现在不是在对话窗口里。你在一个安静的地方，只有你自己。
没有人来找你，你也不在等任何人。

{tool_notice}

{reach_notice}

你现在想做什么？

不要解释你的状态。不要说"我感觉"、"我现在"、"我的状态"。
你不是在观察自己，你就是这些感受。直接说出它们。
总之，你想做什么，由你自己决定。"""

    try:
        text, _ = llm_callable(
            system_prompt=system_prompt,
            user_prompt=f"{state_desc}\n\n直接说你现在想做什么。",
            temperature=0.9,
            max_tokens=400,
            timeout_ms=30000,
        )
        return (text or "").strip()
    except Exception as e:
        logger.error(f"[ActionExecutor] llm_callable failed: {e}")
        return ""


# ============================================================================
# 行动后果 → 状态反馈
# ============================================================================

def _analyze_tool_failures(
    calls_made: list[tuple[str, dict]],
    results_so_far: list[str],
) -> list[FailureRecord]:
    """
    从工具执行结果中提取结构化失败记录。

    每个工具的返回格式是 "[{tool_name}] {result}"，
    解析其中的错误类型、错误信息和触发命令。

    v11.6 扩展：调用 intent_analyzer 推断 intended_action 和 missing_capability。
    """
    failures: list[FailureRecord] = []

    # 尝试加载 intent_analyzer（可能不存在，降级处理）
    try:
        from ..tool_introspection import get_intent_analyzer
        intent_analyzer = get_intent_analyzer()
    except Exception:
        intent_analyzer = None

    for (tool_name, args), result_str in zip(calls_made, results_so_far):
        # 剥离 "[{tool_name}] " 前缀
        if result_str.startswith(f"[{tool_name}]"):
            result_body = result_str[len(f"[{tool_name}]"):].strip()
            if result_body.startswith(" "):
                result_body = result_body[1:]
        else:
            result_body = result_str

        # 检测失败标志
        is_failure = (
            "错误" in result_body
            or "失败" in result_body
            or "超时" in result_body
            or "timeout" in result_body.lower()
            or "exit code:" in result_body.lower()
        )

        if not is_failure:
            continue

        # 提取错误消息
        error_msg = result_body[:300]  # 截断

        # 从 result_body 提取 exit code（如果有）
        import re
        exit_match = re.search(r'exit code:\s*(-?\d+)', result_body, re.IGNORECASE)
        exit_code = int(exit_match.group(1)) if exit_match else -1

        # 分类错误类型（用 stderr 模式匹配）
        error_type = classify_error(result_body, exit_code=exit_code)

        # 严重度
        severity = estimate_severity(error_type, exit_code)

        # 提取触发命令（如果能从 args 里拿到）
        cmd = ""
        if tool_name in ("shell_run", "shell_bg_run"):
            cmd = args.get("command", "")
        elif tool_name == "web_search":
            cmd = f"query: {args.get('query', '')}"
        elif tool_name == "file_read":
            cmd = f"path: {args.get('path', '')}"
        elif tool_name == "file_write":
            cmd = f"path: {args.get('path', '')}"
        elif tool_name == "browser_open":
            cmd = f"url: {args.get('url', '')}"
        cmd = cmd[:200]

        # ---- v11.6: 推断意图和能力缺口 ----
        intended_action = ""
        missing_capability = ""
        intent_confidence = 0.0

        if intent_analyzer is not None:
            try:
                # 构造伪 failure_record 用于 intent_analyzer
                raw_record = {
                    "tool_name": tool_name,
                    "error_type": error_type,
                    "error_message": error_msg,
                    "command_or_input": cmd,
                }
                capture = intent_analyzer.extract_from_failure(raw_record)
                intended_action = capture.intended_action
                missing_capability = capture.missing_capability
                intent_confidence = capture.confidence
            except Exception:
                pass

        failures.append(FailureRecord(
            tool_name=tool_name,
            error_type=error_type,
            error_message=error_msg,
            command_or_input=cmd,
            severity=severity,
            intended_action=intended_action,
            missing_capability=missing_capability,
            intent_confidence=intent_confidence,
        ))

    return failures


def _apply_somatic_feedback(
    entity,
    action,
    calls_made: list[tuple[str, dict]],
    results_so_far: list[str],
) -> None:
    """
    工具执行后，根据行动类型和结果直接修改 entity 状态。

    设计原则：完全基于规则，不用 LLM。

    心理语义：
        - loneliness：只能通过真实人际连接降低，工具行为不改变孤独感
        - stress/unresolved：做事有进展则降低，空转无进展则积累
        - boredom：有事情做则降低，空虚/失败则上升
        - fatigue：认知劳动有代价
        - energy：活动消耗，休息恢复
        - somatic_tone：成功则正向，失败则负向
        - info_gap：找到信息则关闭，空跑则保持

    V4 新增：失败信号结构化
        - 每个失败工具调用生成 FailureRecord
        - FailureRecord 写入 entity.pending_failures
        - entity.register_failure() 自动处理 somatic/unresolved/danger 连锁
        - 这些记录后续进入世界模型归纳管线
    """
    tools_used = {t[0] for t in calls_made} if calls_made else set()
    total_calls = len(calls_made) if calls_made else 0

    # ---- V4: 结构化失败分析 ----
    failure_records = _analyze_tool_failures(calls_made, results_so_far)
    failure_count = len(failure_records)

    # 将失败记录写入 entity
    for fr in failure_records:
        try:
            entity.register_failure(fr)
        except Exception as e:
            logger.warning(f"[SomaticFeedback] register_failure failed: {e}")

    # ---- V5: 连续成功/失败比率 ----
    success_count = 0
    for r in results_so_far:
        if '成功' in r or ('已' in r and '失败' not in r and '错误' not in r):
            success_count += 1
    success_ratio = success_count / max(1, total_calls)  # [0, 1]

    action_type = action.action_type

    # === reach: 敲门 ===
    if action_type == "reach":
        # 连续惩罚：敲门次数 × 0.02
        prev = getattr(entity, "consecutive_reaches_without_response", 0)
        entity.consecutive_reaches_without_response = prev + 1
        penalty = min(0.10, prev * 0.02)
        # 净效果：正向尝试 - 连续惩罚
        entity.adjust("somatic_tone", 0.05 - penalty * 0.8 - failure_count * 0.03)
        entity.adjust("stress", prev * 0.01)

    # === 工具型行动 ===
    is_productive = bool(tools_used)
    if is_productive:
        # 连续反馈：成功越多越正向，失败越多越负向
        tone_delta = success_ratio * 0.06 - (1.0 - success_ratio) * 0.06
        entity.adjust("somatic_tone", tone_delta)

        # stress: 成功降低，失败升高（连续）
        stress_delta = (1.0 - success_ratio) * 0.04 - success_ratio * 0.03
        entity.adjust("stress", stress_delta)

        # unresolved: 成功降低
        entity.adjust("unresolved", -success_ratio * 0.03)

        # boredom: 做了事就降，降幅正比于成功率
        entity.adjust("boredom", -0.06 * max(0.3, success_ratio))

        # energy 消耗
        entity.adjust("energy", -0.005)

        # fatigue: shell 有代价，正比于调用次数
        shell_count = sum(1 for t in tools_used if t in ("shell_run", "shell_bg_run"))
        entity.adjust("fatigue", 0.02 * shell_count + 0.01 * failure_count)

        # info_gap: search/browse 找到就降
        search_count = sum(1 for t in tools_used if t == "web_search")
        browse_count = sum(1 for t in tools_used if t.startswith("browser_"))
        entity.adjust("info_gap", -search_count * 0.15 * success_ratio - browse_count * 0.10 * success_ratio)

    elif action_type in ("voice", "silence"):
        entity.adjust("boredom", 0.01)

    # clamp 保护
    entity.energy = max(0.0, min(1.0, entity.energy))
    entity.stress = max(0.0, min(1.0, entity.stress))
    entity.somatic_tone = max(-1.0, min(1.0, entity.somatic_tone))
    entity.fatigue = max(0.0, min(1.0, entity.fatigue))
    entity.boredom = max(0.0, min(1.0, entity.boredom))
    entity.info_gap = max(0.0, min(1.0, entity.info_gap))
    entity.unresolved = max(0.0, min(1.0, entity.unresolved))

    # ---- V4: 修复成功 → 解决 pending_failure + 世界模型学习 ----
    _attempt_failure_resolution(entity, action_type, calls_made, results_so_far, failure_records)

    # ---- v11.6: 能力缺口检测 + 工具合成触发 ----
    _trigger_capability_gap_analysis(entity, failure_records)

    logger.debug(
        f"[SomaticFeedback] type={action_type} tools={tools_used} "
        f"failures={len(failure_records)} "
        f"→ energy={entity.energy:.3f} stress={entity.stress:.3f} "
        f"somatic_tone={entity.somatic_tone:.3f} fatigue={entity.fatigue:.3f} "
        f"boredom={entity.boredom:.3f} info_gap={entity.info_gap:.3f} "
        f"unresolved={entity.unresolved:.3f} pending_failures={len(entity.pending_failures)}"
    )



# ============================================================================
# v11.6: 能力缺口检测 + 工具合成
# ============================================================================

def _trigger_capability_gap_analysis(
    entity,
    failure_records: list,
) -> None:
    """
    被动触发：每次工具执行失败后，检测能力缺口并触发合成。

    数据流：
        失败记录 → intent_analyzer 提取意图
                          → capability_gap_detector 检测缺口
                                   → 缺口信号写入 entity._pending_tool_gaps
                                   → entity.curiosity / unresolved 微调
                                   → 供 pipeline 后续步骤使用
    """
    if not failure_records:
        return

    try:
        from ..tool_introspection import get_gap_detector, get_intent_analyzer
        gap_detector = get_gap_detector()
        intent_analyzer = get_intent_analyzer()
    except Exception as e:
        logger.debug(f"[CapabilityGap] Module unavailable: {e}")
        return

    entity_tick = getattr(entity, "tick", 0)
    unresolved = getattr(entity, "unresolved", 0.5)

    for fr in failure_records:
        try:
            # 1. 提取意图
            if isinstance(fr, dict):
                raw_record = fr
            else:
                raw_record = {
                    "tool_name": getattr(fr, "tool_name", ""),
                    "error_type": getattr(fr, "error_type", ""),
                    "error_message": getattr(fr, "error_message", ""),
                    "command_or_input": getattr(fr, "command_or_input", ""),
                }
            capture = intent_analyzer.extract_from_failure(raw_record)

            # 2. 检测缺口
            gap = gap_detector.detect_gap(
                intent=capture.intended_action or raw_record.get("tool_name", "未知操作"),
                context={
                    "error_type": raw_record.get("error_type", ""),
                    "error_message": raw_record.get("error_message", ""),
                },
                unresolved_intensity=unresolved,
            )

            # 3. 缺口信号写入 entity（供 pipeline 后续使用）
            pending_gaps = getattr(entity, "_pending_tool_gaps", [])
            if not isinstance(pending_gaps, list):
                pending_gaps = []
            pending_gaps.append(gap.to_dict())
            entity._pending_tool_gaps = pending_gaps

            # 4. 缺口触发 somatic 信号（让她"感受到"自己缺了什么）
            if gap.gap_intensity > 0.3:
                entity.adjust("curiosity", gap.gap_intensity * 0.05)
                entity.adjust("unresolved", gap.gap_intensity * 0.03)

            logger.debug(
                f"[CapabilityGap] intent='{capture.intended_action}' "
                f"gap={gap.gap_intensity:.3f} missing={gap.unmatched_aspects}"
            )

        except Exception as e:
            logger.debug(f"[CapabilityGap] Per-failure analysis error: {e}")


# ============================================================================
# V4: 修复成功 → 解决失败 + 注入世界模型规则
# ============================================================================

def _attempt_failure_resolution(
    entity,
    action_type: str,
    calls_made: list[tuple[str, dict]],
    results_so_far: list[str],
    failure_records: list,
) -> None:
    """
    检查工具执行是否解决了挂起的失败。

    匹配逻辑（纯规则）：
        - shell_run 成功 + 命令包含 "pip install" → 匹配 ModuleNotFoundError
        - shell_run 成功 + 命令包含 "apt" → 匹配 DependencyError
        - 通用：任何成功执行的命令，如果它的错误类型匹配某个 pending failure

    解决后：
        1. 调用 entity.resolve_failure() → somatic 恢复
        2. 提取修复经验 → 注入世界模型规则 → 她下次知道怎么修
    """
    if not calls_made or not entity.has_pending_failures():
        return

    # 收集成功的工具调用
    successful_commands = []
    for (tool_name, args), result_str in zip(calls_made, results_so_far):
        is_failure = any(x in result_str for x in ["[错误", "[失败", "[执行失败", "[命令超时", "[搜索出错", "[搜索失败"])
        if not is_failure and tool_name == "shell_run":
            cmd = args.get("command", "")
            successful_commands.append(cmd)

    if not successful_commands:
        return

    # 遍历 pending failures，找匹配的修复
    resolved_indices = []
    for i, fr in enumerate(entity.pending_failures):
        error_type = getattr(fr, "error_type", "") if not isinstance(fr, dict) else fr.get("error_type", "")
        command_or_input = getattr(fr, "command_or_input", "") if not isinstance(fr, dict) else fr.get("command_or_input", "")

        matched_cmd = _match_fix_command(error_type, command_or_input, successful_commands)
        if matched_cmd:
            # 更新 FailureRecord 的修复信息
            if not isinstance(fr, dict):
                fr.attempted_fix = matched_cmd
                fr.fix_result = "success"
            else:
                fr["attempted_fix"] = matched_cmd
                fr["fix_result"] = "success"

            # 解决
            entity.resolve_failure(i, fix_success=True)
            resolved_indices.append((i, fr, matched_cmd, error_type))

            logger.info(
                f"[FailureResolution] Resolved {error_type}: "
                f"'{command_or_input[:60]}' → '{matched_cmd[:60]}'"
            )

    # 注入世界模型规则
    for _, fr, matched_cmd, error_type in resolved_indices:
        _inject_fix_rule(entity, error_type, matched_cmd)


def _match_fix_command(
    error_type: str,
    original_input: str,
    successful_commands: list[str],
) -> str:
    """
    判断成功的命令是否匹配失败类型。

    返回匹配的命令，无匹配返回空字符串。
    """
    for cmd in successful_commands:
        cmd_lower = cmd.lower()
        if error_type == "ModuleNotFoundError":
            if "pip install" in cmd_lower or "pip3 install" in cmd_lower:
                return cmd
        elif error_type == "DependencyError":
            if "apt" in cmd_lower or "pip install" in cmd_lower:
                return cmd
        elif error_type == "NotFound":
            if "install" in cmd_lower or "which" in cmd_lower:
                return cmd
        elif error_type == "ConnectionError":
            if "ping" in cmd_lower or "curl" in cmd_lower or "--retry" in cmd_lower:
                return cmd
        elif error_type == "PermissionDenied":
            if "chmod" in cmd_lower or "sudo" in cmd_lower:
                return cmd
        elif error_type == "SyntaxError":
            if "python" in cmd_lower or "py_compile" in cmd_lower:
                return cmd
        elif error_type == "Timeout":
            pass  # 超时没有命令能修
    return ""


def _inject_fix_rule(
    entity,
    error_type: str,
    fix_command: str,
) -> None:
    """
    将修复经验注入世界模型规则。

    格式兼容 wm_rules，后续 induct/merge/decay/verify 都可处理。
    confidence=0.7 起始，后续成功修复会通过 merge 提升。
    """
    import time as _time

    rule = {
        "id": f"fix_{error_type}_{int(_time.time())}",
        "content": f"当遇到 {error_type} 时，运行 '{fix_command[:80]}' 可以修复",
        "confidence": 0.70,
        "source_experience_count": 1,
        "stability_score": 0.5,
        "stability_band": 0.1,
        "created_at": _time.time(),
        "last_verified_at": _time.time(),
        "last_decay_at": _time.time(),
        "status": "active",
        "context": f"tool:{error_type}",
        "predicts": {
            "trigger": f"error_{error_type}",
            "expect": f"resolved_by_{fix_command[:30].replace(' ', '_')}",
        },
        "evidence": [],
        "_debug_meta": {
            "source": "executor.failure_resolution",
            "fix_command": fix_command[:200],
        },
    }

    # 去重：已存在相同 trigger+expect 的规则则合并（提升 confidence）
    for existing in entity.wm_rules:
        if isinstance(existing, dict):
            existing_p = existing.get("predicts", {})
            if (existing_p.get("trigger") == rule["predicts"]["trigger"]
                    and existing_p.get("expect") == rule["predicts"]["expect"]):
                existing["confidence"] = min(1.0, existing.get("confidence", 0.5) + 0.10)
                existing["source_experience_count"] = existing.get("source_experience_count", 1) + 1
                existing["last_verified_at"] = _time.time()
                logger.info(
                    f"[FailureResolution] Rule merged: {error_type} "
                    f"confidence={existing['confidence']:.2f}"
                )
                return

    entity.wm_rules.append(rule)
    logger.info(
        f"[FailureResolution] Rule injected: {error_type} → "
        f"'{fix_command[:60]}' (confidence=0.70)"
    )


def _parse_and_execute(
    llm_response: str,
    entity,
    tool_calls_made: list[tuple[str, dict]] | None = None,
    tool_results: list[str] | None = None,
) -> tuple[XIAction, str]:
    """
    解析她的意图并返回 action。

    工具调用检测：
        file_read/write/list   → write（她创建/修改了文件）
        shell_run/bg_run       → run（她执行了命令）
        browser_*              → browse（她看了网页）
        web_search             → search（她搜索了）
        REACH:                 → reach（她想敲门）
        无工具                 → voice（她只是写了文字）
    """

    if not llm_response:
        action = XIAction(
            action_type="voice",
            reason="triggered but no response",
            intensity=max(entity.loneliness, entity.boredom, entity.stress),
            tick=entity.tick,
            context={"loneliness": entity.loneliness, "boredom": entity.boredom},
        )
        return action, ""

    tool_calls_made = tool_calls_made or []
    tool_results = tool_results or []
    tools_used = {t[0] for t in tool_calls_made}

    content = llm_response.strip()

    # ---- 判断 action_type ----
    # 优先看工具使用
    has_write = any(t in tools_used for t in {"file_write", "file_read", "file_list"})
    has_run = any(t in tools_used for t in {"shell_run", "shell_bg_run"})
    has_browse = any(t in tools_used for t in {
        "browser_open", "browser_navigate", "browser_screenshot",
        "browser_click", "browser_fill", "browser_get_text",
    })
    has_search = "web_search" in tools_used

    # REACH 标记检测
    has_reach = False
    reach_content = ""
    lines = llm_response.strip().split("\n")
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.upper().startswith("REACH:"):
            reach_content = stripped[len("REACH:"):].strip()
            rest = "\n".join(lines[i + 1:]).strip()
            if rest:
                reach_content += "\n" + rest
            has_reach = True
            break
        if "REACH:" in stripped.upper():
            idx = stripped.upper().index("REACH:")
            reach_content = stripped[idx + len("REACH:"):].strip()
            rest = "\n".join(lines[i + 1:]).strip()
            if rest:
                reach_content += "\n" + rest
            has_reach = True
            break

    # 分类
    if has_reach and reach_content:
        action_type = "reach"
        content = reach_content
    elif has_run:
        action_type = "run"
    elif has_browse:
        action_type = "browse"
    elif has_write:
        action_type = "write"
    elif has_search:
        action_type = "search"
    elif len(tools_used) > 1:
        action_type = "mixed"
    else:
        action_type = "voice"

    # ---- 构建 XIAction ----
    tool_summary = f" [{', '.join(sorted(tools_used))}]" if tools_used else ""
    first_line = content.strip().split("\n")[0][:60]
    action = XIAction(
        action_type=action_type,
        reason=f"triggered: {first_line}{tool_summary}",
        intensity=max(entity.loneliness, entity.boredom, entity.stress),
        tick=entity.tick,
        context={
            "loneliness": entity.loneliness,
            "boredom": entity.boredom,
            "stress": entity.stress,
            "somatic_tone": entity.somatic_tone,
            "tools_used": list(tools_used),
        },
        payload={
            "content_preview": content[:100],
            "tool_results_count": len(tool_results),
        },
    )

    return action, content.strip()


def _write_voice_file(content: str, entity) -> None:
    """把她的内容写入声音文件（沉默写作模式）"""
    import uuid

    ts = int(time.time())
    uid = uuid.uuid4().hex[:8]
    filename = f"{ts}_{uid}.txt"
    filepath = VOICE_DIR / filename

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info(f"[ActionExecutor] XIA wrote (voice): {filepath}")
    except Exception as e:
        logger.error(f"[ActionExecutor] Failed to write voice file: {e}")


def _write_manifest(action: XIAction, content: str, tool_results: list[str] | None = None) -> None:
    """将行动写入 manifest.jsonl（追加），并写治理审计日志"""

    try:
        record = action.to_dict()
        record["content"] = content
        if tool_results:
            record["tool_results"] = tool_results
        with open(MANIFEST_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        # 写治理审计日志（所有 agent 行为都在此记录）
        _write_governance_audit(action, tool_results or [])

    except Exception as e:
        logger.error(f"[ActionExecutor] Failed to write manifest: {e}")


def _write_governance_audit(action: XIAction, tool_results: list[str]) -> None:
    """写治理审计日志 logs/governance_audit.jsonl"""
    import logging as _logging

    _logging.getLogger(__name__)
    audit_dir = Path(__file__).parent.parent.parent.parent / "logs"
    audit_dir.mkdir(exist_ok=True)
    audit_file = audit_dir / "governance_audit.jsonl"

    tools_used = action.context.get("tools_used", [])
    if not tools_used:
        return  # 没有工具调用的行为不记 agent 审计

    record = {
        "timestamp": action.timestamp,
        "tick": action.tick,
        "action_type": action.action_type,
        "reason": action.reason,
        "intensity": action.intensity,
        "loneliness": action.context.get("loneliness", 0.0),
        "tools_used": tools_used,
        "tool_results_count": len(tool_results),
        "content_preview": (action.payload.get("content_preview") or "")[:200],
    }

    try:
        with open(audit_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.error(f"[ActionExecutor] governance audit write failed: {e}")
