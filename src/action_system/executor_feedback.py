"""Somatic feedback and tool-failure analysis for action execution."""

from __future__ import annotations

import logging

from .types import FailureRecord, classify_error, estimate_severity
from .executor_failure_resolution import (
    _attempt_failure_resolution,
    _trigger_capability_gap_analysis,
)

logger = logging.getLogger(__name__)
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
