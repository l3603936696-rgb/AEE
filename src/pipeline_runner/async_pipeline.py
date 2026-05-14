"""Pipeline async functions — async experience processing, sleep trigger, world model update."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from ..memory_hub import (
    ExperienceLog,
    StateSnapshot,
    log_experience_with_context,
    execute_sleep_cycle,
    get_topology_metrics,
    calculate_memory_pressure_from_topology,
)
from ..world_model_update import run_update_cycle as _wmu_run_update_cycle
from ..world_model_update import CycleStats as _WMUCycleStats
from ..parameter_system.snapshot import ParameterSnapshot
from .utils import _compute_snapshot_diversity

logger = logging.getLogger(__name__)


async def process_async_updates(
    experience_log: ExperienceLog,
    state_snapshot: StateSnapshot,
    entity_id: str = "default",
    entity=None,
    param_snapshot=None,
) -> Optional[Dict[str, Any]]:
    """
    异步经验处理入口。

    在决策管线完成后调用（在决策结果写入快照之后）。
    将经验+状态自然写入 TetraMem，可选读取拓扑并降维为信号。
    状态驱动触发世界模型归纳周期。

    参数：
        entity_id       : 实体唯一标识
        experience_log  : 本轮经验日志
        state_snapshot  : 本轮状态快照
        entity         : EntityState 实例（可选，用于预加载外部记忆到 memory_context）
        param_snapshot  : ParameterSnapshot 实例（可选，用于读取 world_model 触发阈值）
    """
    try:
        # ---- 预加载外部记忆（不阻塞，异步进行）----
        if entity is not None:
            try:
                from ..memory_bias.memory_bias import load_memories_to_entity
                intent = "seek"  # 默认意图，预留
                emotion = 0.0
                if experience_log and hasattr(experience_log, "tags"):
                    tags = getattr(experience_log, "tags", [])
                    for tag in tags:
                        if tag.startswith("intent:"):
                            intent = tag[len("intent:"):]
                            break
                await load_memories_to_entity(
                    entity=entity,
                    intent=intent,
                    emotion=emotion,
                    limit=3,
                )
            except Exception as e:
                logger.debug(f"[EntityZero] Preload memories skipped: {e}")

        await log_experience_with_context(
            entity_id=entity_id,
            experience_log=experience_log,
            state_snapshot=state_snapshot,
        )

        topo = await get_topology_metrics()
        pressure_signal = calculate_memory_pressure_from_topology(topo)
        if pressure_signal is not None:
            return pressure_signal.to_dict()

        # ---- 状态驱动：检查快照累积量，触发世界模型更新 ----
        if entity is not None and param_snapshot is not None:
            try:
                from ..world_model_update.defaults import get_raw_value
                snapshot_count = len(entity.snapshots)
                induction_threshold = int(get_raw_value(
                    param_snapshot,
                    "world_model.induction_min_rounds",
                    5.0,
                ))
                if snapshot_count >= induction_threshold:
                    # 经验质量检查：快照间多样性 CV 低于阈值时强制跳过
                    diversity_ok = True
                    try:
                        cv_thresh = get_raw_value(
                            param_snapshot,
                            "world_model.diversity_cv_threshold",
                            0.08,
                        )
                        diversity_ok = _compute_snapshot_diversity(getattr(entity, "snapshots", [])) >= cv_thresh
                    except Exception:
                        pass  # 检查失败时放行，宁可多学也不漏学
                    if not diversity_ok:
                        logger.debug(
                            f"[EntityZero] WM update skipped: low snapshot diversity "
                            f"(CV < {cv_thresh:.3f})"
                        )
                    else:
                        retention = int(get_raw_value(
                            param_snapshot,
                            "world_model.retention_after_update",
                            5.0,
                        ))
                        # 保存旧规律副本（用于崩塌检测和惯性能量代价计算）
                        old_rules_snapshot = [
                            r.to_dict() if hasattr(r, "to_dict") else dict(r)
                            for r in entity.wm_rules
                        ]
                        _wmu_cycle = await run_world_model_update_cycle_async(
                            old_rules=entity.wm_rules,
                            snaps=entity.snapshots,
                            dialogue_log=[],
                            state_snapshot=state_snapshot,
                            param_snapshot=param_snapshot,
                            embedding_provider=None,
                        )
                        logger.info("[EntityZero] wmu_update ok: %s", {
                            "snapshots_processed": snapshot_count,
                            "new_rules": len(_wmu_cycle[0]) if _wmu_cycle else 0,
                        })
                        # 更新完成后清空已处理的快照，保留最近 N 轮作为上下文
                        old_rule_ids = {r.get("id") if isinstance(r, dict) else getattr(r, "id", None)
                                        for r in entity.wm_rules}
                        # 保留旧 confidence 快照（用于惯性能量代价计算）
                        _old_conf_map = {}
                        for _r in entity.wm_rules:
                            _rid = _r.get("id") if isinstance(_r, dict) else getattr(_r, "id", None)
                            _rconf = float(_r.get("confidence", 0.5) if isinstance(_r, dict) else getattr(_r, "confidence", 0.5))
                            if _rid:
                                _old_conf_map[_rid] = _rconf

                        entity.wm_rules = _wmu_cycle[0] if _wmu_cycle else entity.wm_rules
                        entity.snapshots = entity.snapshots[-retention:] if entity.snapshots else []

                        # 模型惯性能量代价：高惯性规律被显著修改 → 扣减 energy
                        try:
                            from ..world_model_update.model_inertia import compute_inertia, compute_update_energy_cost
                            _total_energy_cost = 0.0
                            for _r in entity.wm_rules:
                                _rid = _r.get("id") if isinstance(_r, dict) else getattr(_r, "id", None)
                                if _rid and _rid in _old_conf_map:
                                    _new_conf = float(_r.get("confidence", 0.5) if isinstance(_r, dict) else getattr(_r, "confidence", 0.5))
                                    _old_c = _old_conf_map[_rid]
                                    if isinstance(_r, dict):
                                        from ..world_model_update.rules import Rule as _Rule
                                        _rule_obj = _Rule.from_dict(_r)
                                    else:
                                        _rule_obj = _r
                                    _inertia = compute_inertia(_rule_obj)
                                    _total_energy_cost += compute_update_energy_cost(_old_c, _new_conf, _inertia)
                            if _total_energy_cost > 0:
                                entity.energy = max(0.0, entity.energy - _total_energy_cost)
                                logger.info("[EntityZero] wmu_inertia_cost: %s", {
                                    "energy_cost": round(_total_energy_cost, 5),
                                })
                        except Exception:
                            pass

                        # ---- 崩塌检测 ----
                        try:
                            from ..weathering.shattering import detect_and_process_shattering
                            from ..weathering.signal_bridge import (
                                make_emotion_weight_fn,
                                make_contradiction_fn,
                                dimensions_to_param_paths,
                            )
                            from ..weathering.drift import apply_acute_drift
                            from ..weathering.param_writer import (
                                write_drifted_params,
                                read_current_params,
                            )
                            from ..world_model_update.model_inertia import compute_inertia

                            # 构建新规律置信度映射（供 contradiction_fn 使用）
                            _new_conf_map = {}
                            for _r in entity.wm_rules:
                                _rid = _r.get("id") if isinstance(_r, dict) else getattr(_r, "id", None)
                                if _rid:
                                    _nc = float(_r.get("confidence", 0.5) if isinstance(_r, dict)
                                                else getattr(_r, "confidence", 0.5))
                                    _new_conf_map[_rid] = _nc

                            # 构建实体状态 dict（供 emotion_fn 使用）
                            _entity_state = {}
                            if hasattr(state_snapshot, "items"):
                                _entity_state = dict(state_snapshot)
                            elif hasattr(state_snapshot, "__dict__"):
                                _entity_state = {
                                    k: getattr(state_snapshot, k, 0.0)
                                    for k in ("loneliness", "energy", "fatigue",
                                              "info_gap", "danger_level",
                                              "approach_drive", "avoid_drive",
                                              "unresolved")
                                }

                            shattering_events = detect_and_process_shattering(
                                old_rules=old_rules_snapshot,
                                new_rules=entity.wm_rules,
                                all_rules=entity.wm_rules,
                                tick=getattr(entity, "tick_index", 0),
                                get_inertia_fn=lambda r: compute_inertia(r) if hasattr(r, "confidence") else 0.5,
                                get_contradiction_fn=make_contradiction_fn(
                                    _old_conf_map, _new_conf_map
                                ),
                                get_emotion_fn=make_emotion_weight_fn(_entity_state),
                            )

                            if shattering_events:
                                # 收集所有崩塌事件影响的参数路径
                                _all_affected = set()
                                _max_force = 0.0
                                _collapse_domain = "general"
                                for evt in shattering_events:
                                    if evt.outcome == "collapsed":
                                        _param_paths = dimensions_to_param_paths(
                                            evt.affected_params
                                        )
                                        _all_affected.update(_param_paths)
                                        if evt.shattering_force >= _max_force:
                                            _max_force = evt.shattering_force
                                            _collapse_domain = evt.domain
                                        logger.info(
                                            f"[weathering] Shattering collapsed: "
                                            f"{evt.rule_id} → {_param_paths}"
                                        )

                                # 域隔离：只保留该域允许影响的参数
                                try:
                                    from ..weathering.domain_map import get_allowed_params
                                    _allowed = get_allowed_params(_collapse_domain)
                                    if _allowed is not None:
                                        _all_affected = _all_affected & set(_allowed)
                                except Exception:
                                    pass  # 过滤失败时放行

                                # 执行急剧漂移 + 写入参数
                                if _all_affected and _max_force > 0:
                                    from ..weathering.registry import get_driftable
                                    _defaults = {}
                                    for _p in _all_affected:
                                        _meta = get_driftable(_p)
                                        if _meta:
                                            _defaults[_p] = _meta.baseline_default
                                    _cur = read_current_params(
                                        list(_all_affected), _defaults
                                    )
                                    _acute_drifted = {}
                                    for _p in _all_affected:
                                        if _p in _cur:
                                            _new_v = apply_acute_drift(
                                                _p, _cur[_p],
                                                -_max_force * 0.1,
                                                getattr(entity, "tick_index", 0),
                                            )
                                            if abs(_new_v - _cur[_p]) > 1e-8:
                                                _acute_drifted[_p] = _new_v
                                    if _acute_drifted:
                                        write_drifted_params(_acute_drifted)
                                        logger.info(
                                            f"[weathering] Acute drift written: "
                                            f"{list(_acute_drifted.keys())}"
                                        )

                        except Exception as e:
                            logger.debug(f"[weathering] Shattering detection skipped: {e}")

                        # Insights 衰减同步：新规则替换旧列表后同步一次
                        try:
                            from ..memory_hub.insights import sync_decay as _sync_decay
                            _sync_decay(entity.wm_rules)
                        except Exception:
                            pass

                        # Insights 升级：找出本轮新升 active 的规则，触发写入
                        if _wmu_cycle:
                            new_rules = _wmu_cycle[0]
                            upgrade_threshold = get_raw_value(
                                param_snapshot,
                                "world_model.upgrade_to_insight_threshold",
                                0.7,
                            )
                            newly_active = [
                                r for r in new_rules
                                if (r.get("status") if isinstance(r, dict) else getattr(r, "status", ""))
                                   == "active"
                                and (r.get("id") if isinstance(r, dict) else getattr(r, "id", None))
                                   not in old_rule_ids
                                and (r.get("confidence", 0.0) if isinstance(r, dict)
                                     else getattr(r, "confidence", 0.0)) >= upgrade_threshold
                            ]
                            if newly_active:
                                try:
                                    from ..memory_hub.insights import write_insight_batch as _write_insight_batch
                                    upgraded = _write_insight_batch(newly_active)
                                    if upgraded > 0:
                                        logger.info(f"[EntityZero] Insights upgraded: {upgraded} rules")
                                except Exception:
                                    pass

                        logger.info(
                            f"[EntityZero] WM update done: {snapshot_count} snaps → "
                            f"{len(entity.wm_rules)} rules, kept {retention} as context"
                        )
            except Exception as e:
                logger.debug(f"[EntityZero] WM update skipped: {e}")

        return None

    except Exception as e:
        logger.error(f"[EntityZero] TetraMem async failed, skipped: {e}")
        return None


async def trigger_sleep_if_needed(
    entity_id: str,
    fatigue: float,
    current_residue: float,
) -> float:
    """
    状态驱动的睡眠触发器。

    此函数本身不决定是否睡眠——决策由 V4 裁决层做出。
    此函数仅执行"睡眠"动作的物理后果（做梦、残留层衰减）。
    """
    try:
        return await execute_sleep_cycle(
            entity_id=entity_id,
            current_residue=current_residue,
        )
    except Exception as e:
        logger.error(f"[EntityZero] Sleep cycle failed, residue unchanged: {e}")
        return current_residue


async def run_world_model_update_cycle_async(
    old_rules: List[Any],
    snaps: List[Any],
    dialogue_log: Any,
    state_snapshot: Any,
    param_snapshot: ParameterSnapshot,
    embedding_provider: Optional[Any] = None,
) -> tuple[List[Any], _WMUCycleStats]:
    """
    世界模型更新异步反思周期主入口（world_model_update 管线）。
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        _wmu_run_update_cycle,
        old_rules,
        snaps,
        dialogue_log,
        state_snapshot,
        param_snapshot,
        embedding_provider,
    )
