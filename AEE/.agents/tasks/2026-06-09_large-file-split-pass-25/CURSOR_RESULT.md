# CURSOR_RESULT.md — Large File Split Pass 25

## 变更摘要

`src/state_update/compute_connection.py`（779行）拆分为 3 个模块，均低于 400 行。

## 文件变更

### 新建
- `src/state_update/compute_connection_helpers.py`（378行）
  - 共享工具：`_safe_float`, `_get_param`, `_somatic_delta_to_factor`, `_cosine_similarity`, `_build_context_vector`, `_interpolate`
  - Extended 版本：`compute_connection_depth_ex`, `compute_loneliness_target_ex`（含完整中间值）
  - 内部实现：`_compute_base_connection_depth`, `_compute_experience_bias_ex`, `_apply_coherence_modulation`
- `src/state_update/compute_connection_test.py`（193行）
  - 10 个测试用例（含 T9: `_ex` 版本，T10: dual-channel）

### 重写
- `src/state_update/compute_connection.py`（779→175行）
  - 删除内联测试（提取到 _test.py）
  - 删除所有 extended 版本（提取到 _helpers.py）
  - 删除共享工具函数（提取到 _helpers.py）
  - 保留核心 API：`compute_connection_depth`, `compute_loneliness_target`

### 文档更新
- `XIA_SYSTEMS.md`：state_update 子模块表新增 `compute_connection_helpers.py` 和 `compute_connection_test.py`

## 验证

| 检查项 | 结果 |
| --- | --- |
| `py_compile` compute_connection.py | PASS |
| `py_compile` compute_connection_helpers.py | PASS |
| `py_compile` compute_connection_test.py | PASS |
| import smoke | PASS |
| inline tests (10) | 10/10 PASS |
| `pytest test_source_identity + test_expression_relief` | 8 passed |
| compute_connection.py < 400 行 | PASS（175行） |
| compute_connection_helpers.py < 400 行 | PASS（378行） |

## 已知限制

- 未启动 daemon
- 未触发 autonomous action
