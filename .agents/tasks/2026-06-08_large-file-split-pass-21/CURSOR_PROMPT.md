# CURSOR_PROMPT.md — Large File Split Pass 21

## 目标

拆分 `stereotype_learner.py` 和 `construction_grammar.py`，两者均低于 400 行。

## `stereotype_learner.py` 拆分

- `stereotype_learner_core.py`（new, ~133行）：`StereotypeLearner` 类 + 两个方法
- `stereotype_learner.py`（rewrite, ~204行）：保留 `FeatureExtractor`、`TagInferrer`、便捷函数，import `StereotypeLearner` from core

## `construction_grammar.py` 拆分

- `construction_helpers.py`（new, ~216行）：`_update_construction` → `update_construction()`，`_gap_probe_mutate` → `gap_probe_mutate()`，`_prune` → `prune_weak_constructions()`，scoring helpers，`get_stats` → `get_construction_stats()`
- `construction_grammar.py`（rewrite, ~376行）：主类 + seeds + 公开方法，内部调用 helpers

## 验证

```bash
python -m py_compile src/language_system/stereotype_learner.py src/language_system/stereotype_learner_core.py src/language_system/construction_grammar.py src/language_system/construction_helpers.py
python -c "from src.language_system import ConstructionLearner, StereotypeLearner"
python -m pytest tests/test_source_identity.py tests/test_expression_relief.py -q
```

## 约束

- public API 名称和签名不变
- 新模块均低于 400 行
- 不改变任何调用点
