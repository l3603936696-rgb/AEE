# Cursor Result — Pass 18

## 摘要

本批处理 2 个文件：

1. `src/language_system/construction_grammar.py` (711行 → 3模块)
2. `src/language_system/recursive_construction.py` (423行 → 2模块)

所有新模块均低于 400 行。

## 文件变更

### 1. `construction_grammar.py` 拆分

**拆分策略**：超参/数据结构/辅助函数 → 子模块，主类保留。

| 文件 | 行数 | 职责 |
|---|---|---|
| `src/language_system/construction_schema.py` | 126 | 超参 + `ExpressionInstance` + `Construction` 类 |
| `src/language_system/construction_utils.py` | 29 | 独立辅助函数 `_infer_anchor_pos` |
| `src/language_system/construction_grammar.py` | 597 | `ConstructionLearner` 类（仍是紧密单类，接近 400 行目标但无法进一步拆分） |

- `ConstructionLearner` 类 ~560 行，是紧密集成的单类（每个方法相互调用，无独立子模块可提取）
- 所有子模块 < 400 行 ✓
- 主文件行数从 711 降至 597（减少 114 行）

### 2. `recursive_construction.py` 拆分

| 文件 | 行数 | 职责 |
|---|---|---|
| `src/language_system/recursive_schema.py` | 153 | `ClausePattern` 类 + 超参 + `ROLE_FILLERS` + `SEED_CLAUSE_PATTERNS` + `_fill_role_from_state` |
| `src/language_system/recursive_construction.py` | 147 | `RecursiveGenerator` 类 + `_softmax_sample` |

所有 < 400 行 ✓

## 验证结果

### py_compile ✓
`python -m py_compile` × 5 个文件全部通过。

### Import Smoke Test ✓
- `construction_grammar`: `ConstructionLearner`, `Construction`, `ExpressionInstance` — OK
- `recursive_construction`: `RecursiveGenerator`, `ClausePattern` — OK

### Pytest ✓
```
8 passed in 0.17s
```

### git diff --check ✓
无实质性错误（Windows CRLF 警告由 git 自动处理）。

## 文档更新

- `XIA_SYSTEMS.md` — language_system 子模块表：`construction_grammar.py` → 3行（加 `construction_schema.py` + `construction_utils.py`）

## 风险与已知限制

- **未做 live daemon 测试**：未启动 daemon 或触发真实 autonomous action
- `construction_grammar.py` 的 `ConstructionLearner` 类（597行）是紧密集成的单类，无法按函数簇拆分，只能拆出外部常量和辅助函数。行数从 711 降至 597。
- `recursive_construction.py` 原未在 `XIA_SYSTEMS.md` 中记录，无需更新
- 原有 `from src.language_system.construction_grammar import ...` 和 `from src.language_system.recursive_construction import ...` 引用**无需修改**（re-export 了所有公开类）
