# CURSOR_RESULT.md — Large File Split Pass 21

## 变更摘要

完成 2 个文件的模块拆分，两者均低于 400 行。

## 文件变更

### 新建
- `src/language_system/stereotype_learner_core.py`（133行）
  - `StereotypeLearner` 类
  - `learn_from_conversation()` / `quick_learn()` 方法
- `src/language_system/construction_helpers.py`（216行）
  - `update_construction()` — 替换原 `_update_construction()`
  - `prune_weak_constructions()` — 替换原 `_prune()`
  - `gap_probe_mutate()` — 替换原 `_gap_probe_mutate()`
  - `get_construction_stats()` — 替换原 `get_stats()`
  - `make_construction_score_fn()` / `make_recursive_score_fn()` — scoring helpers

### 重写
- `src/language_system/stereotype_learner.py`（430→204行）
  - 保留 `FeatureExtractor`、`TagInferrer`、便捷函数
  - `from .stereotype_learner_core import StereotypeLearner`
- `src/language_system/construction_grammar.py`（597→376行）
  - 保留主类框架 + seeds + 公开方法
  - 内部调用 `construction_helpers` 中的提取函数

## 验证

| 检查项 | 结果 |
|---|---|
| `py_compile`（4个文件） | 全部通过 |
| `import` smoke test | OK |
| `pytest test_source_identity + test_expression_relief` | 8 passed |
| 所有文件行数 < 400 | 是 |

## 已知限制

- 未启动 daemon
- 未触发 autonomous action
- 未做 end-to-end integration test
- `sentence_composer.py`（1266行）仍是最大文件
