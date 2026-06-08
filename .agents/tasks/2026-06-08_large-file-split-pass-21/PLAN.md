# PLAN.md — Large File Split Pass 21

## 分析

### `stereotype_learner.py`（430行 → 204行）

结构：
- `FeatureExtractor` 类：~103行，纯函数，无内部依赖
- `TagInferrer` 类：~58行，纯函数，无内部依赖
- `StereotypeLearner` 类：~171行，依赖前两个类
- 便捷函数：~33行

拆分方案：`StereotypeLearner` 提取到 `stereotype_learner_core.py`，主文件变 `from .stereotype_learner_core import StereotypeLearner`。

### `construction_grammar.py`（597行 → 376行）

结构：
- 头部 docstring + imports
- `ConstructionLearner` 主类：~546行（包含 5 个可提取的内部方法）
- `_SEED_CONSTRUCTIONS` 常量表：~6行

`ConstructionLearner` 内部方法分析：
- `_update_construction`：~50行 → `update_construction()` in `construction_helpers.py`
- `_gap_probe_mutate`：~54行 → `gap_probe_mutate()` in `construction_helpers.py`
- `_prune`：~20行 → `prune_weak_constructions()` in `construction_helpers.py`
- `get_stats`：~22行 → `get_construction_stats()` in `construction_helpers.py`
- scoring lambdas：~3处 → `make_construction_score_fn` / `make_recursive_score_fn`

## 执行顺序

1. 创建 `stereotype_learner_core.py`（133行）
2. 重写 `stereotype_learner.py`（204行）
3. 创建 `construction_helpers.py`（216行）
4. 重写 `construction_grammar.py`（376行）
5. 验证编译 + 测试

## 调用点不变

- `language_system/__init__.py` → 无需改动
- `delayed_understanding.py` → 无需改动
- `construction_parser.py` → 无需改动
