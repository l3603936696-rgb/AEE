"""
Entity Zero Iteration — 实体内核迭代器（兼容封装层）

原 4368 行单体文件已拆分为：
  - entity_state.py      — EntityState 类 + 持久化 + 全局单例
  - pipeline_runner.py   — run_pipeline 主函数 + 所有管线步骤
  - language_training.py — run_language_training_tick 训练函数

本文件保持向后兼容：所有外部 import 路径不变。
"""

# ============================================================================
# 实体状态（EntityState、全局单例、持久化）
# ============================================================================
from .entity_state import (
    # 类
    EntityState,
    PipelineTrace,
    _CoreWrapper,
    # 全局单例
    _entity_state_instance,
    get_entity_state,
    reset_entity_state,
    force_set_state,
    # 持久化
    ENTITY_CORE_PATH,
    DATA_DIR,
    # 辅助函数
    _compute_prediction_error_map,
    _build_experience_log,
    _make_core_wrapper,
    _recover_from_episodes,
    _interpolate_lookup,
    _apply_silence_injection,
)

# ============================================================================
# 管线主函数（run_pipeline + 所有步骤）
# ============================================================================
from .pipeline_runner import (
    run_pipeline,
    should_trigger_sleep,
    _compute_snapshot_diversity,
    get_default_drive_params,
    _build_decision_params,
    _build_output_params,
    mock_llm_callable,
    run_world_model_update_cycle_async,
)

# ============================================================================
# 语言训练（run_language_training_tick）
# ============================================================================
from .language_training import (
    run_language_training_tick,
    match_anchor_expression,
)
