# Cursor Prompt

本批拆分 3 个文件：

## quenching_system.py (556行 → 3模块)

1. 创建 `src/quenching/__init__.py`
2. 创建 `src/quenching/quenching_event.py`：含 `QuenchingEvent` dataclass + `QuenchingJournal` class
3. 创建 `src/quenching/quenching_channels.py`：含 6 个通道函数（BASELINE 等常量也放入此模块）
4. 修改 `quenching_system.py`：
   - 删除已移出的内容，保留 `apply_all_quenching` 主入口
   - 底部添加 re-export（向后兼容）：`from .quenching_event import QuenchingEvent, QuenchingJournal; from .quenching_channels import expression_quenching, temporal_quenching, decision_quenching, social_quenching, behavioral_quenching, structural_quenching`
   - 确保 `apply_all_quenching` 函数内部 import 子模块

## semantic_base.py (477行 → 2模块)

1. 创建 `src/thinking_system/semantic_tables.py`：含 `DIMENSION_SEMANTICS`, `ACTION_SEMANTICS`, `CAUSAL_SEEDS`
2. 修改 `semantic_base.py`：
   - 删除常量表，保留所有 query 函数
   - 底部添加 re-export

## tetramem_adapter.py (532行 → 2模块)

1. 创建 `src/memory_hub/tetramem_persistence.py`：含降级读写 helper 函数
2. 修改 `tetramem_adapter.py`：
   - 删除已移出的 helper，保留 dataclass + HTTP helper + 公开 API
   - 底部添加 re-export

验证：每个文件写完后运行 `python -m py_compile <file>`。

完成后运行完整验证并写 `CURSOR_RESULT.md`。
