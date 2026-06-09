"""
BehaviorPatterns Schema — 数据结构与常量。

提取自 behavior_patterns.py（dataclass + schema 常量 + schema helpers）。
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ============================================================================
# 数据路径
# ============================================================================

PROJECT_ROOT = Path(__file__).parents[2]
PATTERNS_FILE = PROJECT_ROOT / "data" / "behavior_patterns.json"


# ============================================================================
# Schema 常量
# ============================================================================

PRIMITIVE_ACTIONS = [
    "chat",
    "web_search",
    "explore",
    "seek",
    "rest",
    "idle",
    "avoid",
    "repair",
]

ACTION_TO_TYPE: Dict[str, str] = {
    "chat": "explore",
    "web_search": "explore",
    "explore": "explore",
    "seek": "seek",
    "rest": "rest",
    "idle": "rest",
    "avoid": "avoid",
    "repair": "avoid",
}

INTENT_RULES: List[Tuple[str, str, float]] = [
    ("找", "topic_discovery", 0.8),
    ("话题", "topic_discovery", 0.7),
    ("问", "question_ask", 0.9),
    ("怎么", "question_ask", 0.8),
    ("为什么", "question_ask", 0.9),
    ("帮", "seek_connection", 0.8),
    ("谢谢", "seek_connection", 0.7),
    ("你好", "seek_connection", 0.6),
    ("好", "affirmation", 0.5),
    ("嗯", "affirmation", 0.4),
    ("不行", "rejection", 0.6),
    ("不对", "rejection", 0.6),
]

INTENT_TO_DRIVE: Dict[str, str] = {
    "topic_discovery": "curiosity",
    "question_ask": "info_hunger",
    "seek_connection": "loneliness_drive",
    "affirmation": "approach_social",
    "rejection": "avoid_drive",
    "kill_time": "boredom_relief",
    "explore_topic": "curiosity",
}


# ============================================================================
# Schema helpers
# ============================================================================

def _band(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _make_context_signature(state: Dict[str, float]) -> str:
    """生成情境签名（用于 WMDB key）"""
    keys = ["boredom", "loneliness", "energy", "fatigue", "info_gap"]
    sig = []
    for k in keys:
        v = state.get(k, 0.5)
        if v < 0.3:
            sig.append(f"{k}_L")
        elif v > 0.7:
            sig.append(f"{k}_H")
    return "|".join(sig) or "neutral"


def _make_wm_key(action: str, state: Dict[str, float]) -> str:
    ctx = _make_context_signature(state)
    return f"{action}@{ctx}"


def _classify_intent(content: str, reason: str = "") -> str:
    """根据 content/reason 内容分类 intent_tag"""
    text = f"{content} {reason}"
    best_score = 0.0
    best_intent = "unknown"
    for keyword, intent, weight in INTENT_RULES:
        if keyword in text:
            if weight > best_score:
                best_score = weight
                best_intent = intent
    return best_intent


# ============================================================================
# BehaviorPattern dataclass
# ============================================================================


@dataclass
class BehaviorPattern:
    """
    可进化的组合行为模式 v2。

    新增字段：
        intent_tag         : 行为语义标签（为什么这么做）
        short_term_reward  : 即时收益
        long_term_effect   : 长期效果（tick 后的状态变化）
        long_term_tracked  : 是否在追踪长期效果
        last_state_snapshot: 上次执行时的状态快照（用于长期效果计算）
    """
    actions: List[str]
    intent_tag: str = "unknown"
    weight: float = -0.2
    usage: int = 0
    success: int = 0
    avg_reward: float = 0.0
    avg_pred_err: float = 1.0
    short_term_reward: float = 0.0
    long_term_effect: float = 0.0
    long_term_tracked: bool = False
    last_state_snapshot: Optional[Dict[str, float]] = None
    created_at: float = field(default_factory=time.time)
    last_used_at: float = field(default_factory=time.time)
    pattern_id: str = field(default_factory=lambda: f"bp_{random.randint(10_000, 99_999)}")

    @property
    def success_rate(self) -> float:
        if self.usage == 0:
            return 0.0
        return self.success / self.usage

    @property
    def is_failed(self) -> bool:
        return self.weight < -0.5 and self.usage > 5

    def to_dict(self) -> Dict[str, Any]:
        return {
            "actions": self.actions,
            "intent_tag": self.intent_tag,
            "weight": self.weight,
            "usage": self.usage,
            "success": self.success,
            "avg_reward": self.avg_reward,
            "avg_pred_err": self.avg_pred_err,
            "short_term_reward": self.short_term_reward,
            "long_term_effect": self.long_term_effect,
            "created_at": self.created_at,
            "last_used_at": self.last_used_at,
            "pattern_id": self.pattern_id,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "BehaviorPattern":
        return cls(
            actions=d["actions"],
            intent_tag=d.get("intent_tag", "unknown"),
            weight=d.get("weight", -0.2),
            usage=d.get("usage", 0),
            success=d.get("success", 0),
            avg_reward=d.get("avg_reward", 0.0),
            avg_pred_err=d.get("avg_pred_err", 1.0),
            short_term_reward=d.get("short_term_reward", 0.0),
            long_term_effect=d.get("long_term_effect", 0.0),
            created_at=d.get("created_at", time.time()),
            last_used_at=d.get("last_used_at", time.time()),
            pattern_id=d.get("pattern_id", f"bp_{random.randint(10_000, 99_999)}"),
        )


# ============================================================================
# update_long_term_bias — 独立函数（不在 PatternPool 内）
# ============================================================================


def update_long_term_bias(
    entity_state: Any,
    pattern_or_intent: Any,
    pre_state: Dict[str, float],
    post_state: Dict[str, float],
    action_result: Dict[str, Any],
) -> Dict[str, float]:
    """
    根据行为执行效果更新实体的长时偏置（v4 — identity signal + unresolved source）。
    """
    intent = (
        pattern_or_intent.intent_tag
        if hasattr(pattern_or_intent, "intent_tag")
        else str(pattern_or_intent) if pattern_or_intent else "unknown"
    )
    drive = INTENT_TO_DRIVE.get(intent, "explore")

    delayed_effect = float(action_result.get("long_term_effect", 0.0))
    short_term_delta = (
        (pre_state.get("boredom", 0.3) - post_state.get("boredom", 0.3)) * 0.6
        + (pre_state.get("loneliness", 0.3) - post_state.get("loneliness", 0.3)) * 0.4
    )
    effect = 0.9 * delayed_effect + 0.1 * short_term_delta

    prev_unresolved = pre_state.get("unresolved", 0.2)
    curr_unresolved = post_state.get("unresolved", 0.2)
    unresolved_progress = prev_unresolved - curr_unresolved
    unresolved_src = str(action_result.get("unresolved_source", "external"))
    if unresolved_src == "self_generated":
        unresolved_progress *= 0.2
    else:
        unresolved_progress *= 1.0

    identity_sig = float(action_result.get("identity_signal", 0.5))
    identity_modulator = 0.5 + 1.0 * identity_sig

    success = action_result.get("success", False)
    pred_err = float(action_result.get("prediction_error", 0.5))
    error_type = str(action_result.get("error_type", "none"))

    delta = identity_modulator * (0.08 * effect + 0.03 * unresolved_progress)

    if error_type == "execution":
        delta -= 0.03
    elif error_type == "strategy":
        delta -= 0.10
    else:
        delta -= 0.08 * pred_err

    if not success:
        delta -= 0.05
    elif success:
        delta += 0.02

    info = {}
    if hasattr(entity_state, "long_term_bias") and drive in entity_state.long_term_bias:
        current = entity_state.long_term_bias[drive]
        new_val = max(-1.0, min(1.0, current + delta))
        entity_state.long_term_bias[drive] = new_val
        info = {
            "intent": intent, "drive": drive,
            "effect": round(effect, 3),
            "unresolved_progress": round(unresolved_progress, 3),
            "unresolved_source": unresolved_src,
            "identity_signal": round(identity_sig, 3),
            "identity_modulator": round(identity_modulator, 3),
            "error_type": error_type,
            "pred_err": round(pred_err, 3),
            "success": success,
            "delta": round(delta, 4),
            "bias_before": round(current, 4),
            "bias_after": round(new_val, 4),
        }
    return info
