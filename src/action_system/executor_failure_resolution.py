"""Failure resolution and capability-gap helpers for action execution."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)
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
