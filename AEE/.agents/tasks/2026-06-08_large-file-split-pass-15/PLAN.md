# Plan

## 文件一：quenching_system.py (556行 → 3模块)

1. **模块 A: `src/quenching/quenching_event.py`** (~90行)
   - `QuenchingEvent` dataclass
   - `QuenchingJournal` class
   - 原文件 import 并 re-export 兼容

2. **模块 B: `src/quenching/quenching_channels.py`** (~280行)
   - 6 个通道函数：`expression_quenching`, `temporal_quenching`, `decision_quenching`, `social_quenching`, `behavioral_quenching`, `structural_quenching`
   - 含通道常量表（BASELINE, DIM_BASE_RATES, BEHAVIOR_EFFECTS）

3. **模块 C: 剩余部分 (~186行) → `apply_all_quenching` 主入口 + 情绪回拉逻辑**
   - 保留在原文件 `quenching_system.py`，清理 import，重导出子模块

## 文件二：semantic_base.py (477行 → 2模块)

1. **模块 A: `src/thinking_system/semantic_tables.py`** (~325行)
   - `DIMENSION_SEMANTICS` dict
   - `ACTION_SEMANTICS` dict
   - `CAUSAL_SEEDS` list

2. **模块 B: 剩余部分 (~152行) → `semantic_base.py`**
   - 5 个 query 函数：`get_dim_meaning`, `get_dim_polarity`, `get_action_essence`, `interpret_delta`, `find_causal_path`, `find_related_seeds`, `check_rule_against_seeds`
   - 保留原文件，清理 import

## 文件三：tetramem_adapter.py (532行 → 2模块)

1. **模块 A: `src/memory_hub/tetramem_persistence.py`** (~190行)
   - `_load_staged`, `_save_staged`
   - `_fallback_write`, `_retrieve_from_staged`
   - `_extract_intent_tag`, `_normalize_tetramem_results`
   - `MEMORIES_STAGED_PATH` 常量

2. **模块 B: 剩余部分 (~342行) → `tetramem_adapter.py`**
   - dataclass 定义（ExperienceLog, StateSnapshot, TopoMetrics）
   - HTTP helper（`_post`, `_get`）
   - 公开 API（`log_experience_with_context`, `execute_sleep_cycle`, `get_topology_metrics`, `retrieve_memories`）
   - Fallback 函数
   - 保留原文件

## 执行顺序

1. 创建子模块目录 `src/quenching/`
2. 写 `quenching_event.py` + `quenching_channels.py`
3. 修改 `quenching_system.py` 为瘦入口
4. 写 `semantic_tables.py`
5. 修改 `semantic_base.py` 为瘦入口
6. 写 `tetramem_persistence.py`
7. 修改 `tetramem_adapter.py` 为瘦入口
8. 运行验证
9. 更新文档
