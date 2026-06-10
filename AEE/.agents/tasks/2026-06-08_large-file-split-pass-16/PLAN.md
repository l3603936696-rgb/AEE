# Plan

## 文件一：drive_vector_field.py (550行 → 2模块)

1. **模块 A: `src/core/drive_tables.py`** (~280行)
   - `DRIVE_DIMS` 常量列表
   - `DEFAULT_ANTAGONISM_MATRIX` 字典
   - `DEFAULT_ALPHA_K` 字典
   - `_sigmoid`, `_sigmoid_k`, `_clamp` 数学工具函数
   - `_raw_drives_from_entity`, `_drives_from_v1` 数据提取函数

2. **模块 B: 剩余部分** (~270行) → `drive_vector_field.py` 瘦入口
   - `compute_net_drives`, `compute_fragmentation_coefficients`, `compute_behavior_vector`, `compute_drive_field`
   - `DriveFieldResult` dataclass（含 `to_dict`, `dominant_dim`, `tension_level`）
   - `format_drive_field_log`
   - 底部 re-export `DRIVE_DIMS`, `DEFAULT_ANTAGONISM_MATRIX`, `DEFAULT_ALPHA_K`（向后兼容 `behavior_vector.py` 的导入）

## 文件二：insights.py (580行 → 4个文件)

1. **模块 A: `src/memory_hub/insights_db.py`** (~190行)
   - `DB_PATH` 常量
   - `init_db()` 函数
   - `_get_db_path()`
   - `_to_dict()` 辅助函数

2. **模块 B: `src/memory_hub/insights_schema.py`** (~80行)
   - `Insight` dataclass
   - `_infer_type()`, `_extract_situation()` 字段提取函数

3. **模块 C: `src/memory_hub/insights_api.py`** (~220行)
   - `write_insight()`, `write_insight_batch()`
   - `recall_insights()`
   - `sync_decay()`
   - `get_all_insights()`, `get_insight_count()`

4. **独立文件: `src/memory_hub/insights_test.py`** (~110行)
   - 原 `if __name__ == "__main__"` 测试块

5. **瘦入口: `src/memory_hub/insights.py`** (~100行)
   - 从三个子模块 import 所有公开 API
   - 底部 re-export
