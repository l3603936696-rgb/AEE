"""管线主函数 — run_pipeline（薄编排器）

原 3600 行单体文件已拆分为 10 个阶段模块（s01_init.py … s07c_language_finalize.py）。
本文件仅负责：
  1. 编排各阶段的调用顺序
  2. 定义 _trace 闭包并注入 PipelineContext
  3. 保持对外接口不变（函数签名、返回值、re-exports）
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from ..entity_state import EntityState, PipelineTrace, get_entity_state
from .context import make_context
from .helpers import DATA_DIR, ENTITY_CORE_PATH  # noqa: F401  (re-export)
from .stages import s01_init, s02_perception, s02b_input_drive_map, s02c_delayed_understanding, s03_think
from .stages import s04a_meta, s04b_emerge, s05_behavior
from .stages import s06_language
from .stages import s07a_state_update, s07b_persist, s07c_language_finalize
from ..language_system.interpretation_competition import run_interpretation_stage
from ..observability import get_registry, observe

logger = logging.getLogger(__name__)


# ============================================================================
# 写入安全防护白名单（保留在此处供外部代码或旧版测试直接引用）
# ============================================================================
_DRIVE_WRITE_WHITELIST = frozenset({
    "energy", "loneliness", "loneliness_core", "loneliness_surface",
    "unresolved", "boredom", "fatigue", "stress", "relief_debt", "pain",
    "info_gap", "external_change_rate",
    "somatic_tone", "danger_level", "approach_drive", "avoid_drive",
    "approach_social", "approach_explore", "approach_urgency",
    "joy", "anger", "fear", "sadness", "disgust", "anxiety", "surprise",
    "curiosity", "serenity", "excitement",
})


def run_pipeline(
    raw_input: Optional[str] = None,
    entity_state: Optional[EntityState] = None,
    params_override: Optional[Dict[str, Any]] = None,
    llm_callable: Optional[Any] = None,
    debug: bool = False,
    daemon_mode: bool = False,
    no_llm: bool = False,
    source_identity: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    同步管线主入口。

    参数：
        raw_input       : 用户输入文本（外部输入时）
        entity_state    : 实体内核状态（若为 None，使用全局单例）
        params_override : 参数覆盖（用于测试）
        llm_callable    : LLM 调用函数（若为 None，使用 output_layer 默认）
        debug           : 是否打印调试追踪
        daemon_mode     : 后台 tick 模式，跳过 LLM 输出步骤
        no_llm          : 对话模式跳过 LLM，强制走锚点/叙事路径（v11.6）
        source_identity : 来源身份包（speaker_id/content_origin/source_id）

    返回：
        {
            "response": {"text": str, "confidence": float, "generation_time_ms": int},
            "decision": {"action_type": str, "target": str, "priority": float, "payload": dict},
            "intent_repr": dict,
            "state_snapshot": dict,
            "trace": List[PipelineTrace],
            "tick": int,
            ...
        }
    """
    t0 = time.time()
    entity = entity_state or get_entity_state()
    trace: List[PipelineTrace] = []

    # 可观测性：同步当前 tick 到注册表
    current_tick = getattr(entity, "tick", 0)
    reg = get_registry()
    reg.set_tick(current_tick)

    # 清除上轮帮助事件和元认知事件（每 tick 只保留当轮产生的事件）
    if hasattr(entity, "_last_help_event"):
        entity._last_help_event = None
    if hasattr(entity, "_last_meta_event"):
        entity._last_meta_event = None

    def _trace(step: str, ok: bool, data: Dict[str, Any] = None, error: str = "") -> PipelineTrace:
        t = PipelineTrace(
            step=step,
            elapsed_ms=round((time.time() - t0) * 1000, 2),
            ok=ok,
            data=data or {},
            error=error,
        )
        if debug:
            print(f"  [{t.elapsed_ms:.1f}ms] {step}: {'OK' if ok else 'FAIL'} {error}")
        trace.append(t)
        return t

    ctx = make_context(
        raw_input=raw_input,
        daemon_mode=daemon_mode,
        no_llm=no_llm,
        llm_callable=llm_callable,
        params_override=params_override,
        source_identity=source_identity,
        debug=debug,
    )
    ctx._trace = _trace
    ctx.t0 = t0
    ctx.trace = trace

    # ---- 管线各阶段按顺序执行（带可观测性）----
    _run_stage(reg, "pipeline:s01_init",     s01_init.run_stage,      ctx, entity)
    _run_stage(reg, "pipeline:s02_perception",     s02_perception.run_stage,     ctx, entity)
    _run_stage(reg, "pipeline:s02b_drive_map",     s02b_input_drive_map.run_input_drive_mapping, ctx, entity)
    _run_stage(reg, "pipeline:s02c_interpret",      run_interpretation_stage,     ctx, entity)
    _run_stage(reg, "pipeline:s02c_delayed",      s02c_delayed_understanding.run_stage, ctx, entity)
    _run_stage(reg, "pipeline:s03_think",         s03_think.run_stage,          ctx, entity)
    _run_stage(reg, "pipeline:s04a_meta",         s04a_meta.run_stage,          ctx, entity)
    _run_stage(reg, "pipeline:s04b_emerge",        s04b_emerge.run_stage,         ctx, entity)
    _run_stage(reg, "pipeline:s05_behavior",        s05_behavior.run_stage,         ctx, entity)
    _run_stage(reg, "pipeline:s06_language",        s06_language.run_stage,         ctx, entity)
    _run_stage(reg, "pipeline:s07a_state_update",  s07a_state_update.run_stage,    ctx, entity)
    _run_stage(reg, "pipeline:s07b_persist",        s07b_persist.run_stage,         ctx, entity)
    _run_stage(reg, "pipeline:s07c_language_finalize", s07c_language_finalize.run_stage, ctx, entity)

    return ctx.result_dict


def _run_stage(
    reg,
    name: str,
    func,
    ctx,
    entity,
) -> None:
    """执行单个 stage 并记录可观测性。"""
    import time as _time
    start = _time.perf_counter()
    ok = True
    err_type = ""
    err_val = ""
    try:
        func(ctx, entity)
    except Exception as exc:
        ok = False
        err_type = type(exc).__name__
        err_val = str(exc)
        raise
    finally:
        dur = (_time.perf_counter() - start) * 1000.0
        try:
            reg.record_call(
                name=name,
                category="pipeline_stage",
                success=ok,
                duration_ms=dur,
                error_type=err_type,
                error_summary=err_val,
            )
        except Exception:
            pass


# ============================================================================
# 子模块导入（保持对外接口不变）
# ============================================================================

# 异步管线
from .async_pipeline import (  # noqa: E402, F401
    process_async_updates,
    trigger_sleep_if_needed as _trigger_sleep_async,
    run_world_model_update_cycle_async,
)

# 独立工具函数
from .utils import (  # noqa: E402, F401
    should_trigger_sleep,
    _update_behavior_rules,
    _compute_snapshot_diversity,
    get_default_drive_params,
    _build_decision_params,
    _build_output_params,
    mock_llm_callable,
    _process_tool_gaps,
)
