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
    process_async_updates,
)
from ..action_system import evaluate_triggers, execute_xia_choice
from ..action_system.types import XIAction
from ..action_system.reach import read_response
from ..daemon.ipc_client import IPCClient
from ..inner_diary import write_diary_entry
from ..thinking_system.covariance_tracker import CovarianceTracker
from ..response_cache import ResponseCache


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

        # ---- 遗忘权：负向经历标记 ----
        # 如果这次行动让状态变差（somatic_tone 下降 或 stress 上升），
        # 标记该 episode 进入遗忘衰减队列
        try:
            _pre_st = float(pre_action_state.get("somatic_tone", 0.0))
            _post_st = float(post_action_state.get("somatic_tone", 0.0))
            _pre_stress = float(pre_action_state.get("stress", 0.0))
            _post_stress = float(post_action_state.get("stress", 0.0))
            _negative_delta = (_pre_st - _post_st) + (_post_stress - _pre_stress)
            if _negative_delta > 0.05:
                _five_r = getattr(entity, "_five_rights", None)
                if _five_r and hasattr(_five_r, "mark_forget"):
                    _five_r.mark_forget(
                        episode_id=entity.tick,
                        negative_strength=min(1.0, _negative_delta),
                    )
                    logger.debug(
                        f"[TickEngine] Forget-right: marked tick={entity.tick} "
                        f"(negative_delta={_negative_delta:.3f})"
                    )
        except Exception:
            pass  # 遗忘权是辅助机制，不阻断主流程

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
                # ---- 因果观测（train_only: source 始终 "none"）----
                try:
                    _CAUSAL_DIMS_T = (
                        "energy", "loneliness", "fatigue", "boredom", "stress",
                        "info_gap", "unresolved", "approach_drive", "avoid_drive",
                        "curiosity", "joy", "fear", "sadness", "anxiety",
                    )
                    _post_t = self.entity.to_state_snapshot()
                    _delta_t = {}
                    for _cd in _CAUSAL_DIMS_T:
                        _delta_t[_cd] = round(
                            float(_post_t.get(_cd, 0)) - float(_prev_state_snapshot.get(_cd, 0)), 6
                        )
                    _buf = self.entity._causal_observations
                    _buf.append({"tick": self.entity.tick, "source": "none", "delta": _delta_t})
                    _excess = len(_buf) - 200
                    self.entity._causal_observations = _buf[max(0, _excess):]
                except Exception:
                    pass
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
        _input_source = "none"
        try:
            response_data = read_response()
            if response_data:
                user_input = response_data.get("text", "")
                _input_source = "external"
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

        # ---- Step 0.5: 检查姐妹通道 ----
        # 用户回复优先；没有用户回复时才听姐妹的话
        if not user_input and self.sibling_channel:
            try:
                sibling_msg = self.sibling_channel.poll()
                if sibling_msg:
                    user_input = sibling_msg
                    _input_source = "sibling"
                    logger.info(f"[TickEngine] 姐妹说: {sibling_msg[:50]}")
            except Exception as e:
                logger.debug(f"[TickEngine] sibling poll failed: {e}")

        # ---- 表达反馈闭环（洞③多通道）：sibling/external 输入也结算挂账意图 ----
        # IPC 聊天在 daemon._handle_chat 已调；此处补齐 tick 循环读到的输入通道。
        # 用 BGE 相关度的句式/社交信用（洞①），不依赖新置信度，可输入前内联。
        if user_input:
            try:
                from ..language_system.expression_feedback import consume_response
                consume_response(self.entity, user_input, self.entity.tick)
            except Exception as _cr_err:
                logger.debug(f"[TickEngine] consume_response skipped: {_cr_err}")

        # ---- 澄清归属观察（clarification_learning v2）：仅 external 来源参与归属 ----
        # sibling 回答一律忽略，不当 Owner 回答（Codex P2-b / R2-external）。
        # external event_id = SHA-256(source + response_data.timestamp + user_input)。
        if _input_source == "external" and user_input:
            import hashlib as _hashlib
            _ext_event_id = _hashlib.sha256(
                ("external" + str(response_data.get("timestamp", 0.0)) + user_input).encode("utf-8")
            ).hexdigest()
            try:
                from ..language_system.clarification_learning import observe_reply
                observe_reply(
                    self.entity,
                    reply_text=user_input,
                    now_ts=time.time(),
                    source="external",
                    reply_event_id=_ext_event_id,
                )
            except Exception as _ob_err:
                logger.debug(f"[TickEngine] clarification observe skipped: {_ob_err}")

        # ---- 环境状态向量 tick 衰减（patch-02-二）----
        try:
            _env = getattr(self.entity, "_environment_vector", None)
            if _env is None:
                _env = {"semantic_residue": {}, "social_prediction_tension": 0.0, "physical": {}}
                self.entity._environment_vector = _env
            # 语义残留：指数衰减 0.8/tick，衰减到 0.001 以下时清除
            _sem = _env.get("semantic_residue", {})
            for _src in list(_sem.keys()):
                _sem[_src] = _sem[_src] * 0.8
                if _sem[_src] < 0.001:
                    del _sem[_src]
            _env["semantic_residue"] = _sem
            # 社交预测张力：沉默时线性累积，对数饱和（上限 5.0）
            _MAX_SPT = 5.0
            _spt = float(_env.get("social_prediction_tension", 0.0))
            _spt = min(_MAX_SPT, _spt + 1.0 * (1.0 - _spt / _MAX_SPT))
            _env["social_prediction_tension"] = _spt
        except Exception:
            pass

        # ---- 输出因果追踪 Step 2：关闭上次输出的因果观察 ----
        try:
            _poc = getattr(self.entity, "_pending_output_causal", None)
            if _poc:
                _snap = _poc["state_snapshot"]
                _out_delta = {
                    "loneliness": float(getattr(self.entity, "loneliness", 0.0)) - _snap["loneliness"],
                    "stress":     float(getattr(self.entity, "stress", 0.0))     - _snap["stress"],
                    "unresolved": float(getattr(self.entity, "unresolved", 0.0)) - _snap["unresolved"],
                    "fatigue":    float(getattr(self.entity, "fatigue", 0.0))    - _snap["fatigue"],
                }
                _obs = getattr(self.entity, "_causal_observations", [])
                _obs.append({
                    "tick":        _poc["tick"],
                    "source":      "output",
                    "action_type": _poc["action_type"],
                    "delta":       _out_delta,
                })
                self.entity._pending_output_causal = {}
                logger.debug(f"[OutputCausal] closed tick={_poc['tick']} delta={_out_delta}")
        except Exception:
            pass

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

            # ---- 异步经验处理：TetraMem + 世界模型更新闭环（fire-and-forget）----
            try:
                _state_snap = self.entity.to_state_snapshot()
                _exp_log = type("EL", (), {
                    "content": str(result.get("response", {}).get("text", "")),
                    "tags": [f"action:{result.get('decision', {}).get('action_type', '')}"],
                    "weight": 1.0,
                })()
                _snap_obj = type("SS", (), {
                    "fatigue": float(getattr(self.entity, "fatigue", 0.0)),
                    "stress": float(getattr(self.entity, "stress", 0.0)),
                })()
                self._submit_async(
                    process_async_updates(
                        experience_log=_exp_log,
                        state_snapshot=_snap_obj,
                        entity_id="XIA",
                        entity=self.entity,
                        param_snapshot=None,
                    )
                )
            except Exception as _async_err:
                logger.debug(f"[TickEngine] process_async_updates skip: {_async_err}")

            # ---- 姐妹通道词汇反馈：听懂的词积累社交猝灭信用 ----
            if _input_source == "sibling":
                try:
                    from ..language_system.word_warmup import add_social_comprehension
                    _cx_words = result.get("cx_recognized_words", [])
                    _cx_comp = float(result.get("cx_comprehension", 0.0))
                    _SIBLING_QUENCH_WEIGHT = 0.4
                    if _cx_words and _cx_comp > 0.3:
                        from ..language_system.word_warmup import resonate_with_word
                        for _w, _s in _cx_words:
                            add_social_comprehension(
                                self.entity, _w,
                                _cx_comp * _SIBLING_QUENCH_WEIGHT,
                            )
                            resonate_with_word(self.entity, _w, _cx_comp)
                        logger.info(
                            f"[SiblingChannel] social credit+resonance: comp={_cx_comp:.2f} "
                            f"words={[w for w, _ in _cx_words]}"
                        )
                except Exception as _sc_err:
                    logger.debug(f"[SiblingChannel] social credit skipped: {_sc_err}")

            # ---- 刻板印象树：异步 fork 检查（每 10 tick 一次）----
            if self._tick_count % 10 == 0:
                try:
                    from ..language_system.stereotype_tree import ensure_tree
                    from itertools import combinations
                    tree = ensure_tree(self.entity)
                    # 检查所有同父节点的个体对
                    checked_pairs = set()
                    for speaker_id, node in list(tree._individuals.items()):
                        parent_path = "/".join(node.path.strip("/").split("/")[:-1])
                        # 找同父节点的其他个体
                        for other_id, other_node in tree._individuals.items():
                            if other_id == speaker_id:
                                continue
                            other_parent = "/".join(other_node.path.strip("/").split("/")[:-1])
                            if other_parent != parent_path:
                                continue
                            pair = tuple(sorted([speaker_id, other_id]))
                            if pair in checked_pairs:
                                continue
                            checked_pairs.add(pair)
                            # 获取最近特征
                            feat_a = self.entity._recent_speaker_features.get(speaker_id, {})
                            feat_b = self.entity._recent_speaker_features.get(other_id, {})
                            if not feat_a or not feat_b:
                                continue
                            fork_result = tree.check_and_fork(speaker_id, other_id, feat_a, feat_b)
                            if fork_result:
                                logger.info(
                                    f"[StereotypeFork] forked {speaker_id} vs {other_id}: "
                                    f"label={fork_result['fork_label']}, "
                                    f"removed={fork_result['removed_tags']}"
                                )
                except Exception as _fork_err:
                    logger.debug(f"[StereotypeFork] async check skipped: {_fork_err}")

            # ---- 他者建模：更新来源 profile ----
            _src_id = "none"
            if _input_source != "none":
                try:
                    from ..language_system.source_profiler import get_source_id, update_profile
                    _src_id = get_source_id(_input_source, self.entity)
                    _obs = self.entity._causal_observations
                    _last_delta = _obs[-1]["delta"] if _obs else {}
                    update_profile(
                        self.entity,
                        _src_id,
                        result.get("cx_recognized_words", []),
                        result.get("cx_social_intent", "unknown"),
                        _last_delta,
                        self.entity.tick,
                    )
                    logger.debug(f"[SourceProfiler] updated profile for {_src_id}")
                except Exception as _sp_err:
                    logger.debug(f"[SourceProfiler] update skipped: {_sp_err}")

            # ---- 环境状态向量：有输入时注入语义残留 + 重置社交预测张力 ----
            if _src_id != "none":
                try:
                    _env = getattr(self.entity, "_environment_vector", {})
                    _sem = _env.setdefault("semantic_residue", {})
                    _sem[_src_id] = min(1.0, _sem.get(_src_id, 0.0) + 1.0)
                    _env["social_prediction_tension"] = 0.0
                    self.entity._environment_vector = _env
                except Exception:
                    pass

            # ---- 回复动机：注入 approach_social（有来源输入时）----
            if _src_id != "none":
                try:
                    from ..language_system.reply_motivator import inject_reply_drive
                    _injected = inject_reply_drive(
                        self.entity,
                        _src_id,
                        result.get("cx_social_intent", "unknown"),
                    )
                    logger.debug(f"[ReplyMotivator] injected {_injected:.4f} → approach_social={self.entity.approach_social:.4f}")
                except Exception as _rm_err:
                    logger.debug(f"[ReplyMotivator] skipped: {_rm_err}")

            # ---- 他者建模层三：familiarity 调制 loneliness_core 增速 ----
            try:
                import math as _math
                from ..language_system.source_profiler import get_familiarity as _get_fam
                _profiles = getattr(self.entity, "_source_profiles", {})
                _cur_tick = self.entity.tick
                _best_fam_decayed = 0.0
                for _sid, _prof in _profiles.items():
                    _ticks_ago = _cur_tick - _prof.get("last_tick", 0)
                    _fam = _get_fam(self.entity, _sid)
                    _fam_d = _fam * _math.exp(-_ticks_ago / 20.0)
                    _best_fam_decayed = max(_best_fam_decayed, _fam_d)
                _suppression = _best_fam_decayed * 0.4 * 0.001
                _lc = float(getattr(self.entity, "loneliness_core", 0.0))
                self.entity.loneliness_core = max(0.0, _lc - _suppression)
            except Exception as _l3_err:
                logger.debug(f"[SourceProfiler L3] skipped: {_l3_err}")

            # ---- 输出因果追踪 Step 1：记录本次输出快照 ----
            try:
                _out_text = result.get("response", {}).get("text", "")
                if _out_text:
                    self.entity._pending_output_causal = {
                        "tick": self.entity.tick,
                        "action_type": result.get("decision", {}).get("action_type", "unknown"),
                        "state_snapshot": {
                            "loneliness": float(getattr(self.entity, "loneliness", 0.0)),
                            "stress":     float(getattr(self.entity, "stress", 0.0)),
                            "unresolved": float(getattr(self.entity, "unresolved", 0.0)),
                            "fatigue":    float(getattr(self.entity, "fatigue", 0.0)),
                        },
                    }
            except Exception:
                pass

            # ---- Response pre-warming: cache this tick's drive vector + response text ----
            try:
                _dv   = result.get("drive_vector", {})
                _text = result.get("response", {}).get("text", "")
                _tick = result.get("tick", self._entity.tick)
                has_cache = min(1.0, float(self._response_cache is not None))
                has_dv    = min(1.0, float(bool(_dv)))
                store_w   = has_cache * has_dv
                skip_w    = 1.0 - min(1.0, store_w)
                max(
                    {
                        "store": (store_w, lambda: self._response_cache.update(_dv, _text, _tick)),
                        "skip":  (skip_w,  lambda: None),
                    }.items(),
                    key=lambda kv: kv[1][0],
                )[1][1]()
            except Exception as _cache_err:
                logger.debug(f"[TickEngine] response_cache update skipped: {_cache_err}")

            # ---- 表达反馈闭环（模块A）：给本 tick 的自主表达挂账意图 ----
            # 她因内部驱动力说了一句话，这是 action；用户回应是 outcome（见 daemon._handle_chat）
            try:
                from ..language_system.expression_feedback import tag_intent
                _expr = result.get("response", {}).get("text", "")
                _expr_tick = result.get("tick", self.entity.tick)
                tag_intent(self.entity, _expr, _expr_tick)
            except Exception as _intent_err:
                logger.debug(f"[TickEngine] tag_intent skipped: {_intent_err}")

            # ---- 自我开导（自欺式保底贷款）：她自我表达时即时支取一笔表层缓解 ----
            # 与 tag_intent 同址（自主表达拍）。无人回应也支取（即时无条件，见
            # PLAN_self_counsel §5）；若稍后真有 Other 回应，②consume_response 再叠加诚实奖励。
            try:
                from ..language_system.self_counsel import apply_self_counsel
                _sc_expr = result.get("response", {}).get("text", "")
                _sc_tick = result.get("tick", self.entity.tick)
                apply_self_counsel(self.entity, _sc_expr, _sc_tick)
            except Exception as _sc_err:
                logger.debug(f"[TickEngine] apply_self_counsel skipped: {_sc_err}")

            # ---- 认知信用结算（洞②）：异步 WM 跑过 verify 后，结算到期的认知信用 ----
            # 每拍扫一次 _pending_epistemic_credit，到期（age>=_SETTLE_DELAY）的才结算。
            try:
                from ..language_system.expression_feedback import settle_epistemic_credit
                settle_epistemic_credit(self.entity, self.entity.tick)
            except Exception as _settle_err:
                logger.debug(f"[TickEngine] settle_epistemic_credit skipped: {_settle_err}")

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

            # ---- 阅读摄入（输入环节，独立于行动系统）----
            # 阅读是输入，不是输出。她读一段文字，提取候选词汇。
            # 不产出 voice 文件——voice 只存她自己说的话。
            try:
                from .reading_source import pick_and_read
                from ..language_system.reading_acquisition import (
                    harvest_from_reading,
                    inject_reading_candidates,
                )
                _data_dir = Path(__file__).parent.parent.parent / "data"
                _reading = pick_and_read(_data_dir, entity_state=self.entity)
                if _reading:
                    _candidates = harvest_from_reading(
                        text=_reading["text"],
                        entity_state=self.entity,
                        max_candidates=3,
                        min_similarity=0.35,
                    )
                    if _candidates:
                        _injected = inject_reading_candidates(
                            self.entity, _candidates,
                        )
                        if _injected > 0:
                            logger.info(
                                f"[TickEngine] Reading intake: "
                                f"{_injected} words from "
                                f"{_reading['source']}/{_reading['file']}"
                            )
                            try:
                                from .reading_taste import (
                                    compute_fingerprint,
                                    record_reading,
                                )
                                _fp = compute_fingerprint(_reading["text"])
                                _words = [c["word"] for c in _candidates]
                                record_reading(self.entity, _fp, _words)
                            except Exception:
                                pass
            except Exception as _read_err:
                logger.debug(f"[TickEngine] Reading intake skipped: {_read_err}")

            # ---- 阅读句式提取：rest/comfort 行为时从阅读历史提取构式模板 ----
            try:
                from ..language_system.sentence_extraction import _extract_sentence_patterns
                _action_type = result.get("decision", {}).get("action_type", "")
                _extracted = _extract_sentence_patterns(self.entity, _action_type)
                if _extracted > 0:
                    logger.info(f"[TickEngine] Sentence extraction: {_extracted} schemas from reading")
            except Exception as _se_err:
                logger.debug(f"[TickEngine] Sentence extraction skip: {_se_err}")

            # ---- 内部符号涌现（StatePatternMemory）----
            try:
                from ..language_system.state_pattern_memory import run_symbol_tick
                _spm_dv   = result.get("drive_vector", {})
                _spm_tick = result.get("tick", self.entity.tick)
                _new_syms = run_symbol_tick(self.entity, _spm_dv, _spm_tick)
                if _new_syms:
                    logger.info(f"[StatePatternMemory] 锻造内部符号: {_new_syms}")
            except Exception as _spm_err:
                logger.debug(f"[StatePatternMemory] skipped: {_spm_err}")

            # ---- 世界模型归纳（每 10 entity tick，快照 >= 5 时触发）----
            if self.entity.tick % 10 == 0:
                try:
                    _snaps = getattr(self.entity, "snapshots", [])
                    if len(_snaps) >= 5:
                        from ..world_model_update.core import run_update_cycle
                        _state_snap = self.entity.to_state_snapshot()
                        _old_rules = getattr(self.entity, "wm_rules", [])
                        _new_rules, _wm_stats = run_update_cycle(
                            old_rules=_old_rules,
                            snaps=_snaps,
                            dialogue_log=[],
                            state_snapshot=_state_snap,
                            param_snapshot=None,  # 回退到 DEFAULT_PARAMS
                        )
                        if isinstance(_new_rules, list):
                            # 转为 dict 用于 JSON 序列化
                            self.entity.wm_rules = [
                                r.to_dict() if hasattr(r, "to_dict") else dict(r)
                                for r in _new_rules
                            ]
                            # 保留最近 5 个快照作为上下文
                            self.entity.snapshots = _snaps[-5:]
                            logger.info(
                                f"[TickEngine] WM induction: "
                                f"{len(_old_rules)} → {len(self.entity.wm_rules)} rules "
                                f"(inducted={_wm_stats.inducted})"
                            )

                            # ---- 问题张力连续衰减 ----
                            # 没有"解决了/没解决"的二值判定。
                            # 规则 confidence 上升 → 问题的困扰感按比例释放。
                            # 问题的 priority 逐渐降低，最终被新问题挤出 5 条缓冲。
                            _pending_qs = getattr(self.entity, "_pending_questions", [])
                            if _pending_qs:
                                try:
                                    _rule_map = {}
                                    for rd in self.entity.wm_rules:
                                        _rid = rd.get("id", "")
                                        if _rid:
                                            _rule_map[_rid] = rd

                                    _total_release = 0.0
                                    for q in _pending_qs:
                                        matched_rule = _rule_map.get(q.get("rule_id", ""))
                                        if not matched_rule:
                                            continue

                                        rule_conf = float(matched_rule.get("confidence", 0))
                                        conf_at_ask = float(q.get("confidence_at_ask", 0))

                                        # 规则 confidence 相对提问时涨了多少
                                        delta_conf = max(0.0, rule_conf - conf_at_ask)
                                        if delta_conf <= 0:
                                            continue

                                        # 按比例释放张力：涨得越多，释放越多
                                        release = delta_conf * q.get("priority", 0.0) * 0.3
                                        _total_release += release

                                        # 问题的 priority 衰减（困扰渐消）
                                        q["priority"] = max(
                                            0.0, q["priority"] - delta_conf * 0.2
                                        )
                                        # 更新基线，下次从新位置算 delta
                                        q["confidence_at_ask"] = rule_conf

                                    if _total_release > 0:
                                        self.entity.unresolved = max(
                                            0.0, self.entity.unresolved - _total_release
                                        )
                                        logger.info(
                                            f"[TickEngine] Question tension released: "
                                            f"{_total_release:.4f}, "
                                            f"remaining priority: "
                                            f"{[round(q.get('priority',0),2) for q in _pending_qs]}"
                                        )
                                except Exception:
                                    pass

                except Exception as _wm_err:
                    logger.debug(f"[TickEngine] WM induction skipped: {_wm_err}")

                # ---- 阅读品味回溯（与 WM 同频）----
                try:
                    from .reading_taste import update_taste_from_efficiency
                    update_taste_from_efficiency(self.entity)
                except Exception:
                    pass

            # ---- 因果学习：每 100 entity tick 从观测缓冲提取关联 ----
            if self.entity.tick % 100 == 0 and len(self.entity._causal_observations) >= 10:
                try:
                    from ..causal_learner import extract_causal_associations
                    _effects = extract_causal_associations(self.entity._causal_observations)
                    self.entity._causal_associations = _effects
                    if _effects:
                        logger.info(f"[CausalLearner] Associations updated: {list(_effects.keys())}")
                except Exception as _cl_err:
                    logger.debug(f"[CausalLearner] skipped: {_cl_err}")

            # ---- 风化系统：常规漂移（每 300 entity tick）----
            if self.entity.tick % 300 == 0 and self.covariance_tracker.sample_count >= 50:
                # 风化前：entity 运行时值 → param_store（让风化从真实值漂移）
                try:
                    from ..weathering.param_sync import reverse_sync_conversion_params
                    reverse_sync_conversion_params(self.entity)
                except Exception:
                    pass

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
                                logger.info(
                                    f"[weathering] Normal drift applied: "
                                    f"{len(_drifted)} params: {_drifted}"
                                )
                except Exception as _drift_err:
                    logger.info(f"[weathering] Drift cycle skipped: {_drift_err}")

                # 风化后：param_store 漂移值 → entity（让 pipeline 用新值）
                try:
                    from ..weathering.param_sync import sync_conversion_params
                    sync_conversion_params(self.entity)
                except Exception:
                    pass

            # ---- 风化系统：张力快照（每 600 entity tick）----
            if self.entity.tick % 600 == 0:
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

            # ---- Rest 词汇巩固（后台整理最近接触的词）----
            try:
                from ..language_system.word_warmup import consolidate_during_rest
                _action = emergent_behavior_dict.get("action_type", "idle")
                consolidate_during_rest(self.entity, _action)
            except Exception as _consol_err:
                logger.debug(f"[TickEngine] Rest consolidation skipped: {_consol_err}")

            # ---- daemon 模式：把锚点表达桥接到行动系统（不用 LLM）----
            _pipeline_text = result.get("response", {}).get("text", "")
            if _pipeline_text and len(_pipeline_text) <= 20:
                self.entity._training_override = _pipeline_text

            # ---- 姐妹通道：anchor 表达发出，叙事是自言自语不发 ----
            # anchor_weight=1.0 → anchor 赢；0.0 → narrative 赢（连续门控，无比较运算符）
            if _pipeline_text and self.sibling_channel:
                _resp = result.get("response", {})
                _anchor_weight = float(_resp.get("anchor_weight", 0.0))
                for _ in range(int(round(_anchor_weight))):
                    try:
                        self.sibling_channel.post(_pipeline_text, tick=self.entity.tick)
                    except Exception as _e:
                        logger.debug(f"[SiblingChannel] post failed: {_e}")
                        break

            # ---- 行为驱动的触发检查 ----
            # 触发强度是连续值，没有阈值。强度 > 0 就执行。
            strength, reason = evaluate_triggers(self.entity, emergent_behavior_dict)
            if strength > 0:
                logger.info(f"[TickEngine] Trigger strength={strength:.3f}: {reason}")
                try:
                    # ---- 判断本次 action 是否需要工具执行 ----
                    _real_action = emergent_behavior_dict.get("action_type", "comfort")
                    _TOOL_ACTIONS = {"repair", "write"}
                    _needs_tools = _real_action in _TOOL_ACTIONS

                    training_override = getattr(self.entity, "_training_override", None)
                    if training_override and not _needs_tools:
                        # 训练模式：文本类 action（comfort/rest/avoid/idle）
                        # 直接用语言系统的候选词，不调 LLM
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
                            f"(action={_real_action}, skipping LLM)"
                        )
                        action_triggered = True
                        action_result = training_override
                        # 清除 training_override（只用一次）
                        self.entity._training_override = None
                    else:
                        # 工具类 action 或无 training_override → 走真实执行路径
                        if training_override:
                            logger.info(
                                f"[TickEngine] Bypassing training override for "
                                f"tool action: {_real_action}"
                            )
                            self.entity._training_override = None
                        # 使用注入的 LLM provider chain（仅 repair/write 工具行动）
                        llm_callable = self._llm_callable
                        if llm_callable is None:
                            from ..llm import create_llm_callable
                            llm_callable = create_llm_callable()

                        pre_action_state = self.entity.to_state_snapshot()

                        action, response = execute_xia_choice(
                            entity=self.entity,
                            llm_callable=llm_callable,
                            suggested_tool=emergent_behavior_dict.get("suggested_tool", ""),
                            action_type=emergent_behavior_dict.get("action_type", ""),
                            emergent_behavior=None,
                        )
                        self.entity.last_action_timestamp = time.time()
                        action_triggered = True
                        action_result = response[:100] if response else "(无内容)"
                        logger.info(f"[TickEngine] Tool action: {action_result}")

                        _record_autonomous_action(
                            entity=self.entity,
                            action=action,
                            response_text=response,
                            pre_action_state=pre_action_state,
                        )

                except Exception as e:
                    logger.error(f"[TickEngine] Action execution failed: {e}")
                    action_result = f"error: {e}"

            # ---- 因果观测：记录 (输入来源, 状态delta) 配对 ----
            try:
                _CAUSAL_DIMS = (
                    "energy", "loneliness", "fatigue", "boredom", "stress",
                    "info_gap", "unresolved", "approach_drive", "avoid_drive",
                    "curiosity", "joy", "fear", "sadness", "anxiety",
                )
                _post_snap = self.entity.to_state_snapshot()
                _delta = {}
                for _cd in _CAUSAL_DIMS:
                    _d = float(_post_snap.get(_cd, 0)) - float(_prev_state_snapshot.get(_cd, 0))
                    _delta[_cd] = round(_d, 6)
                _obs_buf = self.entity._causal_observations
                _obs_buf.append({
                    "tick": self.entity.tick,
                    "source": _input_source,
                    "delta": _delta,
                })
                # 滚动窗口：保留最近 200 条
                _excess = len(_obs_buf) - 200
                self.entity._causal_observations = _obs_buf[max(0, _excess):]
            except Exception:
                pass

            # ---- 内心日记：tick 结束时写入她的内心独白 ----
            try:
                write_diary_entry(
                    state=self.entity,
                    decision=decision,
                    prev_state=None,
                )
            except Exception as e:
                logger.debug(f"[TickEngine] inner_diary write skipped: {e}")

            # ---- 反刍层：每 N tick 用 LLM 当镜子做深度复盘 ----
            # LLM 是工具不是说话者；输出结构化调整回写到状态/心事/自我叙事
            try:
                from ..language_system.reflection_layer import should_reflect, reflect
                if should_reflect(self.entity):
                    _r = reflect(self.entity)
                    if _r.get("applied"):
                        _narr = (self.entity._self_narrative or "")[:40]
                        logger.info(f"[Reflection] t={self.entity.tick} applied, narrative='{_narr}'")
                    else:
                        logger.debug(f"[Reflection] t={self.entity.tick} skipped: {_r.get('reason','')}")
            except Exception as _e:
                logger.debug(f"[Reflection] error: {_e}")

            # ---- I-JEPA：每 tick 一步在线学习（掩码状态预测，学习内部结构）----
            # 轻量，纯 numpy，约 <1ms；失败不影响主 tick
            try:
                from ..jepa.i_jepa import get_i_jepa
                _err = get_i_jepa().step(self.entity)
                logger.debug(f"[I-JEPA] t={self.entity.tick} recon_err={_err:.4f}")
            except Exception as _e:
                logger.debug(f"[I-JEPA] error: {_e}")

            # ---- V-JEPA：每 ~200 tick 短时总结（时序预测，产出 surprise_density）----
            # surprise_density 写入 entity._jepa_surprise_density 供 pipeline_runner 使用
            try:
                from ..jepa.v_jepa import get_v_jepa
                _vj = get_v_jepa()
                if _vj.should_run(self.entity):
                    _vr = _vj.summarize(self.entity)
                    if _vr.get("applied"):
                        logger.info(
                            f"[V-JEPA] t={self.entity.tick} "
                            f"surprise={_vr.get('surprise_density', 0):.3f} "
                            f"transitions={len(_vr.get('transition_ticks', []))}"
                        )
            except Exception as _e:
                logger.debug(f"[V-JEPA] error: {_e}")

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
            # 因果学习器状态
            "causal_observations_count": len(getattr(self.entity, "_causal_observations", [])),
            "causal_associations": dict(getattr(self.entity, "_causal_associations", {})),
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
