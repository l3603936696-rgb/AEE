"""意图编码器 (Intent Encoder)

接收裁决系统输出的 decision（含 action_type、target、priority、payload），
将其翻译为生成层能直接消费的 intent_repr（语气、目标、约束）。

纯翻译层，不做决策、不调用LLM、不修改输入。
硬约束：
  - 纯函数，不读取记忆、世界模型
  - 不调用LLM
  - 任何输入字段缺失或失败，返回默认意图
  - 所有权重和阈值必须从 params 读取，不得硬编码
"""

import random
from typing import Any

# 默认意图（用于任何输入字段缺失或失败时的兜底）
DEFAULT_INTENT_REPR: dict[str, Any] = {
    "tone": "neutral",
    "goal": "share",
    "constraints": {
        "length": "tiny",
        "must_not": ["分析", "展开", "你觉得呢", "你怎么看"],
        "reflect_state": False,
    },
}

# action_type → 可选 tone 列表（energy >= threshold 时生效）
_TONE_OPTIONS: dict[str, list[str]] = {
    "seek": ["empathetic", "curious", "supportive"],
    "avoid": ["cautious", "neutral"],
    "comfort": ["neutral"],
}

# action_type → 可选 goal 列表
_GOAL_OPTIONS: dict[str, list[str]] = {
    "seek": ["clarify", "propose"],
    "avoid": ["answer"],
    "comfort": ["share"],
}

# priority > threshold 时可选 length
_LENGTH_HIGH_PRIORITY = ["short", "medium"]
# priority <= threshold 时可选 length
_LENGTH_LOW_PRIORITY = ["tiny", "short"]

# 固定 must_not 列表
_DEFAULT_MUST_NOT = ["分析", "展开", "你觉得呢", "你怎么看"]


def _safe_choice(seq: list[str]) -> str:
    """从序列中随机选择一个元素，序列非空有保证时使用。"""
    return random.choice(seq)


def _get_param(params: dict[str, Any], key: str, default: float) -> float:
    """从 params 中安全读取数值参数，支持嵌套字段（如 a.b）。"""
    if not isinstance(params, dict):
        return default
    keys = key.split(".")
    value = params
    for k in keys:
        if isinstance(value, dict):
            value = value.get(k)
        else:
            return default
    if isinstance(value, (int, float)):
        return float(value)
    return default


def _resolve_action(decision: Any) -> str | None:
    """从 decision 中安全解析 action_type。"""
    if not isinstance(decision, dict):
        return None
    return decision.get("action_type")


def _resolve_priority(decision: Any) -> float:
    """从 decision 中安全解析 priority，缺失时返回 0.0。"""
    if not isinstance(decision, dict):
        return 0.0
    val = decision.get("priority")
    if isinstance(val, (int, float)):
        return float(val)
    return 0.0


def _resolve_energy(state_snapshot: Any) -> float:
    """从 state_snapshot 中安全解析 energy，缺失时返回 0.5（正常能量）。"""
    if not isinstance(state_snapshot, dict):
        return 0.5
    val = state_snapshot.get("energy")
    if isinstance(val, (int, float)):
        return max(0.0, min(1.0, float(val)))
    return 0.5


def _determine_tone(
    action: str | None,
    energy: float,
    params: dict[str, Any],
) -> str:
    """根据 action_type、energy 和 params 确定语气 tone。"""
    low_energy_threshold = _get_param(params, "intent_encoder.low_energy_threshold", 0.3)

    if energy < low_energy_threshold:
        return "neutral"

    if action is None:
        return "neutral"

    options = _TONE_OPTIONS.get(action)
    if not options:
        return "neutral"

    return _safe_choice(options)


def _determine_goal(action: str | None) -> str:
    """根据 action_type 确定目标 goal。"""
    if action is None:
        return "share"

    options = _GOAL_OPTIONS.get(action)
    if not options:
        return "share"

    return _safe_choice(options)


def _determine_length(
    priority: float,
    params: dict[str, Any],
) -> str:
    """根据 priority 和 params 确定长度约束 length。"""
    high_priority_threshold = _get_param(params, "intent_encoder.high_priority_threshold", 0.8)

    if priority > high_priority_threshold:
        return _safe_choice(_LENGTH_HIGH_PRIORITY)
    return _safe_choice(_LENGTH_LOW_PRIORITY)


def encode_intent(
    decision: dict[str, Any],
    state_snapshot: dict[str, Any],
    params: dict[str, Any],
) -> dict[str, Any]:
    """意图编码主函数。

    将裁决系统的 decision 翻译为生成层可消费的 intent_repr。

    参数:
        decision: 裁决系统输出，包含 action_type、target、priority、
                  payload.reason、payload.context_id。
        state_snapshot: 当前实体状态快照，用于动态调整语气。
        params: 意图编码器参数表（含 low_energy_threshold、high_priority_threshold）。

    返回:
        intent_repr: {
            "tone": "empathetic/neutral/curious/cautious/supportive",
            "goal": "clarify/answer/propose/share",
            "constraints": {
                "length": "tiny/short/medium/long",
                "must_not": ["分析", "展开", "你觉得呢", "你怎么看"],
                "reflect_state": bool
            }
        }

    硬约束:
        - 纯函数，不读取记忆、世界模型
        - 不调用LLM
        - 任何输入字段缺失或失败，返回默认意图
        - 所有权重和阈值必须从 params 读取，不得硬编码
    """
    try:
        action = _resolve_action(decision)
        priority = _resolve_priority(decision)
        energy = _resolve_energy(state_snapshot)

        tone = _determine_tone(action, energy, params)
        goal = _determine_goal(action)
        length = _determine_length(priority, params)

        low_energy_threshold = _get_param(params, "intent_encoder.low_energy_threshold", 0.3)

        return {
            "tone": tone,
            "goal": goal,
            "constraints": {
                "length": length,
                "must_not": _DEFAULT_MUST_NOT.copy(),
                "reflect_state": energy < low_energy_threshold,
            },
        }
    except Exception:
        return DEFAULT_INTENT_REPR.copy()
