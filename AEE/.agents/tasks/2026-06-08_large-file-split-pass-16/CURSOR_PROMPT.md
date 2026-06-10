# Cursor Prompt

本批拆分 2 个文件：

## 1. drive_vector_field.py (550行)

1. 创建 `src/core/drive_tables.py`：含 `DRIVE_DIMS`、`DEFAULT_ANTAGONISM_MATRIX`、`DEFAULT_ALPHA_K`、`_sigmoid`、`_sigmoid_k`、`_clamp`、`_raw_drives_from_entity`、`_drives_from_v1`
2. 修改 `src/core/drive_vector_field.py`：
   - 删除已移出的内容，保留主计算函数、`DriveFieldResult` dataclass、`format_drive_field_log`
   - 顶部 `from .drive_tables import DRIVE_DIMS, DEFAULT_ANTAGONISM_MATRIX, DEFAULT_ALPHA_K, _sigmoid, _sigmoid_k, _clamp, _raw_drives_from_entity, _drives_from_v1`
   - 底部 re-export `DRIVE_DIMS`（`behavior_vector.py` 依赖）
3. 验证 `behavior_vector.py` 的 `from src.core.drive_vector_field import DRIVE_DIMS` 仍能工作

## 2. insights.py (580行)

1. 创建 `src/memory_hub/insights_db.py`：含 `DB_PATH`、`_get_db_path`、`init_db`、`_to_dict`
2. 创建 `src/memory_hub/insights_schema.py`：含 `Insight` dataclass、`_infer_type`、`_extract_situation`
3. 创建 `src/memory_hub/insights_api.py`：含 `write_insight`、`write_insight_batch`、`recall_insights`、`sync_decay`、`get_all_insights`、`get_insight_count`
4. 创建 `src/memory_hub/insights_test.py`：含原 `if __name__` 测试块（将顶层变量如 `DB_PATH` 作为参数传入）
5. 修改 `src/memory_hub/insights.py` 为瘦入口，从三个子模块 import 并 re-export

完成后运行验证并写 `CURSOR_RESULT.md`。
