# PLAN.md — Pass 30 执行计划

## 执行顺序

每次只处理一个文件，验证通过后再处理下一个。

### 步骤 1: `pipeline_runner/stages/s04b_emerge.py` (438L → ~393L)

- 提取 `SelfBodyMap` + `NarrativeGenerator` + `coherence_meta` → `s04b_self_mapping.py` (~45L)
- `tick_engine.py` 已确认 441L，提取 somatic_driver → `somatic_driver.py` (~15L)，主文件 ~426L（仍超）
- **实际策略**：先不动 tick_engine（已排入下一批），专注 pipeline stages

### 步骤 2: `pipeline_runner/stages/s05_behavior.py` (423L → ~331L)

- 提取 `BP feedback loop` (lines 277-368, ~92L) → `s05b_pattern_feedback.py`
- `s05_behavior.py` 剩余 ~331L

### 步骤 3: `pipeline_runner/stages/s06a_candidates.py` (406L → ~326L)

- 提取训练模式管线 (lines 297-376, ~80L) → `s06a_training_mode.py`
- `s06a_candidates.py` 剩余 ~326L

### 步骤 4: `pipeline_runner/stages/s07a_state_update.py` (410L → ~378L)

- 提取 integrity tick (lines 368-399, ~32L) → `s07a_integrity_tick.py`
- `s07a_state_update.py` 剩余 ~378L

### 步骤 5: `parameter_system/parameters.py` (437L → ~317L)

- 提取常量 + schema → `parameters_schema.py` (~120L)
- 主文件剩余 ~317L

## 文档更新

- `XIA_SYSTEMS.md` submodule 列表
- 对应 subsystem README（如有）
