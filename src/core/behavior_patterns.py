"""
BehaviorPattern — 经验驱动的行为进化模块 v2

修复了四个关键问题：

1. WMDB 升级到 situation-level（不只是 action-level）
   key = (action_type, context_signature)，区分"什么情境下有效"

2. BehaviorPattern 加 intent_tag（行为语义标签）
   区分"为什么这么做"——search[找话题] vs search[求助] 不同

3. 加 long_term_effect（延时状态差分）
   区分短期效果和长期效果

4. 加 satisfaction + suppress（终止条件）
   防止"找话题循环"——满足了就停

设计原则：
    - 决策 100% 在系统，LLM 不参与
    - world_model 只做预测评分，不生成行为
    - 所有状态变化透明可追溯
"""

from __future__ import annotations

import json
import logging
import random
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ============================================================================
# 路径常量
# ============================================================================

PATTERNS_FILE = Path(__file__).parent.parent.parent / "data" / "behavior_patterns.json"
PATTERNS_FILE.parent.mkdir(parents=True, exist_ok=True)

# ============================================================================
# 原子动作定义
# ============================================================================

PRIMITIVE_ACTIONS: List[str] = [
    "web_search", "file_write", "file_read", "file_list",
    "browser_open", "browser_screenshot", "shell_run",
]

ACTION_TO_TYPE: Dict[str, str] = {
    "web_search":            "explore",
    "file_write":            "explore",
    "file_read":             "explore",
    "file_list":             "explore",
    "browser_open":          "explore",
    "browser_screenshot":    "explore",
    "shell_run":             "explore",
}

# ============================================================================
# 工具函数：context_signature（WMDB situation-level key）
# ============================================================================


def _make_context_signature(state: Dict[str, float]) -> str:
    """
    从状态快照提取 context_signature，用于区分"什么情境"。

    用离散化 + 组合方式，不用 embedding，不依赖 LLM。
    格式：level_描述
    """
    boredom = _band(state.get("boredom", 0.3), "b")
    loneliness = _band(state.get("loneliness", 0.3), "l")
    fatigue = _band(state.get("fatigue", 0.1), "f")
    energy = _band(state.get("energy", 0.7), "e")
    unresolved = _band(state.get("unresolved", 0.2), "u")
    curiosity = _band(state.get("curiosity", state.get("info_gap", 0.3)), "c")
    social_time = _band(state.get("time_since_last_social", 0.0) / 300, "s")  # 5min 为单位
    info_time = _band(state.get("time_since_last_info", 0.0) / 120, "i")      # 2min 为单位

    return f"{boredom}{loneliness}{fatigue}{energy}{unresolved}{curiosity}{social_time}{info_time}"


def _band(value: float, prefix: str) -> str:
    """将连续值离散化为低/中/高三档"""
    if value < 0.33:
        return f"{prefix}0"
    elif value < 0.66:
        return f"{prefix}1"
    else:
        return f"{prefix}2"


def _make_wm_key(action: str, state: Dict[str, float]) -> str:
    """生成 situation-level WM key"""
    sig = _make_context_signature(state)
    return f"{action}@{sig}"


# ============================================================================
# 工具函数：intent_tag（规则分类，不用 LLM）
# ============================================================================


INTENT_RULES: List[Tuple[List[str], str]] = [
    # (content 关键词, intent_tag)
    (["新闻", "最新", "最近", "发生了什么", "头条"], "explore_topic"),
    (["展览", "艺术", "音乐", "电影", "有趣"], "explore_topic"),
    (["孤独", "寂寞", "找人", "陪伴", "想聊天", "REACH"], "seek_connection"),
    (["问题", "解决", "怎么办", "如何", "疑问"], "solve_problem"),
    (["记录", "写", "笔记", "写下来", "备忘"], "express"),
    (["无聊", "没事做", "打发", "玩"], "kill_time"),
    (["担心", "害怕", "焦虑", "紧张", "压力"], "seek_comfort"),
]


def _classify_intent(content: str, reason: str = "") -> str:
    """
    规则分类：从 action_result.content 推断 intent_tag。

    不依赖 LLM，只做关键词匹配。
    """
    text = (content + " " + reason).lower()
    for keywords, intent in INTENT_RULES:
        if any(kw in text for kw in keywords):
            return intent
    return "unknown"


# intent_tag → 长时偏置驱动
INTENT_TO_DRIVE: Dict[str, str] = {
    "explore_topic":   "explore",
    "seek_connection":"connect",
    "solve_problem":  "build",
    "express":        "introspect",
    "kill_time":      "explore",
    "seek_comfort":   "connect",
    "unknown":        "explore",   # 默认向探索偏移
}


def update_long_term_bias(
    entity_state: Any,
    pattern_or_intent: Any,
    pre_state: Dict[str, float],
    post_state: Dict[str, float],
    action_result: Dict[str, Any],
) -> Dict[str, float]:
    """
    根据行为执行效果更新实体的长时偏置（v4 — identity signal + unresolved source）。

    四层信号叠加：
        1. delayed_effect  — 延迟反馈（来自 PatternPool structured_progress）
        2. identity_signal — 行为一致性（高一致性时 bias 更新放大）
        3. unresolved_src  — external=高权重，self_generated=低权重
        4. error_type      — execution=-0.03，strategy=-0.10

    公式：
        delta = identity_modulator * (0.08*delayed_effect + 0.03*unresolved_progress)
                - error_penalty
                + (0.02 if success else -0.05)

    identity_modulator：
        - 高 identity（0.7~1.0）→ 系数 1.0~1.5（一致性时更新更强）
        - 低 identity（0.0~0.3）→ 系数 0.5~0.0（漂移时抑制更新）
    """
    intent = (
        pattern_or_intent.intent_tag
        if hasattr(pattern_or_intent, "intent_tag")
        else str(pattern_or_intent) if pattern_or_intent else "unknown"
    )
    drive = INTENT_TO_DRIVE.get(intent, "explore")

    # 延迟反馈
    delayed_effect = float(action_result.get("long_term_effect", 0.0))
    short_term_delta = (
        (pre_state.get("boredom", 0.3) - post_state.get("boredom", 0.3)) * 0.6
        + (pre_state.get("loneliness", 0.3) - post_state.get("loneliness", 0.3)) * 0.4
    )
    effect = 0.9 * delayed_effect + 0.1 * short_term_delta

    # unresolved 进展感（source 加权）
    prev_unresolved = pre_state.get("unresolved", 0.2)
    curr_unresolved = post_state.get("unresolved", 0.2)
    unresolved_progress = prev_unresolved - curr_unresolved   # 正=解决了问题
    unresolved_src = str(action_result.get("unresolved_source", "external"))
    if unresolved_src == "self_generated":
        unresolved_progress *= 0.2    # 自我生成的问题解决价值低
    else:
        unresolved_progress *= 1.0    # 外部问题解决价值正常

    # identity_signal：一致性放大/抑制 bias 更新
    identity_sig = float(action_result.get("identity_signal", 0.5))
    # 高 identity → modulator > 1（稳定时更新更强）；低 identity → modulator < 1
    identity_modulator = 0.5 + 1.0 * identity_sig   # [0.5, 1.5]

    success = action_result.get("success", False)
    pred_err = float(action_result.get("prediction_error", 0.5))
    error_type = str(action_result.get("error_type", "none"))

    # delta 计算
    delta = identity_modulator * (0.08 * effect + 0.03 * unresolved_progress)

    # error type discrimination
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

    # 写入 entity
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


# ============================================================================
# BehaviorPattern 数据结构 v2
# ============================================================================


@dataclass
class BehaviorPattern:
    """
    可进化的组合行为模式 v2。

    新增字段：
        intent_tag     : 行为语义标签（为什么这么做）
        short_term_reward : 即时收益
        long_term_effect : 长期效果（tick 后的状态变化）
        long_term_tracked : 是否在追踪长期效果
        last_state_snapshot : 上次执行时的状态快照（用于长期效果计算）
    """
    actions: List[str]
    intent_tag: str = "unknown"
    weight: float = -0.2
    usage: int = 0
    success: int = 0
    avg_reward: float = 0.0
    avg_pred_err: float = 1.0
    short_term_reward: float = 0.0
    long_term_effect: float = 0.0   # 正=长期好，负=长期坏
    long_term_tracked: bool = False  # 是否在追踪长期效果
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
# PatternPool — 全局行为模式池（单例）
# ============================================================================


class PatternPool:
    _instance: Optional["PatternPool"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._patterns: List[BehaviorPattern] = []
        self._dirty = False
        self._save_timer: Optional[threading.Timer] = None
        # suppress 机制：被压制的 pattern_id → 剩余压制 tick 数
        self._suppressed: Dict[str, int] = {}
        # 长期效果追踪队列：pattern_id → [(tick, state_snapshot), ...]
        self._long_term_queue: Dict[str, List[Tuple[int, Dict[str, float]]]] = {}
        self._load()

    @classmethod
    def get_instance(cls) -> "PatternPool":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ---- 持久化 ----

    def _load(self) -> None:
        if not PATTERNS_FILE.exists():
            return
        try:
            with open(PATTERNS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            patterns_data = data.get("patterns", [])
            self._patterns = [BehaviorPattern.from_dict(p) for p in patterns_data]
            logger.info(f"[PatternPool] loaded {len(self._patterns)} patterns")
        except Exception as e:
            logger.warning(f"[PatternPool] load failed: {e}")

    def _save_async(self) -> None:
        def _do_save():
            try:
                data = {
                    "patterns": [p.to_dict() for p in self._patterns],
                    "updated_at": time.time(),
                }
                with open(PATTERNS_FILE, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.warning(f"[PatternPool] save failed: {e}")

        if self._save_timer is not None:
            self._save_timer.cancel()
        self._save_timer = threading.Timer(5.0, _do_save)
        self._save_timer.start()

    # ---- 候选集合 ----

    def get_candidates(self) -> List[Any]:
        """返回候选，过滤掉被 suppress 的 pattern"""
        candidates: List[Any] = list(PRIMITIVE_ACTIONS)
        with self._lock:
            now = int(time.time())
            for p in self._patterns:
                remaining = self._suppressed.get(p.pattern_id, 0)
                if remaining <= 0:
                    candidates.append(p)
        return candidates

    def get_pattern(self, pattern_id: str) -> Optional[BehaviorPattern]:
        with self._lock:
            for p in self._patterns:
                if p.pattern_id == pattern_id:
                    return p
        return None

    # ---- 反馈闭环 v2 ----

    def update_pattern(
        self,
        pattern_or_id: Any,
        result: Dict[str, Any],
        state_snapshot: Optional[Dict[str, float]] = None,
    ) -> None:
        """
        根据执行结果更新单个 pattern。

        v2 新增：
            - intent_tag：从 content 规则分类
            - short_term_reward：即时奖励
            - long_term_effect：启动延时追踪（等 N ticks 后再算）
        """
        pid = (
            pattern_or_id.pattern_id
            if isinstance(pattern_or_id, BehaviorPattern)
            else str(pattern_or_id) if pattern_or_id else None
        )
        if pid is None:
            return

        with self._lock:
            for p in self._patterns:
                if p.pattern_id == pid:
                    break
            else:
                return

            p.usage += 1
            p.last_used_at = time.time()

            success = result.get("success", False)
            pred_err = float(result.get("prediction_error", 1.0))
            short_reward = float(result.get("short_term_reward", 0.0))
            satisfaction = float(result.get("satisfaction", 0.5))

            # intent_tag（首次设置或更新）
            content = result.get("content", "")
            reason = result.get("reason", "")
            new_intent = _classify_intent(content, reason)
            if new_intent != "unknown":
                p.intent_tag = new_intent

            # short_term_reward 滑动平均
            p.short_term_reward = 0.8 * p.short_term_reward + 0.2 * short_reward

            # 权重更新（短期 + 长期加权）
            reward_total = 0.6 * short_reward + 0.4 * p.long_term_effect
            if success:
                p.success += 1
                p.weight = min(1.0, p.weight + 0.05 * (1 + satisfaction))
            else:
                p.weight = max(-1.0, p.weight - 0.1 * (1 + satisfaction))

            # 预测误差滑动平均
            p.avg_pred_err = 0.8 * p.avg_pred_err + 0.2 * pred_err

            # 长期效果追踪：记录当前状态快照，等 10 ticks 后再算差分
            TRACK_DELAY = 10
            if state_snapshot and p.usage >= 2:
                if p.pattern_id not in self._long_term_queue:
                    self._long_term_queue[p.pattern_id] = []
                self._long_term_queue[p.pattern_id].append(
                    (int(time.time()), dict(state_snapshot))
                )
                # 只保留最近 TRACK_DELAY 条
                if len(self._long_term_queue[p.pattern_id]) > TRACK_DELAY:
                    self._long_term_queue[p.pattern_id].pop(0)

            # satisfaction → suppress
            if satisfaction > 0.7:
                suppress_ticks = int((satisfaction - 0.7) * 30)  # 最高压制 9 ticks
                self._suppressed[p.pattern_id] = max(
                    self._suppressed.get(p.pattern_id, 0), suppress_ticks
                )
                logger.info(f"[PatternPool] suppressed {p.pattern_id} for {suppress_ticks} ticks (satisfaction={satisfaction:.2f})")

            self._dirty = True
            self._save_async()

    def update_primitive(
        self,
        action: str,
        result: Dict[str, Any],
        state_snapshot: Optional[Dict[str, float]] = None,
    ) -> None:
        """更新原子动作（写入 situation-level WMDB）"""
        success = result.get("success", False)
        pred_err = float(result.get("prediction_error", 1.0))
        if state_snapshot:
            wm_key = _make_wm_key(action, state_snapshot)
            wm_predict.record_situation(wm_key, success, pred_err)
        else:
            wm_predict.record_primitive_outcome(action, success, pred_err)

    def tick_suppress(self) -> None:
        """每 tick 减少压制计数"""
        expired = []
        for pid, remaining in self._suppressed.items():
            self._suppressed[pid] = remaining - 1
            if self._suppressed[pid] <= 0:
                expired.append(pid)
        for pid in expired:
            del self._suppressed[pid]
            logger.info(f"[PatternPool] suppress expired: {pid}")

    def compute_long_term_effects(
        self,
        current_tick: int,
        state_history: Optional[List[Dict[str, float]]] = None,
        action_history: Optional[List[str]] = None,
    ) -> None:
        """
        每 tick 调用，计算进入追踪队列的 pattern 的长期效果（v4）。

        长期价值 = 0.7 * state_improvement + 0.3 * structured_progress

        structured_progress：
            - 有熵（状态有变化）AND 有连续性（一段时间内行为不跳变）→ 正
            - 无熵（状态锁死）→ 负（防止稳定麻醉）
            - 高熵但无连续性（行为随机跳变）→ 负（防止无目的抖动）
        """
        TRACK_DELAY = 10
        with self._lock:
            for pid, queue in list(self._long_term_queue.items()):
                if len(queue) < 2:
                    continue
                oldest_tick, oldest_state = queue[0]
                newest_tick, newest_state = queue[-1]
                if newest_tick - oldest_tick < TRACK_DELAY:
                    continue

                # 状态改善
                boredom_delta = oldest_state.get("boredom", 0.5) - newest_state.get("boredom", 0.5)
                loneliness_delta = oldest_state.get("loneliness", 0.5) - newest_state.get("loneliness", 0.5)
                state_improvement = boredom_delta * 0.6 + loneliness_delta * 0.4

                # 结构化进展度（entropy + 连续性）
                raw_entropy = 0.0
                if state_history and len(state_history) >= 3:
                    raw_entropy = self._state_entropy(state_history[-20:])

                # 连续性：action_history 中相邻行为是否相似
                # 用 intent 变化率衡量；跳变越多连续性越低
                coherence = 0.0
                if action_history and len(action_history) >= 3:
                    coherence = self._action_coherence(action_history[-20:])

                # structured_progress：熵和连续性缺一不可
                # 无连续性的高熵 = behavior jitter → 负
                structured_progress = raw_entropy * coherence

                effect = 0.7 * state_improvement + 0.3 * structured_progress

                for p in self._patterns:
                    if p.pattern_id == pid:
                        p.long_term_effect = 0.8 * p.long_term_effect + 0.2 * effect
                        p.long_term_tracked = True
                        logger.info(
                            f"[PatternPool] LTE {pid}: "
                            f"improvement={state_improvement:.3f} "
                            f"entropy={raw_entropy:.3f} "
                            f"coherence={coherence:.3f} "
                            f"→ structured={structured_progress:.3f} "
                            f"effect={effect:.3f} avg={p.long_term_effect:.3f}"
                        )
                        break

    @staticmethod
    def _action_coherence(history: List[str]) -> float:
        """
        计算行为历史的连续性（0~1）。
        1.0 = 所有行为完全相同（无聊）
        0.0 = 每 tick 都在跳变（jitter）
        理想区间：0.3~0.7（有结构的变化）
        """
        if len(history) < 3:
            return 0.5
        transitions = 0
        total = len(history) - 1
        for i in range(total):
            if history[i] != history[i + 1]:
                transitions += 1
        change_rate = transitions / total
        # 高跳变率 → 低连续性；低跳变率 → 高连续性
        return 1.0 - change_rate

    @staticmethod
    def _state_entropy(history: List[Dict[str, float]]) -> float:
        """计算状态历史的信息熵（0~1）"""
        if len(history) < 3:
            return 0.0
        dimensions = ["boredom", "loneliness", "energy", "fatigue"]
        total_var = 0.0
        count = 0
        for dim in dimensions:
            values = [s.get(dim, 0.5) for s in history]
            if not values:
                continue
            mean = sum(values) / len(values)
            variance = sum((v - mean) ** 2 for v in values) / len(values)
            total_var += variance
            count += 1
        if count == 0:
            return 0.0
        raw_entropy = min(total_var / count * 4, 1.0)
        return raw_entropy

    # ---- 变异机制 ----

    def should_mutate(self, boredom: float, recent_pred_err: float) -> bool:
        """条件：boredom > 0.8 或 recent_pred_err > 0.5"""
        return boredom > 0.8 or recent_pred_err > 0.5

    def mutate(self, intent_tag: str = "unknown") -> Optional[BehaviorPattern]:
        """基于现有 pattern 或 primitive 生成新组合，继承 intent_tag"""
        with self._lock:
            if len(self._patterns) >= 20:
                return None

            if self._patterns:
                base = random.choice(self._patterns)
                actions = base.actions.copy()
            else:
                base = random.choice(PRIMITIVE_ACTIONS)
                actions = [base]

            op = random.choice(["insert", "replace", "chain"])
            if op == "insert" and len(actions) < 5:
                new_action = random.choice(PRIMITIVE_ACTIONS)
                pos = random.randint(0, len(actions))
                actions.insert(pos, new_action)
            elif op == "replace":
                pos = random.randint(0, len(actions) - 1)
                new_action = random.choice(PRIMITIVE_ACTIONS)
                actions[pos] = new_action
            elif op == "chain" and len(actions) < 5:
                new_action = random.choice(PRIMITIVE_ACTIONS)
                actions.append(new_action)

            # 去重
            for existing in self._patterns:
                if existing.actions == actions:
                    return self._mutate_retry(attempts=3)

            new_pattern = BehaviorPattern(
                actions=actions,
                intent_tag=intent_tag,
                weight=-0.1,
            )
            self._patterns.append(new_pattern)
            self._dirty = True
            self._save_async()
            logger.info(f"[PatternPool] mutated: {actions} [{intent_tag}]")
            return new_pattern

    def _mutate_retry(self, attempts: int = 3) -> Optional[BehaviorPattern]:
        for _ in range(attempts):
            new_actions = [
                random.choice(PRIMITIVE_ACTIONS)
                for _ in range(random.randint(1, 3))
            ]
            for existing in self._patterns:
                if existing.actions == new_actions:
                    break
            else:
                new_pattern = BehaviorPattern(actions=new_actions, weight=-0.1)
                self._patterns.append(new_pattern)
                self._dirty = True
                self._save_async()
                return new_pattern
        return None

    # ---- 淘汰 ----

    def prune(self) -> List[str]:
        removed: List[str] = []
        with self._lock:
            before = len(self._patterns)
            self._patterns = [p for p in self._patterns if not p.is_failed]
            removed = [p.pattern_id for p in self._patterns[before:]]
            if len(self._patterns) < before:
                self._dirty = True
                self._save_async()
        if removed:
            logger.info(f"[PatternPool] pruned {len(removed)} patterns")
        return removed

    # ---- 统计 ----

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "pattern_count": len(self._patterns),
                "total_usage": sum(p.usage for p in self._patterns),
                "total_success": sum(p.success for p in self._patterns),
                "avg_weight": (
                    sum(p.weight for p in self._patterns) / len(self._patterns)
                    if self._patterns else 0.0
                ),
                "high_performing": [
                    {"id": p.pattern_id, "intent": p.intent_tag, "weight": round(p.weight, 2),
                     "long_term": round(p.long_term_effect, 3)}
                    for p in self._patterns if p.weight > 0.2
                ],
                "suppressed": {pid: r for pid, r in self._suppressed.items() if r > 0},
            }


# ============================================================================
# world_model_predict v2 — situation-level
# ============================================================================


class _WorldModelDB:
    """
    预测数据库 v2：situation-level key。

    结构：{key: {reward_sum, reward_count, pred_err_sum, pred_err_count}}
    key = "action@context_signature" 或 "pattern_id"
    """

    def __init__(self) -> None:
        self._db: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def record(self, key: str, success: bool, pred_err: float) -> None:
        with self._lock:
            if key not in self._db:
                self._db[key] = {
                    "reward_sum": 0.0, "reward_count": 0,
                    "pred_err_sum": 0.0, "pred_err_count": 0,
                }
            d = self._db[key]
            d["reward_sum"] += (1.0 if success else -0.5)
            d["reward_count"] += 1
            d["pred_err_sum"] += pred_err
            d["pred_err_count"] += 1

    def record_situation(self, wm_key: str, success: bool, pred_err: float) -> None:
        """记录 situation-level 经验"""
        self.record(wm_key, success, pred_err)

    def record_primitive_outcome(self, action: str, success: bool, pred_err: float) -> None:
        """兼容旧接口"""
        self.record(action, success, pred_err)

    def predict(self, key: str) -> Dict[str, float]:
        with self._lock:
            if key not in self._db or self._db[key]["reward_count"] == 0:
                return {"reward": 0.0, "uncertainty": 1.0}
            d = self._db[key]
            avg_reward = d["reward_sum"] / d["reward_count"]
            avg_err = d["pred_err_sum"] / d["pred_err_count"]
            return {
                "reward": avg_reward,
                "uncertainty": min(1.0, avg_err),
            }

    def save(self) -> None:
        path = PATTERNS_FILE.parent / "world_model_db.json"
        with self._lock:
            data = dict(self._db)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"[WMDB] save failed: {e}")

    def load(self) -> None:
        path = PATTERNS_FILE.parent / "world_model_db.json"
        if not path.exists():
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            with self._lock:
                self._db = data
            logger.info(f"[WMDB] loaded {len(self._db)} entries")
        except Exception as e:
            logger.warning(f"[WMDB] load failed: {e}")


_wm_db = _WorldModelDB()
_wm_db.load()
wm_predict = _wm_db  # 别名兼容


# ============================================================================
# 评分函数 v2
# ============================================================================


def compute_drive_match(candidate: Any, state: Dict[str, float]) -> float:
    """计算候选与当前驱动力场的匹配度"""
    if isinstance(candidate, BehaviorPattern):
        actions = candidate.actions
    else:
        actions = [str(candidate)]

    types = [ACTION_TO_TYPE.get(a, "explore") for a in actions]
    dominant_type = types[0]

    curiosity = state.get("curiosity", state.get("info_gap", 0.3))
    loneliness = state.get("loneliness", 0.3)
    fatigue = state.get("fatigue", 0.1)
    energy = state.get("energy", 0.8)
    boredom = state.get("boredom", 0.3)
    unresolved = state.get("unresolved", 0.2)

    if dominant_type == "explore":
        return 0.3 * curiosity + 0.3 * boredom + 0.2 * unresolved + 0.2 * (1 - fatigue)
    elif dominant_type == "rest":
        return 0.5 * fatigue + 0.3 * (1 - energy) + 0.2 * (1 - boredom)
    elif dominant_type == "seek":
        return loneliness
    elif dominant_type == "avoid":
        return state.get("danger_level", 0.0) * 0.5 + fatigue * 0.3
    return 0.2


def world_model_predict(
    candidate: Any,
    state: Dict[str, float],
) -> Dict[str, float]:
    """
    对候选行为进行 world_model 预测（situation-level）。

    优先用 situation-level key，其次用纯 action key。
    """
    if isinstance(candidate, BehaviorPattern):
        # pattern：用 pattern_id
        base = _wm_db.predict(candidate.pattern_id)
        # intent_tag 调节
        reward = float(base["reward"])
        if candidate.intent_tag == "seek_connection" and state.get("loneliness", 0.3) > 0.5:
            reward += 0.1
        elif candidate.intent_tag == "explore_topic" and state.get("boredom", 0.3) > 0.5:
            reward += 0.1
        uncertainty = float(base["uncertainty"])
        count = 0
        with _wm_db._lock:
            if candidate.pattern_id in _wm_db._db:
                count = _wm_db._db[candidate.pattern_id].get("reward_count", 0)
        if count < 3:
            uncertainty = min(1.0, uncertainty + (3 - count) * 0.15)
        return {"reward": max(-1.0, min(1.0, reward)), "uncertainty": max(0.0, min(1.0, uncertainty))}
    else:
        # primitive：用 situation-level key
        action = str(candidate)
        wm_key = _make_wm_key(action, state)
        base = _wm_db.predict(wm_key)
        reward = float(base["reward"])
        uncertainty = float(base["uncertainty"])
        # 状态调节
        boredom = state.get("boredom", 0.3)
        loneliness = state.get("loneliness", 0.3)
        if action.startswith("web_"):
            reward += boredom * 0.1
        # 数据少时提升不确定性
        count = 0
        with _wm_db._lock:
            if wm_key in _wm_db._db:
                count = _wm_db._db[wm_key].get("reward_count", 0)
        if count < 3:
            uncertainty = min(1.0, uncertainty + (3 - count) * 0.15)
        return {"reward": max(-1.0, min(1.0, reward)), "uncertainty": max(0.0, min(1.0, uncertainty))}


def record_outcome(
    candidate: Any,
    success: bool,
    prediction_error: float,
    state_snapshot: Optional[Dict[str, float]] = None,
) -> None:
    """记录执行结果到 situation-level world_model_db"""
    if isinstance(candidate, BehaviorPattern):
        key = candidate.pattern_id
    else:
        key = _make_wm_key(str(candidate), state_snapshot or {}) if state_snapshot else str(candidate)
    _wm_db.record(key, success, prediction_error)
    _wm_db.save()


def score_candidate(
    candidate: Any,
    state: Dict[str, float],
    pool: Optional[PatternPool] = None,
    entity_state: Any = None,
) -> float:
    """
    综合评分：

    base(0.3) + 0.6*reward - 0.4*uncertainty + pattern_weight
    + long_term_effect_bonus(0.3)
    + long_term_bias(0.15)  ← 行为风格偏置（若 entity_state 有数据）
    """
    base = compute_drive_match(candidate, state)
    pred = world_model_predict(candidate, state)
    pred_reward = pred["reward"]
    pred_uncertainty = pred["uncertainty"]

    pattern_weight = 0.0
    long_term_bonus = 0.0
    if isinstance(candidate, BehaviorPattern):
        pattern_weight = candidate.weight
        if candidate.long_term_tracked:
            long_term_bonus = candidate.long_term_effect * 0.3

    # v2 长时偏置：intent_tag → drive → entity bias
    bias_bonus = 0.0
    if entity_state is not None and hasattr(entity_state, "long_term_bias"):
        intent = (
            candidate.intent_tag
            if isinstance(candidate, BehaviorPattern)
            else "unknown"
        )
        drive = INTENT_TO_DRIVE.get(intent, "explore")
        bias = entity_state.long_term_bias.get(drive, 0.0)
        bias_bonus = 0.15 * bias  # 小权重，防止主导决策

    score = (
        base
        + 0.6 * pred_reward
        - 0.4 * pred_uncertainty
        + pattern_weight
        + long_term_bonus
        + bias_bonus
    )
    return max(-1.0, min(1.0, score))


# ============================================================================
# 顶层便捷函数
# ============================================================================


def get_pool() -> PatternPool:
    return PatternPool.get_instance()


def select_best_candidate(state: Dict[str, float], entity_state: Any = None) -> Any:
    """
    从候选池中选择最佳候选（含 suppress 过滤 + 长时偏置）。
    """
    pool = get_pool()
    candidates = pool.get_candidates()

    if not candidates:
        return random.choice(PRIMITIVE_ACTIONS)

    boredom = state.get("boredom", 0.3)
    recent_err = _wm_db.predict("__global__").get("uncertainty", 0.5)

    scored = [(c, score_candidate(c, state, pool, entity_state)) for c in candidates]
    scored.sort(key=lambda x: x[1], reverse=True)
    best = scored[0][0]

    # 15% 探索：偶尔选第二名
    if len(scored) > 1 and random.random() < 0.15:
        best = scored[1][0]

    # 变异触发（30% 概率用新 pattern）
    if pool.should_mutate(boredom, recent_err):
        if random.random() < 0.3:
            # 尝试推断当前 intent
            intent = "unknown"
            if boredom > 0.6:
                intent = "kill_time"
            elif state.get("loneliness", 0.3) > 0.5:
                intent = "seek_connection"
            new_p = pool.mutate(intent_tag=intent)
            if new_p is not None:
                new_score = score_candidate(new_p, state, pool, entity_state)
                if new_score > scored[0][1]:
                    best = new_p

    # Exploration floor：带偏探索（guided exploration）
    # 从 top-3 候选中随机选，而非完全随机（避免破坏已形成的结构）
    if len(scored) >= 3 and random.random() < 0.10:
        best = random.choice(scored[:3])[0]
    elif len(scored) >= 2 and random.random() < 0.10:
        best = random.choice(scored[:2])[0]

    return best


def apply_result(
    candidate: Any,
    result: Dict[str, Any],
    state_snapshot: Optional[Dict[str, float]] = None,
) -> None:
    """
    将执行结果反馈给 pattern pool 和 world_model。

    result 格式（v2）：
        {
            "success": bool,
            "detail": str,
            "prediction_error": float,
            "short_term_reward": float,
            "satisfaction": float,    # 新增：满足感
            "content": str,           # 用于 intent_tag 分类
            "reason": str,
            "count": int,
        }
    """
    pool = get_pool()
    if isinstance(candidate, BehaviorPattern):
        pool.update_pattern(candidate.pattern_id, result, state_snapshot)
    elif isinstance(candidate, str) and candidate in PRIMITIVE_ACTIONS:
        pool.update_primitive(candidate, result, state_snapshot)

    record_outcome(candidate, result.get("success", False), result.get("prediction_error", 1.0), state_snapshot)
