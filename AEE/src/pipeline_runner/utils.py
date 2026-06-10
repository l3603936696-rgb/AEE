"""Pipeline utilities — standalone functions extracted from pipeline_runner."""

import logging
import math
import time
from typing import Any, Dict, List, Optional

from ..parameter_system.access import get_param
from ..parameter_system.snapshot import ParameterSnapshot

logger = logging.getLogger(__name__)


# ============================================================================
# 状态驱动触发检查（供裁决层调用）
# ============================================================================

def should_trigger_sleep(fatigue: float, stress: float) -> bool:
    """
    睡眠触发条件检查。

    状态驱动：fatigue 或 stress 超过阈值时，触发睡眠信号。
    此函数本身不触发睡眠，仅返回布尔值供裁决层参考。
    """
    return fatigue > 0.9 or stress > 0.85


# ============================================================================
# V6: 行为规则学习
# ============================================================================

def _update_behavior_rules(entity, decision: dict) -> None:
    """
    管线结束时，从本轮 snapshot 更新行为规则。

    只记录有实际效果的动作（至少一个维度变化 > 0.01）。
    失败静默跳过。
    """
    try:
        from AEE.src.core.behavior_vector import update_rules_from_snapshot
        snaps = getattr(entity, "snapshots", [])
        if len(snaps) < 2:
            return
        action_type = decision.get("action_type", "")
        if not action_type:
            return
        pre = snaps[-2]
        post = snaps[-1]

        # 内生筛选：只记她当前在乎的变化
        # relevance = Σ |delta[dim]| × drive_pressure[dim]
        # loneliness 高时 loneliness 的小变化也值得记
        # loneliness 低时再大的变化也是噪音
        drive_weights = {
            "energy":       max(0.0, 1.0 - entity.energy),
            "loneliness":   entity.loneliness,
            "fatigue":      entity.fatigue,
            "info_gap":     entity.info_gap,
            "unresolved":   entity.unresolved,
            "somatic_tone": abs(entity.somatic_tone),
            "danger_level": getattr(entity, "danger_level", 0.0),
            "approach_drive": getattr(entity, "approach_drive", 0.0),
            "avoid_drive":  getattr(entity, "avoid_drive", 0.0),
        }
        relevance = 0.0
        for k in pre:
            if k in post and k in drive_weights:
                delta = abs(float(post.get(k, 0)) - float(pre.get(k, 0)))
                relevance += delta * drive_weights[k]
        if relevance < 0.005:  # 加权总变化太小 → 不值得记
            return

        snap = {
            "action_type": action_type,
            "pre_state": dict(pre),
            "post_state": dict(post),
        }
        update_rules_from_snapshot(entity, snap, entity.tick)
    except Exception:
        pass


# ============================================================================
# 经验质量：快照多样性计算
# ============================================================================

def _compute_snapshot_diversity(snaps: list) -> float:
    """
    计算快照集合的多样性（状态变化向量夹角余弦）。

    快照多样性低（CV 低）→ 各轮状态变化模式相似 → 学习价值低 → 跳过归纳。
    多样性高 → 状态变化模式丰富 → 学习价值高 → 执行归纳。

    返回：
        float — 快照间平均余弦距离（0=完全相同, 1=完全不相关）。
        snapshots 不足 2 个时返回 1.0（允许学习）。
    """
    if not snaps or len(snaps) < 2:
        return 1.0

    def _to_vec(snap) -> dict:
        if hasattr(snap, "pre_state") and hasattr(snap, "post_state"):
            pre = getattr(snap, "pre_state", {})
            post = getattr(snap, "post_state", {})
        elif isinstance(snap, dict):
            pre = snap.get("pre_state", {})
            post = snap.get("post_state", {})
        else:
            return {}
        all_keys = set(pre.keys()) | set(post.keys())
        return {k: post.get(k, 0.0) - pre.get(k, 0.0) for k in all_keys}

    vecs = [_to_vec(s) for s in snaps]
    valid = [v for v in vecs if v]
    if len(valid) < 2:
        return 1.0

    total_dist = 0.0
    count = 0
    for i in range(len(valid)):
        for j in range(i + 1, len(valid)):
            v1, v2 = valid[i], valid[j]
            all_keys = set(v1.keys()) | set(v2.keys())
            if not all_keys:
                continue
            dot = sum(v1.get(k, 0.0) * v2.get(k, 0.0) for k in all_keys)
            mag1 = math.sqrt(sum(v1.get(k, 0.0) ** 2 for k in all_keys))
            mag2 = math.sqrt(sum(v2.get(k, 0.0) ** 2 for k in all_keys))
            if mag1 > 1e-9 and mag2 > 1e-9:
                cos = dot / (mag1 * mag2)
                # 余弦距离 = 1 - cos，余弦越接近1（相似）距离越小
                total_dist += (1.0 - cos)
                count += 1

    if count == 0:
        return 1.0
    return total_dist / count


# 辅助函数
# ============================================================================

def get_default_drive_params() -> Dict[str, Any]:
    """返回驱动力系统的默认形态表参数"""
    return {
        "info_hunger_time_shape": {
            "x_anchors": [0.0, 0.3, 0.8, 1.0, 2.0, 5.0],
            "y_anchors": [0.0, 0.02, 0.15, 0.60, 0.85, 0.99]
        },
        "social_time_shape": {
            "x_anchors": [0.0, 0.5, 1.0, 2.0, 4.0],
            "y_anchors": [0.0, 0.05, 0.30, 0.70, 0.98]
        },
        "loneliness_shape": {
            "x_anchors": [0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
            "y_anchors": [0.0, 0.01, 0.05, 0.15, 0.45, 1.0]
        },
        "fatigue_shape": {
            "x_anchors": [0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
            "y_anchors": [0.0, 0.02, 0.08, 0.20, 0.50, 1.0]
        },
        "change_shape": {
            "x_anchors": [0.0, 0.25, 0.5, 0.75, 1.0],
            "y_anchors": [0.0, 0.05, 0.20, 0.55, 1.0]
        },
        "debt_shape": {
            "x_anchors": [0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
            "y_anchors": [0.0, 0.01, 0.05, 0.15, 0.40, 1.0]
        },
    }


def _build_decision_params(snapshot: ParameterSnapshot) -> Dict[str, Any]:
    """从参数快照构建裁决系统参数"""
    return {
        "module_weights": {
            "SituationAssessment": get_param(snapshot, "decision.module_weights.SituationAssessment", 1.0),
            "ContextAwareness": get_param(snapshot, "decision.module_weights.ContextAwareness", 1.0),
            "ThoughtIntegration": get_param(snapshot, "decision.module_weights.ThoughtIntegration", 1.0),
            "SignalActivation": get_param(snapshot, "decision.module_weights.SignalActivation", 1.0),
            "MainlineConstraint": get_param(snapshot, "decision.module_weights.MainlineConstraint", 1.0),
            "TemporalPressure": get_param(snapshot, "decision.module_weights.TemporalPressure", 1.0),
            "SelfState": get_param(snapshot, "decision.module_weights.SelfState", 1.0),
            "Preference": get_param(snapshot, "decision.module_weights.Preference", 1.0),
            "WorldModel": get_param(snapshot, "decision.module_weights.WorldModel", 1.0),
        },
        "survival_override_threshold": get_param(snapshot, "decision.survival_override_threshold", 0.85),
        "max_suggestions": get_param(snapshot, "decision.max_suggestions", 2),
        "fallback_priority": get_param(snapshot, "decision.fallback_priority", 0.0),
        "personality": get_param(snapshot, "personality", {
            "introverted_bias": 0.2,
            "extroverted_bias": 0.1,
        }),
        "web_search": {
            "enabled": get_param(snapshot, "web_search.enabled", True),
            "info_hunger_threshold": get_param(snapshot, "web_search.info_hunger_threshold", 0.6),
            "wm_hit_threshold": get_param(snapshot, "web_search.wm_hit_threshold", 0.3),
            "intent_intensity_threshold": get_param(snapshot, "web_search.intent_intensity_threshold", 0.6),
            "max_results": get_param(snapshot, "web_search.max_results", 5),
            "timeout_seconds": get_param(snapshot, "web_search.timeout_seconds", 8.0),
            "backend": get_param(snapshot, "web_search.backend", None),
        },
    }


def _build_output_params(snapshot: ParameterSnapshot) -> Dict[str, Any]:
    """从参数快照构建输出层参数"""
    return {
        "model_name": get_param(snapshot, "llm.model_name", "qwen2.5:3b"),
        "temperature": get_param(snapshot, "llm.temperature", 0.7),
        "max_tokens": int(get_param(snapshot, "llm.max_tokens", 300)),
        "output_llm_timeout_ms": get_param(snapshot, "llm.output_llm_timeout_ms", 90000),
    }


# ============================================================================
# Mock LLM（用于测试，无外部依赖）
# ============================================================================

def mock_llm_callable(
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    max_tokens: int,
    timeout_ms: float,
) -> tuple[Optional[str], Optional[str]]:
    """Mock LLM 调用，用于测试"""
    return "嗯，我听到了。", None


# ============================================================================
# v11.6: 工具缺口感知 + 合成触发
# ============================================================================

def _process_tool_gaps(entity, pending_gaps: list) -> None:
    """
    处理待合成的工具缺口。

    工作流程：
        1. 从 pending_gaps 找到最高强度的缺口
        2. 调用 LLMSynthesizer 合成工具
        3. 合成成功 → 注册到 registry
        4. 写入日志供观察
    """
    if not pending_gaps:
        return

    top_gap = max(pending_gaps, key=lambda g: float(g.get("gap_intensity", 0)))
    gap_intensity = float(top_gap.get("gap_intensity", 0))

    if gap_intensity < 0.4:
        logger.debug(f"[ToolSynthesis] Gap too weak ({gap_intensity:.3f}), skipping")
        return

    intent = top_gap.get("intent", "")
    recent_synth_time = getattr(entity, "_last_tool_synthesis_time", 0.0)
    if time.time() - recent_synth_time < 3600:
        logger.debug("[ToolSynthesis] Skipping: synthesis within last hour")
        return

    recent_failures = []
    for fr in getattr(entity, "pending_failures", [])[-5:]:
        if hasattr(fr, "to_dict"):
            recent_failures.append(fr.to_dict())
        elif isinstance(fr, dict):
            recent_failures.append(fr)

    try:
        from ..tool_synthesizer import synthesize_tool
        result = synthesize_tool(
            intent=intent,
            gap_signal=top_gap,
            failure_history=recent_failures,
            current_tick=getattr(entity, "tick", 0),
        )

        if result.success and result.tool_definition:
            tool_name = result.tool_definition.get("name", "unknown")
            try:
                from ..action_system.agent_tools import registry
                registry.register_tool_definition(result.tool_definition)
                registry.reload_tools()
                entity._last_tool_synthesis_time = time.time()
                logger.info(
                    f"[ToolSynthesis] Registered new tool: {tool_name} "
                    f"(gap={gap_intensity:.3f}, confidence={result.confidence:.3f})"
                )
            except Exception as reg_err:
                logger.warning(f"[ToolSynthesis] Registry failed: {reg_err}")
        else:
            logger.debug(f"[ToolSynthesis] Synthesis failed: {result.error}")

    except Exception as e:
        logger.debug(f"[ToolSynthesis] Unexpected error: {e}")
