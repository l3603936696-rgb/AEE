# REVIEW.md — Large File Split Pass 21

## 变更清单

| 文件 | 变更前 | 变更后 | 类型 |
|---|---|---|---|
| `stereotype_learner.py` | 430行 | 204行 | 重写 |
| `stereotype_learner_core.py` | — | 133行 | 新建 |
| `construction_grammar.py` | 597行 | 376行 | 重写 |
| `construction_helpers.py` | — | 216行 | 新建 |

## 风险评估

- **低风险**：两处拆分都是按方法/函数边界提取，不改变任何逻辑
- 无 API 签名变更
- 调用点（`__init__.py`、`delayed_understanding.py`）无需改动
- 所有 `import` 通过 `from .xxx import` 局部导入，避免循环依赖

## 验证结果

- `python -m py_compile`：全部通过
- `from src.language_system import ConstructionLearner, StereotypeLearner`：OK
- `pytest tests/test_source_identity.py tests/test_expression_relief.py`：8 passed

## 剩余超 400 行文件（优先级）

1. `sentence_composer.py` — 1266行
2. `stereotype_tree.py` — 1043行（Pass 20 已部分处理）
3. `behavior_patterns.py` — 920行
4. `thinking_system.py` — 901行
5. `episodes_db.py` — 890行
