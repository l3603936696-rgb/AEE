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
from typing import Callable, Optional

from ..entity_zero_iteration import (
    EntityState,
    get_entity_state,
    run_pipeline,
    run_language_training_tick,
    process_async_updates,
)
from ..daemon.action_execution import run_action_execution
from ..daemon.async_updates import submit_pipeline_async_updates
from ..daemon.causal_observation import record_causal_observation
from ..daemon.covariance_update import update_covariance_tracker
from ..daemon.environment_vector import decay_environment_vector
from ..daemon.expression_postprocess import run_expression_postprocess
from ..daemon.output_causal_observation import (
    close_pending_output_causal,
    record_pending_output_causal,
)
from ..daemon.periodic_maintenance import (
    emit_tension_snapshot_tick,
    run_causal_learning,
    run_weathering_drift,
)
from ..daemon.response_prewarm import update_response_cache
from ..daemon.reading_cycle import (
    extract_sentence_patterns_from_reading,
    run_reading_intake,
)
from ..daemon.reflection_jepa_tick import run_reflection_and_jepa, write_tick_diary
from ..daemon.sibling_tick import (
    apply_sibling_social_credit,
    run_stereotype_fork_check,
)
from ..daemon.source_tick import update_source_tick
from ..daemon.state_pattern_tick import run_state_pattern_memory_tick
from ..daemon.tick_input import prepare_tick_input
from ..daemon.tick_status import build_tick_status
from ..daemon.world_model_tick import run_world_model_tick
from ..daemon.ipc_client import IPCClient
from ..daemon.protocol import IPCRequest, IPCResponse
from ..observability import get_registry
from ..thinking_system.covariance_tracker import CovarianceTracker
from ..response_cache import ResponseCache


logger = logging.getLogger(__name__)

# 默认 tick 间隔（秒）
DEFAULT_TICK_INTERVAL = 30.0


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
        response_cache: Optional[ResponseCache] = None,
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
        self._sibling_channel = None  # 懒加载
        self._response_cache = response_cache
        self._async_loop: Optional["asyncio.AbstractEventLoop"] = None
        self._async_thread: Optional[threading.Thread] = None
        self._async_running = False

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
    def sibling_channel(self):
        """懒加载姐妹通道。entity._sibling_channel 配置存在时才启用。"""
        if self._sibling_channel is None:
            cfg = getattr(self.entity, "_sibling_channel", None)
            if cfg and isinstance(cfg, dict) and cfg.get("enabled"):
                try:
                    from ..sibling_channel import SiblingChannel
                    self._sibling_channel = SiblingChannel(
                        channel_dir=cfg["channel_dir"],
                        self_name=cfg["self_name"],
                        peer_name=cfg["peer_name"],
                    )
                    logger.info(
                        f"[SiblingChannel] connected: {cfg['self_name']} <-> {cfg['peer_name']}"
                    )
                except Exception as e:
                    logger.warning(f"[SiblingChannel] init failed: {e}")
                    self._sibling_channel = False  # 标记为失败，不再重试
            else:
                self._sibling_channel = False  # 未配置
        return self._sibling_channel if self._sibling_channel else None

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

        # 可观测性：同步当前 tick 到注册表（使所有 @observe 装饰器的 health 判定生效）
        try:
            get_registry().set_tick(self.entity.tick)
        except Exception:
            pass

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
                record_causal_observation(self.entity, _prev_state_snapshot, "none")
                write_tick_diary(self.entity, None, logger)
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

        user_input, _input_source, _source_identity = prepare_tick_input(
            self.entity,
            self.sibling_channel,
            logger,
        )
        decay_environment_vector(self.entity)
        close_pending_output_causal(self.entity, logger)

        try:
            if user_input:
                logger.info(f"[TickEngine] 处理用户输入: {user_input[:50]}")
                result = run_pipeline(
                    raw_input=user_input,
                    entity_state=self.entity,
                    daemon_mode=True,
                    llm_callable=self._llm_callable,
                    source_identity=_source_identity,
                )
            else:
                result = run_pipeline(
                    raw_input=None,
                    entity_state=self.entity,
                    daemon_mode=True,
                )
            self._tick_count += 1

            submit_pipeline_async_updates(
                self.entity,
                result,
                self._submit_async,
                process_async_updates,
                logger,
            )

            apply_sibling_social_credit(self.entity, result, _input_source, logger)

            run_stereotype_fork_check(self.entity, self._tick_count, logger)

            _src_id = update_source_tick(
                self.entity,
                result,
                _input_source,
                _source_identity,
                logger,
            )
            # ---- 输出因果追踪 Step 1：记录本次输出快照 ----
            record_pending_output_causal(self.entity, result)

            update_response_cache(self._response_cache, result, self.entity, logger)

            run_expression_postprocess(self.entity, result, logger)

            update_covariance_tracker(self.entity, self.covariance_tracker, logger)

            run_reading_intake(self.entity, logger)

            extract_sentence_patterns_from_reading(self.entity, result, logger)

            run_state_pattern_memory_tick(self.entity, result, logger)

            run_world_model_tick(self.entity, logger)

            run_causal_learning(self.entity, logger)

            run_weathering_drift(self.entity, self.covariance_tracker, logger)

            self._last_tension_total = emit_tension_snapshot_tick(
                self.entity,
                self._tick_count,
                self._last_tension_total,
                logger,
            )
            decision, action_triggered, action_result = run_action_execution(
                self.entity,
                result,
                self.sibling_channel,
                self._llm_callable,
                logger,
            )
            record_causal_observation(self.entity, _prev_state_snapshot, _input_source)

            write_tick_diary(self.entity, decision, logger)

            run_reflection_and_jepa(self.entity, logger)
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
        self._start_async_loop()
        logger.info(f"[TickEngine] started (interval={self._interval}s)")

    # ── 异步事件循环（供 process_async_updates 使用）──────────────────────────────────
    def _start_async_loop(self) -> None:
        """启动专用异步线程，运行事件循环。"""
        if self._async_running:
            return
        self._async_running = True

        def _run():
            import asyncio as _asyncio
            self._async_loop = _asyncio.new_event_loop()
            _asyncio.set_event_loop(self._async_loop)
            self._async_loop.run_forever()
            self._async_loop.close()

        self._async_thread = threading.Thread(target=_run, daemon=True)
        self._async_thread.start()
        logger.info("[TickEngine] async loop started")

    def _submit_async(self, coro) -> None:
        """向异步线程提交协程（fire-and-forget）。"""
        if self._async_loop is None or not self._async_running:
            return
        import asyncio as _asyncio
        try:
            _asyncio.run_coroutine_threadsafe(coro, self._async_loop)
        except Exception as e:
            logger.debug(f"[TickEngine] async submit failed: {e}")

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
        """Return daemon status summary."""
        return build_tick_status(
            self.entity,
            self.covariance_tracker,
            self.uptime_s,
            self._interval,
            self._tick_count,
            self._last_tension_total,
        )