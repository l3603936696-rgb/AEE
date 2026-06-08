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

from .types import XIAction
from . import tools
from . import reach
from . import agent_tools
from .executor_feedback import _apply_somatic_feedback
from .executor_prompts import (
    _build_failure_context,
    _build_hermes_routing_notice,
    _build_reach_notice,
    _build_state_description,
    _build_tool_notice,
    _call_llm,
)

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
            from ..observability import create_wrapped_llm
            llm_callable = create_wrapped_llm("executor")

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
