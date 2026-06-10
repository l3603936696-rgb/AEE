# SPEC.md — Large File Split Pass 21

## 目标

拆分 `src/language_system/stereotype_learner.py`（430行）和 `src/language_system/construction_grammar.py`（597行），使两者均低于 400 行。

## 约束

- 不改变 public API 名称和签名
- 新模块均低于 400 行
- 不使用 if/else 做逻辑分支
- surgical changes only

## `stereotype_learner.py` 拆分方案

主文件保留 3 个类中的 2 个（`FeatureExtractor` + `TagInferrer`），将 `StereotypeLearner` 提取到 `stereotype_learner_core.py`。

```
stereotype_learner.py (277行):
  - docstring + imports
  - FeatureExtractor (103行)
  - TagInferrer (58行)
  - convenience functions (33行)
  + from .stereotype_learner_core import StereotypeLearner

stereotype_learner_core.py (new, ~175行):
  - StereotypeLearner class
  - learn_from_conversation / quick_learn methods
```

## `construction_grammar.py` 拆分方案

提取常量表和解析器为独立模块。

```
construction_grammar.py (保留 ~350行):
  - docstring + imports
  - SentenceConstruction / ConstructionGrammar core
  - learning + matching methods

construction_patterns.py (new, ~200行):
  - CONSTRUCTION_PATTERNS (list of pattern dicts)
  - DEFAULT_CONSTRUCTION_PARAMS
  - PATTERN_METADATA

construction_parser.py (已有，~130行被引用):
  - keep as-is, imported by construction_grammar.py
```

## 调用点（不变）

- `src/language_system/__init__.py` → `from .stereotype_learner import StereotypeLearner, learn_speaker, quick_learn, init_tree_from_memory`
- `src/language_system/delayed_understanding.py` → `from .stereotype_learner import quick_learn`
- `src/language_system/construction_parser.py` → `from .construction_grammar import SentenceConstruction`
