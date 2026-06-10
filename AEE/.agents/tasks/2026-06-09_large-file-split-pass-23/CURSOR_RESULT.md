# CURSOR_RESULT.md — Large File Split Pass 23

## 变更摘要

`src/language_system/somatic_concept_map.py`（599行）拆分为 2 个模块，均低于 400 行。

## 文件变更

### 新建
- `src/language_system/somatic_concept_map_helpers.py`（382行）—— BGE传播层 + 聚类辅助 + 匹配评分实现
  - `_ensure_anchor_embeddings()`（懒加载嵌入）
  - `get_somatic_delta()`（传播算法）
  - `_get_state_match_score_impl()`（诊断精度计算）
  - `get_top_matches()`（top-K 候选词）
  - `get_cluster_peers()`（聚类同簇词）
  - `find_closest_anchor()`（BGE 最近锚点）
  - `list_anchors()`
  - `training_exploration_nudge()`（含 NEUTRAL 常量提取）

### 重写
- `src/language_system/somatic_concept_map.py`（599→209行）
  - 保留核心 API：`get_state_match_score`, `get_counter_delta`, `get_match_and_help`, `apply_help_delta`
  - 兼容别名 `get_somatic_expected_score = get_state_match_score`
  - 从 helpers 模块 import 所有传播/辅助函数
  - 主模块专注：匹配验证逻辑 + 帮助施加逻辑

### 文档更新
- `XIA_SYSTEMS.md`：language_system 子模块表新增 `somatic_concept_map_helpers.py`
- `src/language_system/README.md`：子模块表新增 `somatic_concept_map_helpers.py`

## 验证

| 检查项 | 结果 |
| --- | --- |
| `py_compile` somatic_concept_map.py | PASS |
| `py_compile` somatic_concept_map_helpers.py | PASS |
| `from somatic_concept_map import ...` smoke | PASS |
| `pytest test_source_identity + test_expression_relief` | 8 passed |
| `git diff --check` | PASS（仅 LF/CRLF 警告） |
| somatic_concept_map.py < 400 行 | PASS（209行） |
| somatic_concept_map_helpers.py < 400 行 | PASS（382行） |

## 已知限制

- 未启动 daemon
- 未触发 autonomous action
- somatic_anchors.py（数据模块，豁免）保持原样
