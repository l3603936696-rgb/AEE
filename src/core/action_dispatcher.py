"""
ActionDispatcher — 真实行为执行分派器（B 线）

将 emergent_behavior() 的 action_type 语义映射为真实的异步动作。

语义映射规则：
    explore → 联网信息采集（使用已有搜索模块的异步搜索机制）
    rest    → 后台整理（世界模型归纳 vs 记忆整合，由内部强度竞争决定）
    seek / avoid / comfort / idle → 不触发后台动作

设计原则：
    - 不设阈值，只比较强度
    - 分派是 action_type 的语义定义，不是决策规则
    - 所有动作异步执行，不阻塞同步管线
    - 使用已有模块的现有机制（搜索池 / 异步封装 / 睡眠周期）
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .behavior_patterns import BehaviorPattern

logger = logging.getLogger(__name__)

# ============================================================================
# 候选选择 — 行为进化层
# ============================================================================


def select_primitive_candidate(
    action_type: str,
    state: Dict[str, float],
    entity_state: Any = None,
) -> Any:
    """
    根据 emergent_behavior 输出的 action_type，从行为进化池中选择最佳候选。

    候选 = primitive_action(str) 或 BehaviorPattern 实例。
    由 behavior_patterns.select_best_candidate() 做综合评分（drive_match + world_model 预测 + pattern_weight + long_term_bias）。

    返回：
        str 或 BehaviorPattern 或 None
    """
    try:
        from . import behavior_patterns as bp

        candidates = bp.get_pool().get_candidates()
        if not candidates:
            # 池为空：按 action_type 硬映射到 primitive
            return _action_type_to_primitive(action_type)

        scored = [(c, bp.score_candidate(c, state, entity_state=entity_state)) for c in candidates]

        # 按 action_type 过滤（只选与当前 emergent action_type 匹配的）
        # primitive action 的 ACTION_TO_TYPE 映射已包含 type 信息
        def type_matches(c: Any) -> bool:
            if isinstance(c, str):
                return bp.ACTION_TO_TYPE.get(c, "explore") == action_type
            elif hasattr(c, "actions"):
                # BehaviorPattern：取主导动作的 type
                types = [bp.ACTION_TO_TYPE.get(a, "explore") for a in c.actions]
                return types[0] == action_type
            return True

        filtered = [(c, s) for c, s in scored if type_matches(c)]
        if not filtered:
            # 没找到匹配类型，回退到全部候选
            filtered = scored

        # 选最高分
        filtered.sort(key=lambda x: x[1], reverse=True)
        return filtered[0][0]
    except Exception as e:
        logger.warning(f"[select_primitive_candidate] failed: {e}")
        return _action_type_to_primitive(action_type)


def _action_type_to_primitive(action_type: str) -> Optional[str]:
    """fallback：action_type → 单一 primitive"""
    mapping = {
        "explore": "web_search",
        "rest": "file_write",
        "seek": "file_write",
        "avoid": "file_read",
        "comfort": "file_write",
        "idle": None,
    }
    return mapping.get(action_type)


# ============================================================================
# 搜索词提取（内部使用 web_search._build_search_query）
# ============================================================================


def _extract_search_query(
    thought_packet: Optional[Dict[str, Any]],
    semantic_packet_biased: Optional[Dict[str, Any]] = None,
    concept_tags: Optional[List[Dict[str, Any]]] = None,
    wm_context: Optional[Dict[str, Any]] = None,
    state_snapshot: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """
    提取搜索关键词。

    优先从 thought_packet 的 web_search_results 中已有的 query 提取，
    其次从 semantic_packet_biased / concept_tags / wm_context / state_snapshot
    拼装搜索词（通过 web_search._build_search_query）。
    """
    # 优先复用已有搜索 query
    if thought_packet:
        prev_results = thought_packet.get("web_search_results", [])
        if prev_results and isinstance(prev_results, list):
            for r in prev_results:
                if isinstance(r, dict) and r.get("query"):
                    return r["query"]

    # 回退：从语义包等拼装
    if semantic_packet_biased is not None:
        try:
            from ..decision_system.submodules.web_search import _build_search_query as _bsq
            query = _bsq(
                semantic_packet_biased or {},
                concept_tags or [],
                wm_context or {},
                state_snapshot or {},
            )
            return query
        except Exception:
            pass

    return None


# ============================================================================
# explore 分派：联网信息采集
# ============================================================================


def _dispatch_explore(
    entity_state: Any,
    thought_packet: Optional[Dict[str, Any]] = None,
    semantic_packet_biased: Optional[Dict[str, Any]] = None,
    concept_tags: Optional[List[Dict[str, Any]]] = None,
    wm_context: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """
    执行信息采集动作。

    使用已有的 _AsyncSearchRunner + _pending_search_register 机制，
    搜索结果被 drain_pending_searches() 收集，注入下一轮 thought_packet。
    """
    query = _extract_search_query(
        thought_packet=thought_packet,
        semantic_packet_biased=semantic_packet_biased,
        concept_tags=concept_tags,
        wm_context=wm_context,
        state_snapshot=None,
    )
    if not query:
        return None

    try:
        from ..decision_system.submodules.web_search import (
            _AsyncSearchRunner,
            _pending_search_register,
        )

        runner = _AsyncSearchRunner(
            query=query,
            num_results=5,
            timeout=8.0,
            backend=None,
        )
        runner.start()
        _pending_search_register(runner)

        return {
            "action_type": "explore",
            "detail": f"info_gathering:{query}",
            "timestamp": time.time(),
        }
    except Exception as e:
        logger.warning(f"[_dispatch_explore] 搜索启动失败: {e}")
        return {
            "action_type": "explore",
            "detail": f"info_gathering_failed:{e}",
            "timestamp": time.time(),
        }


# ============================================================================
# 世界模型归纳触发
# ============================================================================


def _trigger_world_model_induction(
    entity_state: Any,
    snapshot: Any,
) -> Dict[str, Any]:
    """
    触发异步世界模型归纳。

    使用已有 run_world_model_update_cycle_async 异步封装，
    将新规律通过事件机制通知 entity（由外层调度器负责持久化）。
    """
    def _run():
        try:
            wm_rules = getattr(entity_state, "wm_rules", [])
            snapshots = getattr(entity_state, "snapshots", [])
            state_snap = entity_state.to_state_snapshot()
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                new_rules, stats = loop.run_until_complete(
                    _wmu_async(
                        wm_rules,
                        snapshots,
                        None,
                        state_snap,
                        snapshot,
                        None,
                    )
                )
                logger.info(
                    f"[_trigger_wm_induction] 完成: inducted={stats.inducted}, "
                    f"merged={stats.merged}, verified={stats.verified}"
                )
            finally:
                loop.close()
        except Exception as e:
            logger.warning(f"[_trigger_wm_induction] 异步执行失败: {e}")

    try:
        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        return {
            "action_type": "rest",
            "detail": "world_model_induction",
            "timestamp": time.time(),
        }
    except Exception as e:
        logger.warning(f"[_trigger_wm_induction] 线程启动失败: {e}")
        return {
            "action_type": "rest",
            "detail": f"induction_failed:{e}",
            "timestamp": time.time(),
        }


# ============================================================================
# 记忆整合触发
# ============================================================================


def _trigger_memory_consolidation(
    entity_state: Any,
) -> Dict[str, Any]:
    """
    触发异步记忆整合。

    调用 TetraMem execute_sleep_cycle，
    残差层自然衰减（无需额外参数）。
    """
    def _run():
        try:
            entity_id = getattr(entity_state, "target_locked", "entity_0") or "entity_0"
            current_residue = float(getattr(entity_state, "relief_debt", 0.0))
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                new_residue = loop.run_until_complete(
                    _execute_sleep(entity_id, current_residue)
                )
                logger.info(f"[_trigger_memory_consolidation] 完成: residue={new_residue:.3f}")
            finally:
                loop.close()
        except Exception as e:
            logger.warning(f"[_trigger_memory_consolidation] 异步执行失败: {e}")

    try:
        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        return {
            "action_type": "rest",
            "detail": "memory_consolidation",
            "timestamp": time.time(),
        }
    except Exception as e:
        logger.warning(f"[_trigger_memory_consolidation] 线程启动失败: {e}")
        return {
            "action_type": "rest",
            "detail": f"consolidation_failed:{e}",
            "timestamp": time.time(),
        }


# ============================================================================
# 延迟导入异步包装（避免顶层循环导入）
# ============================================================================


def _get_wmu_async():
    try:
        from ..entity_zero_iteration import run_world_model_update_cycle_async as _f
        return _f
    except Exception:
        return None


def _get_sleep_async():
    try:
        from ..memory_hub import execute_sleep_cycle as _f
        return _f
    except Exception:
        return None


_wmu_async = None
_execute_sleep = None


def _ensure_async_funcs():
    global _wmu_async, _execute_sleep
    if _wmu_async is None:
        _wmu_async = _get_wmu_async()
    if _execute_sleep is None:
        _execute_sleep = _get_sleep_async()


# ============================================================================
# rest 分派：强度竞争
# ============================================================================


def _dispatch_rest(
    entity_state: Any,
    snapshot: Any,
) -> Optional[Dict[str, Any]]:
    """
    rest 时根据内部压力竞争决定后台动作。

    不设阈值——只比较 unresolved 和 boredom 谁更高。
    两者均低于 0.3 → 纯休息，不触发任何动作。
    """
    unresolved = float(getattr(entity_state, "unresolved", 0.0))
    boredom = float(getattr(entity_state, "boredom", 0.0))

    if unresolved < 0.3 and boredom < 0.3:
        return {
            "action_type": "rest",
            "detail": "pure_rest",
            "timestamp": time.time(),
        }

    # 预初始化异步函数
    _ensure_async_funcs()

    if unresolved > boredom:
        return _trigger_world_model_induction(entity_state, snapshot)
    else:
        return _trigger_memory_consolidation(entity_state)


# ============================================================================
# 主入口
# ============================================================================


def dispatch_async_action(
    emergent_behavior: Any,
    entity_state: Any,
    thought_packet: Optional[Dict[str, Any]] = None,
    semantic_packet_biased: Optional[Dict[str, Any]] = None,
    concept_tags: Optional[List[Dict[str, Any]]] = None,
    wm_context: Optional[Dict[str, Any]] = None,
    snapshot: Any = None,
    candidate: Any = None,
) -> List[Dict[str, Any]]:
    """
    根据涌现行为方向，分派真实的异步动作。

    分派逻辑是 action_type 的语义定义，不是决策规则：
        explore → 联网信息采集
        rest    → 后台整理（由强度竞争决定）
        seek / avoid / comfort / idle → 不触发后台动作

    支持 BehaviorPattern 链式执行：若传入 candidate 为 BehaviorPattern，
    则按顺序执行其所有 actions，收集所有结果。

    参数：
        emergent_behavior   : EmergentBehavior 实例或 dict
        entity_state       : EntityCore 实例
        thought_packet     : 本轮思考包（含 web_search_results）
        semantic_packet_biased : 语义包（用于搜索词提取）
        concept_tags       : 概念标签列表（用于搜索词提取）
        wm_context         : 世界模型上下文（用于搜索词提取）
        snapshot          : ParameterSnapshot（用于世界模型归纳）
        candidate          : 已选定的候选（来自 select_primitive_candidate），
                            若为 None 则根据 action_type 自行选择

    返回：
        List[Dict] : dispatched_actions 列表（可能为空）
    """
    if emergent_behavior is None or entity_state is None:
        return []

    action_type = getattr(emergent_behavior, "action_type", None)
    if not action_type:
        return []

    # 若未传入候选，自己选
    if candidate is None:
        state = entity_state.to_state_snapshot() if hasattr(entity_state, "to_state_snapshot") else {}
        candidate = select_primitive_candidate(action_type, state, entity_state)

    dispatched: List[Dict[str, Any]] = []

    # BehaviorPattern 链式执行
    if hasattr(candidate, "actions"):
        # BehaviorPattern 实例
        from .behavior_patterns import BehaviorPattern
        pattern_results: List[Dict[str, Any]] = []
        for sub_action in candidate.actions:
            sub_result = _run_single_action(
                action_type=action_type,
                action=sub_action,
                entity_state=entity_state,
                thought_packet=thought_packet,
                semantic_packet_biased=semantic_packet_biased,
                concept_tags=concept_tags,
                wm_context=wm_context,
                snapshot=snapshot,
            )
            if sub_result:
                dispatched.append(sub_result)
        return dispatched

    # 单动作执行
    if candidate is not None:
        result = _run_single_action(
            action_type=action_type,
            action=candidate,
            entity_state=entity_state,
            thought_packet=thought_packet,
            semantic_packet_biased=semantic_packet_biased,
            concept_tags=concept_tags,
            wm_context=wm_context,
            snapshot=snapshot,
        )
        if result:
            dispatched.append(result)

    return dispatched


def _run_single_action(
    action_type: str,
    action: Any,
    entity_state: Any,
    thought_packet: Optional[Dict[str, Any]] = None,
    semantic_packet_biased: Optional[Dict[str, Any]] = None,
    concept_tags: Optional[List[Dict[str, Any]]] = None,
    wm_context: Optional[Dict[str, Any]] = None,
    snapshot: Any = None,
) -> Optional[Dict[str, Any]]:
    """
    执行单个动作。
    """
    if action_type == "explore":
        return _dispatch_explore(
            entity_state=entity_state,
            thought_packet=thought_packet,
            semantic_packet_biased=semantic_packet_biased,
            concept_tags=concept_tags,
            wm_context=wm_context,
        )
    elif action_type == "rest":
        return _dispatch_rest(entity_state=entity_state, snapshot=snapshot)
    return None
