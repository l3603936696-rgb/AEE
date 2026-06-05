# XIA src/ 重构计划 — 2026-05-10
# 备份: src_backup_20260510/

## 现状
entity_zero_iteration.py (4368行) 包含:
  - EntityState 类 (L424-989)
  - run_pipeline 函数 (L1315-3654, ~2300行)
  - run_language_training_tick (L4170-4368)
  - 各种辅助函数散落在前后

## 拆分方案

### Phase 1: 抽 EntityState → src/core/entity_state.py
  移入: EntityState, _CoreWrapper, _make_core_wrapper, PipelineTrace,
        get_entity_state, reset_entity_state, force_set_state,
        _recover_from_episodes, _interpolate_lookup, _apply_silence_injection
  保留: entity_zero_iteration.py 做兼容层 (from .core.entity_state import *)

### Phase 2: 抽 run_pipeline → src/pipeline/runner.py
  移入: run_pipeline, _compute_prediction_error_map, _build_experience_log,
        _make_fallback_candidates
  保留: entity_zero_iteration.py 兼容导出

### Phase 3: 抽训练函数 → src/training/language_training.py
  移入: run_language_training_tick, mock_llm_callable

### Phase 4: 抽工具函数 → src/pipeline/utils.py
  移入: should_trigger_sleep, _update_behavior_rules, 
        _compute_snapshot_diversity, get_default_drive_params,
        _build_decision_params, _build_output_params

### Phase 5: 清理
  - 删 world_model_LEGACY/ (确认无引用后)
  - 删 emergent_behavior.py (保留 emergent_behavior_v5.py)
  - 统一 import 路径

## 兼容策略
每一步完成后 entity_zero_iteration.py 变成纯 import 重导出：
  from .core.entity_state import EntityState, ...
  from .pipeline.runner import run_pipeline
  from .training.language_training import run_language_training_tick
外部代码 (daemon, tick_engine, tests) 无感知变化。
