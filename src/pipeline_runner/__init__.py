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
        debug=debug,
    )
    ctx._trace = _trace
    ctx.t0 = t0
    ctx.trace = trace

    # ---- 管线各阶段按顺序执行 ----
    s01_init.run_stage(ctx, entity)       # 参数快照 + 语言模块初始化
    s02_perception.run_stage(ctx, entity)  # 语义感知 + 驱动力 + 感质
    s02b_input_drive_map.run_input_drive_mapping(ctx, entity)  # 输入→drive空间映射
    run_interpretation_stage(ctx, entity)   # 解释竞争（理解机制核心）
    s02c_delayed_understanding.run_stage(ctx, entity)  # 延迟理解层（反刍）
    s03_think.run_stage(ctx, entity)       # 情绪粒子 + 受限思考 + 情绪衰减
    s04a_meta.run_stage(ctx, entity)       # 元认知状态调整（MC 噪声 / 反锁 / 物理约束）
    s04b_emerge.run_stage(ctx, entity)     # 感知 + 情绪内生 + 行为涌现 + 预测误差
    s05_behavior.run_stage(ctx, entity)    # 连接深度 + 孤独 + 行为模式 + decision 装配
    s06_language.run_stage(ctx, entity)        # 候选词 + 输出（daemon/LLM）+ 语言闭环
    s07a_state_update.run_stage(ctx, entity)   # 状态回写 + BP tick + 消力系统六通道
    s07b_persist.run_stage(ctx, entity)        # 快照 + 记忆 + episode + 时间戳
    s07c_language_finalize.run_stage(ctx, entity)  # L3b 消力闭环 + L6 + 持久化 + 返回值

    return ctx.result_dict


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
