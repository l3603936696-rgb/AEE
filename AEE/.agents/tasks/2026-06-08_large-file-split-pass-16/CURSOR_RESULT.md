# Cursor Result — Pass 16

## 摘要

本批完成 2 个文件的拆分，所有新模块均低于 400 行。

## 文件变更

### 1. `src/core/drive_vector_field.py` (550行 → 2模块)

**拆分策略**：常量表/数学工具 / 主计算与结果分离。

| 文件 | 行数 | 职责 |
|---|---|---|
| `src/core/drive_tables.py` | 152 | `DRIVE_DIMS`, `DEFAULT_ANTAGONISM_MATRIX`, `DEFAULT_ALPHA_K`, `_sigmoid`, `_sigmoid_k`, `_clamp`, `_raw_drives_from_entity`, `_drives_from_v1` |
| `src/core/drive_vector_field.py` | 245 | 主计算函数 + `DriveFieldResult` dataclass + `format_drive_field_log` |

所有新模块 < 400 行 ✓

### 2. `src/memory_hub/insights.py` (580行 → 4文件)

**拆分策略**：DB层 / Schema层 / API层 / 测试入口分离。

| 文件 | 行数 | 职责 |
|---|---|---|
| `src/memory_hub/insights_db.py` | 81 | `DB_PATH`, `init_db`, `_get_db_path`, `get_db_path` |
| `src/memory_hub/insights_schema.py` | 73 | `Insight` dataclass, `_infer_type`, `_extract_situation`, `_to_dict` |
| `src/memory_hub/insights_api.py` | 241 | `write_insight`, `write_insight_batch`, `recall_insights`, `sync_decay`, `get_all_insights`, `get_insight_count` |
| `src/memory_hub/insights.py` | 33 | 瘦入口（re-export 公开 API） |
| `src/memory_hub/insights_test.py` | 123 | 原 `if __name__` 测试块独立为可执行文件 |

所有新模块 < 400 行 ✓

## 验证结果

### 编译检查 ✓
`python -m py_compile` × 7 个文件 — 全部通过。

### Import Smoke Test ✓
- `drive_vector_field`: `compute_drive_field`, `DriveFieldResult`, `DRIVE_DIMS` — 全 OK
- `behavior_vector`: `DRIVE_DIMS`（通过瘦入口 re-export）— OK
- `insights`: `write_insight`, `recall_insights`, `get_insight_count`, `Insight` — 全 OK

### Pytest ✓
```
tests/test_source_identity.py  4 passed
tests/test_expression_relief.py 4 passed
8 passed in 0.21s
```

## 文档更新

- `XIA_SYSTEMS.md` — 在 `## 13. core` 的子模块表中新增 `drive_tables.py` 行
- `XIA_SYSTEMS.md` — 在 `## 12. memory_hub` 的子模块表中新增 `insights_db.py`、`insights_schema.py`、`insights_api.py`、`insights.py` 行

## 风险与已知限制

- **未做 live daemon 测试**：未启动 daemon 或触发真实 autonomous action
- `insights_api.py` 中的 `write_insight` 参数类型为 `Any`（原接口签名），内部调用 `_to_dict` 兼容 Rule 对象或 dict
- `sync_decay` 中 `DECAY_FLOOR = 0.1` 为硬编码常量，属于已存在设计，不在本次拆分范围内
- `insights_db.py` 的 `init_db` 中使用了 `if _Initialized: return` 惰性初始化（已有逻辑，非本次引入）
