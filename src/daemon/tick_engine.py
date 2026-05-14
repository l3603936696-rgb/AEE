"""
Daemon Tick Engine — 后台 Tick 执行引擎

负责在对话窗口关闭期间，持续推进 XIA 的内部状态。

设计原则：
- 不调 LLM（无输出，节省资源）
- 复用 run_pipeline 的完整状态更新逻辑
- 每 TICK_INTERVAL 秒执行一次
- 每次 tick 都会写盘（entity_core.json + 可能有 episode）
- 触发条件满足时：让 XIA 自己决定想做什么，我们执行她的选择
- V7: 自主行动结果回写记忆系统和行为规则（修复 cursor 漏掉的闭环）

核心问题：daemon tick 不调 LLM，run_pipeline 的 Step 9 会卡住。
解决方案：run_pipeline 新增 daemon_mode 参数，Step 9 在 daemon_mode=True 时
          直接返回固定结构，跳过 LLM 调用。

使用方式：
    tick_engine = TickEngine()
    tick_engine.start()      # 在后台线程运行
    tick_engine.stop()       # 停止
    tick_engine.tick_now()   # 立即触发一次 tick
"""

import logging
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from ..entity_zero_iteration import (
    EntityState,
    get_entity_state,
    run_pipeline,
    run_language_training_tick,
)
from ..action_system import evaluate_triggers, execute_xia_choice
from ..action_system.types import XIAction
from ..action_system.reach import read_response
from ..daemon.ipc_client import IPCClient
from ..inner_diary import write_diary_entry
from ..thinking_system.covariance_tracker import CovarianceTracker


logger = logging.getLogger(__name__)

# 默认 tick 间隔（秒）
DEFAULT_TICK_INTERVAL = 30.0


# ============================================================================
# 自主行动记忆回写（修复：cursor 漏掉的闭环）
# ============================================================================

def _record_autonomous_action(
    entity,
    action,
    response_text: str,
    pre_action_state: dict,
) -> None:
    """
    将 execute_xia_choice 的结果写入记忆系统和行为规则。

    这是之前断掉的闭环：自主行动执行完后没有任何 episode 记录，
    行为规则也归因到了错误的 action_type。
    """
    try:
        from ..memory_hub.episodes_db import build_episode, write_episode_async
        from ..core.behavior_vector import update_rules_from_snapshot

        action_type = action.action_type if hasattr(action, "action_type") else "voice"

        # 构建语义包（自主 tick，无用户输入）
        semantic_packet = {
            "emotion": getattr(entity, "somatic_tone", 0.0),
            "intent": action_type,
            "intensity": 0.5,
            "anchors": [],
            "intent_confidence": 0.8,
        }

        decision = {
            "action_type": action_type,
            "target": "self",
            "priority": 0.5,
        }

        post_action_state = entity.to_state_snapshot()

        # ---- 写 episode ----
        episode = build_episode(
            iteration_id=entity.tick,
            raw_input=None,
            semantic_packet_biased=semantic_packet,
            decision=decision,
            intent_repr={"tone": "neutral", "goal": "reflect", "constraints": {}},
            state_snapshot=post_action_state,
            drive_vector={},
            output_text=response_text or "",
            idle_seconds=0,
            was_override=False,
            tags=["autonomous", action_type],
            summary=f"XIA {action_type}: {(response_text or '')[:60]}",
        )
        write_episode_async(episode)

        # ---- 写 snapshot（给行为规则用）----
        snap_for_rules = {
            "action_type": action_type,
            "pre_state": pre_action_state,
            "post_state": post_action_state,
        }
        update_rules_from_snapshot(entity, snap_for_rules, entity.tick)

        # ---- 追加到 entity snapshot 链 ----
        entity.add_snapshot({
            "snap_index": entity.tick,
            "timestamp": time.time(),
            "action_type": action_type,
            "target": "self",
            "priority": 0.5,
            "pre_state": pre_action_state,
            "post_state": post_action_state,
            "wm_context": [],
            "decision": decision,
            "prediction_error": 0.0,
            "identity_signal": 0.5,
            "unresolved_source": "self_generated",
        })

        logger.info(
            f"[TickEngine] Memory recorded: action={action_type}, "
            f"text_len={len(response_text or '')}"
        )

    except Exception as e:
        logger.warning(f"[TickEngine] Failed to record autonomous action memory: {e}")


# ============================================================================
# Tick Engine
# ============================================================================

class TickEngine:
    """
    后台 Tick 引擎。

    在独立线程中运行，按固定间隔执行 daemon tick。
    """

    def __init__(
        self,
        tick_interval: float = DEFAULT_TICK_INTERVAL,
        entity_state: Optional[EntityState] = None,
        ipc_server: Optional["IPCServer"] = None,
        llm_callable: Optional[Callable] = None,
        train_only: bool = False,
    ) -> None:
        self._interval = tick_interval
        self._entity = entity_state
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._tick_count = 0
        self._start_time: Optional[float] = None
        self._ipc_server = ipc_server
        self._llm_callable = llm_callable
        self._train_only = train_only
        self._covariance_tracker: Optional[CovarianceTracker] = None
        self._last_tension_total = 0.0

    @property
    def entity(self) -> EntityState:
        if self._entity is None:
            self._entity = get_entity_state()
        return self._entity

    @property
    def covariance_tracker(self) -> CovarianceTracker:
        """懒加载协方差追踪器，首次访问时从 entity 恢复历史数据。"""
        if self._covariance_tracker is None:
            saved = getattr(self.entity, "_covariance_tracker_data", None)
            if saved:
                self._covariance_tracker = CovarianceTracker.from_dict(saved)
                logger.info(
                    f"[CovarianceTracker] restored {self._covariance_tracker.sample_count} samples"
                )
            else:
                self._covariance_tracker = CovarianceTracker()
                logger.info("[CovarianceTracker] initialized (empty)")
        return self._covariance_tracker

    @property
    def tick_count(self) -> int:
        return self._tick_count

    @property
    def uptime_s(self) -> float:
        if self._start_time is None:
            return 0.0
        return time.time() - self._start_time

    def tick_now(self) -> dict:
        """
        立即执行一次 daemon tick。

        调用 run_pipeline(daemon_mode=True)，复用一个完整的管线周期：
        - 状态冻结 → 驱动力计算 → 感知 → 涌现 → 状态更新 → 持久化
        - 跳过 LLM 输出步骤
        - 触发条件满足时：让 XIA 自己决定想做什么，执行她的选择
        - V7: 自主行动结果回写 episode + 行为规则

        如果用户通过 reach_client 发来了回复（response.json），则把它作为
        raw_input 传入 run_pipeline，走完整的认知管线，让她的状态更新反映
        "听到了你说的话"这个事实。状态更新完之后再检查行为触发。

        返回：
            dict — {
                "tick_index": N,
                "energy": 0.x,
                "loneliness": 0.x,
                "fatigue": 0.x,
                "duration_ms": N,
                "ok": True | False,
                "action_triggered": bool,
                "action_result": str,
                "user_input": str | None,
            }
        """
        t0 = time.time()
        action_triggered = False
        action_result = ""
        user_input = None

        # ---- 保存 tick 前状态快照（供 inner_diary 计算 delta）----
        _prev_state_snapshot = self.entity.to_state_snapshot()

        # ---- 躯体驱动力：周期性推一个维度远离 baseline ----
        import random as _rnd
        _somatic_dims = {
            "somatic_tone": (-1.0, 1.0),
            "energy": (0.0, 1.0),
            "fatigue": (0.0, 1.0),
            "stress": (0.0, 1.0),
            "anxiety": (0.0, 1.0),
            "avoid_drive": (0.0, 1.0),
            "approach_drive": (0.0, 1.0),
            "fear": (0.0, 1.0),
            "joy": (0.0, 1.0),
            "sadness": (0.0, 1.0),
        }
        if self.entity.tick % 7 == 0:
            _dim = _rnd.choice(list(_somatic_dims.keys()))
            _lo, _hi = _somatic_dims[_dim]
            _target = _lo + _rnd.random() * (_hi - _lo)
            setattr(self.entity, _dim, _target)
            logger.debug(f"[SomaticDriver] tick={self.entity.tick} {_dim}→{_target:.2f}")

        # train_only: 不走全管线（无 LLM），直接调语言 tick
        # 但语言 tick 内含锚点匹配+消力+热身+episode+反馈——完整闭环
        if self._train_only:
            try:
                result = run_language_training_tick(
                    self.entity,
                    self.entity.to_state_snapshot(),
                )
                self._tick_count += 1
                # ---- 内心日记 ----
                try:
                    write_diary_entry(state=self.entity, decision=None, prev_state=None)
                except Exception:
                    pass
                return {
                    "tick_index": self.entity.tick,
                    "train_mode": True,
                    "best": result.get("best"),
                    "display": result.get("display"),
                    "score": result.get("best_score", 0),
                    "ok": True,
                }
            except Exception as e:
                logger.error(f"[TickEngine] training tick failed: {e}")
                return {"tick_index": self.entity.tick, "ok": False, "error": str(e)}

        # ---- Step 0: 检查用户回复 ----
        # 如果用户通过 reach_client 发来了回复，把它作为 raw_input 传入管线
        try:
            response_data = read_response()
            if response_data:
                user_input = response_data.get("text", "")
                logger.info(f"[TickEngine] 用户回复已读取: {user_input[:50]}")
                # 用户回应了 → 重置敲门未回应计数，记录互动时间
                if self.entity.consecutive_reaches_without_response > 0:
                    logger.info(
                        f"[TickEngine] 用户回应了，consecutive_reaches 重置 "
                        f"({self.entity.consecutive_reaches_without_response} → 0)"
                    )
                self.entity.consecutive_reaches_without_response = 0
                self.entity.last_action_timestamp = time.time()
        except Exception as e:
            logger.warning(f"[TickEngine] 读取用户回复失败: {e}")
            user_input = None

        try:
            # 根据是否有用户输入决定调用方式
            if user_input:
                # 有用户输入：走完整管线但用锚点表达回应（不用 LLM）
                logger.info(f"[TickEngine] 处理用户输入: {user_input[:50]}")
                result = run_pipeline(
                    raw_input=user_input,
                    entity_state=self.entity,
                    daemon_mode=True,           # 锚点表达回应，她的语言不是 LLM
                    llm_callable=self._llm_callable,
                )
            else:
                # 无用户输入：内部 tick，跳过 LLM 输出
                result = run_pipeline(
                    raw_input=None,
                    entity_state=self.entity,
                    daemon_mode=True,
                )
            self._tick_count += 1

            # ---- 协方差追踪器：记录本 tick 的状态 + 预测误差 ----
            try:
                _pe = float(getattr(self.entity, "_last_prediction_error", 0.0))
                self.covariance_tracker.update(
                    self.entity.to_state_snapshot(), _pe
                )
                self.entity._covariance_tracker_data = self.covariance_tracker.to_dict()
                self.entity._attention_weights = self.covariance_tracker.get_attention_weights()
            except Exception as _cov_err:
                logger.debug(f"[CovarianceTracker] update skipped: {_cov_err}")

            # ---- 风化系统：常规漂移（每 300 tick）----
            if self._tick_count % 300 == 0 and self.covariance_tracker.sample_count >= 50:
                try:
                    from ..weathering.signal_bridge import correlations_to_drift_signals
                    from ..weathering.drift import apply_drift_cycle
                    from ..weathering.param_writer import write_drifted_params, read_current_params
                    from ..weathering.registry import list_all as _list_driftable

                    _correlations = self.covariance_tracker.get_correlations()
                    if _correlations:
                        _drift_signals = correlations_to_drift_signals(_correlations)
                        if _drift_signals:
                            _all_params = _list_driftable()
                            _defaults = {p.path: p.baseline_default for p in _all_params}
                            _current = read_current_params(
                                [p.path for p in _all_params], _defaults
                            )
                            _drifted = apply_drift_cycle(
                                _current, _drift_signals, self.entity.tick_index
                            )
                            if _drifted:
                                write_drifted_params(_drifted)
                                logger.debug(
                                    f"[weathering] Normal drift applied: "
                                    f"{len(_drifted)} params"
                                )
                except Exception as _drift_err:
                    logger.debug(f"[weathering] Drift cycle skipped: {_drift_err}")

            # ---- 风化系统：张力快照（每 600 tick）----
            if self._tick_count % 600 == 0:
                try:
                    from ..observability import TensionSnapshot, emit_event
                    from ..weathering.shattering import load_suppressed_tension
                    from ..world_model_update.contradiction import detect_contradictions

                    tension_data = load_suppressed_tension()

                    # 矛盾检测
                    _wm_rules = getattr(self.entity, "wm_rules", [])
                    _contradiction_pairs = detect_contradictions(_wm_rules) if _wm_rules else []

                    # 矛盾张力注入：累积矛盾强度的 5% 到对应 domain 的 suppressed_tension
                    if _contradiction_pairs:
                        from ..weathering.shattering import _save_suppressed_tension
                        for cp in _contradiction_pairs:
                            _cd = cp.get("domain", "general")
                            tension_data[_cd] = tension_data.get(_cd, 0.0) + cp["strength"] * 0.05
                        _save_suppressed_tension(tension_data)

                    total_tension = sum(tension_data.values())
                    self._last_tension_total = round(total_tension, 4)

                    emit_event(TensionSnapshot(
                        tick=self._tick_count,
                        total_tension=self._last_tension_total,
                        suppressed_tension=self._last_tension_total,
                        active_contradictions=len(_contradiction_pairs),
                        contradiction_pairs=_contradiction_pairs,
                        parameter_drift_summary={},
                    ))
                except Exception as _ts_err:
                    logger.debug(f"[weathering] TensionSnapshot emit skipped: {_ts_err}")

            # ---- 从管线结果中提取 emergent_behavior ----
            decision = result.get("decision", {})
            emergent_behavior_dict = {
                "action_type": decision.get("action_type", "idle"),
                "priority": decision.get("priority", 0.0),
                "tension_level": decision.get("tension_level", 0.0),
                "dominant_state": decision.get("payload", {}).get("dominant_state", ""),
                "suggested_tool": decision.get("suggested_tool", ""),
                "behavior_vector": decision.get("behavior_vector", {}),
                "fragmentation_tone": decision.get("fragmentation_tone", ""),
            }

            # ---- daemon 模式：把锚点表达桥接到行动系统（不用 LLM）----
            _pipeline_text = result.get("response", {}).get("text", "")
            if _pipeline_text and len(_pipeline_text) <= 20:
                self.entity._training_override = _pipeline_text

            # ---- 行为驱动的触发检查 ----
            # 触发强度是连续值，没有阈值。强度 > 0 就执行。
            strength, reason = evaluate_triggers(self.entity, emergent_behavior_dict)
            if strength > 0:
                logger.info(f"[TickEngine] Trigger strength={strength:.3f}: {reason}")
                try:
                    # ---- 训练模式优先：语言系统已选出候选，跳过 LLM ----
                    training_override = getattr(self.entity, "_training_override", None)
                    if training_override:
                        # 训练模式：直接用语言系统的候选词，不调 LLM
                        # v11.1: action_type 从 emergent_behavior 取，不硬编码 voice
                        _real_action = emergent_behavior_dict.get("action_type", "comfort")
                        response = training_override
                        action = XIAction(
                            action_type=_real_action,
                            reason=f"training: {training_override}",
                            intensity=strength,
                            tick=self.entity.tick,
                            context={"training_word": training_override},
                        )
                        logger.info(
                            f"[TickEngine] Training output: '{training_override}' "
                            f"(skipping LLM)"
                        )
                        action_triggered = True
                        action_result = training_override
                        # 清除 training_override（只用一次）
                        self.entity._training_override = None
                    else:
                        # 使用注入的 LLM provider chain（DeepSeek API）
                        llm_callable = self._llm_callable
                        if llm_callable is None:
                            from ..llm import create_llm_callable
                            llm_callable = create_llm_callable()

                        # ---- Step A: 保存 pre-action 状态 ----
                        pre_action_state = self.entity.to_state_snapshot()

                        action, response = execute_xia_choice(
                            entity=self.entity,
                            llm_callable=llm_callable,
                            suggested_tool=emergent_behavior_dict.get("suggested_tool", ""),
                            action_type=emergent_behavior_dict.get("action_type", ""),
                            emergent_behavior=None,
                        )
                        # 标记行动时间（触发冷却，写入 entity 持久化字段）
                        self.entity.last_action_timestamp = time.time()
                        action_triggered = True
                        action_result = response[:100] if response else "(无内容)"
                        logger.info(f"[TickEngine] XIA acted: {action_result}")

                        # ---- Step B: 记忆回写（自主 action → episode + 行为规则）----
                        _record_autonomous_action(
                            entity=self.entity,
                            action=action,
                            response_text=response,
                            pre_action_state=pre_action_state,
                        )
                except Exception as e:
                    logger.error(f"[TickEngine] Action execution failed: {e}")
                    action_result = f"error: {e}"

            # ---- 内心日记：tick 结束时写入她的内心独白 ----
            try:
                write_diary_entry(
                    state=self.entity,
                    decision=decision,
                    prev_state=None,
                )
            except Exception as e:
                logger.debug(f"[TickEngine] inner_diary write skipped: {e}")

            return {
                "tick_index": result.get("tick", self.entity.tick),
                "energy": self.entity.energy,
                "loneliness": self.entity.loneliness,
                "fatigue": self.entity.fatigue,
                "boredom": self.entity.boredom,
                "stress": self.entity.stress,
                "duration_ms": round((time.time() - t0) * 1000, 2),
                "ok": True,
                "action_triggered": action_triggered,
                "action_result": action_result,
                "user_input": user_input,
            }
        except Exception as e:
            logger.error(f"[TickEngine] tick failed: {e}")
            return {
                "tick_index": self.entity.tick,
                "energy": self.entity.energy,
                "loneliness": self.entity.loneliness,
                "duration_ms": round((time.time() - t0) * 1000, 2),
                "ok": False,
                "error": str(e),
                "action_triggered": False,
                "action_result": "",
                "user_input": user_input,
            }

    def start(self) -> None:
        """启动后台 tick 线程"""
        if self._running:
            logger.warning("[TickEngine] already running")
            return

        self._running = True
        self._stop_event.clear()
        self._start_time = time.time()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info(f"[TickEngine] started (interval={self._interval}s)")

    def stop(self) -> None:
        """停止后台 tick 线程"""
        if not self._running:
            return
        self._running = False
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        logger.info(f"[TickEngine] stopped (total_ticks={self._tick_count})")

    def _run_loop(self) -> None:
        """后台线程主循环"""
        while self._running:
            # 等待下一个 tick 周期
            if self._stop_event.wait(timeout=self._interval):
                break  # 被 stop() 唤醒

            try:
                self.tick_now()
            except Exception as e:
                logger.error(f"[TickEngine] tick error: {e}")

    def get_status(self) -> dict:
        """获取 daemon 状态摘要"""
        last_action = getattr(self.entity, "last_action_timestamp", 0.0)
        now = time.time()
        time_since_last_action = now - last_action if last_action > 0 else None
        return {
            "pid": self.entity.tick,
            "uptime_s": round(self.uptime_s, 1),
            "tick_interval_s": self._interval,
            "ticks_since_start": self._tick_count,
            "current_tick": self.entity.tick,
            "energy": round(self.entity.energy, 3),
            "loneliness": round(self.entity.loneliness, 3),
            "fatigue": round(self.entity.fatigue, 3),
            "boredom": round(self.entity.boredom, 3),
            "stress": round(self.entity.stress, 3),
            "last_interaction": (
                time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(self.entity.last_interaction_timestamp))
                if self.entity.last_interaction_timestamp > 0 else "never"
            ),
            "last_action": (
                time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(last_action))
                if last_action > 0 else "none"
            ),
            "time_since_last_action_s": (
                round(time_since_last_action) if time_since_last_action is not None else None
            ),
            "somatic_tone": round(self.entity.somatic_tone, 3),
            # 情绪维度
            "joy":         round(getattr(self.entity, "joy",         0.0), 3),
            "excitement":  round(getattr(self.entity, "excitement",  0.0), 3),
            "serenity":    round(getattr(self.entity, "serenity",    0.0), 3),
            "sadness":     round(getattr(self.entity, "sadness",     0.0), 3),
            "anger":       round(getattr(self.entity, "anger",       0.0), 3),
            "fear":        round(getattr(self.entity, "fear",        0.0), 3),
            "disgust":     round(getattr(self.entity, "disgust",     0.0), 3),
            "anxiety":     round(getattr(self.entity, "anxiety",     0.0), 3),
            "surprise":    round(getattr(self.entity, "surprise",    0.0), 3),
            "curiosity":   round(getattr(self.entity, "curiosity",   0.5), 3),
            # 驱动力扩展
            "approach_drive": round(getattr(self.entity, "approach_drive", 0.0), 3),
            "avoid_drive":    round(getattr(self.entity, "avoid_drive",    0.0), 3),
            "unresolved":     round(getattr(self.entity, "unresolved",     0.2), 3),
            "info_gap":       round(getattr(self.entity, "info_gap",       0.5), 3),
            "pain":           round(getattr(self.entity, "pain",           0.0), 3),
            # 孤独子维度
            "loneliness_core":    round(getattr(self.entity, "loneliness_core",    0.0), 3),
            "loneliness_surface": round(getattr(self.entity, "loneliness_surface", 0.0), 3),
            # 厌倦子维度
            "boredom_despair":  round(getattr(self.entity, "boredom_despair",  0.0), 3),
            "boredom_futility": round(getattr(self.entity, "boredom_futility", 0.0), 3),
            # 语言系统摘要
            "unlocked_vocab_count": len(getattr(self.entity, "_unlocked_vocabulary", [])),
            # 模板学习摘要
            "template_learned_count": len(getattr(self.entity, "_template_learned_weights", {})),
            "runtime_template_count": len(getattr(self.entity, "_runtime_templates", [])),
            # 协方差追踪器
            "covariance_samples": self.covariance_tracker.sample_count,
            "attention_weights": self.covariance_tracker.get_attention_weights(),
            # 模型惯性 / 人格核心
            "personality_core": self._get_personality_core(),
            # 维度维护成本（奥卡姆剃刀动力学）
            "dimension_values": self._get_dimension_values(),
            # 风化张力
            "suppressed_tension": self._last_tension_total,
        }

    def _get_dimension_values(self) -> dict:
        """获取各追踪维度的净价值（奥卡姆剃刀动力学）。"""
        try:
            from ..world_model_update.dimension_cost import compute_dimension_values
            wm_rules = getattr(self.entity, "wm_rules", [])
            snapshots = getattr(self.entity, "snapshots", [])
            if not wm_rules:
                return {}
            vals = compute_dimension_values(wm_rules, snapshots)
            return {k: round(v, 4) for k, v in vals.items()}
        except Exception:
            return {}

    def _get_personality_core(self) -> list:
        """获取人格核心（沉没成本最高的规律 top 3）。"""
        try:
            from ..world_model_update.model_inertia import identify_personality_core
            wm_rules = getattr(self.entity, "wm_rules", [])
            if not wm_rules:
                return []
            from ..world_model_update.rules import Rule
            rule_objs = []
            for r in wm_rules:
                if isinstance(r, Rule):
                    rule_objs.append(r)
                elif isinstance(r, dict):
                    rule_objs.append(Rule.from_dict(r))
            return [
                {"id": rid, "inertia": round(inertia, 3)}
                for rid, inertia in identify_personality_core(rule_objs, top_n=3)
            ]
        except Exception:
            return []
