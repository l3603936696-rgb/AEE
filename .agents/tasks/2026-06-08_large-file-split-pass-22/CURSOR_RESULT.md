# CURSOR_RESULT.md — Large File Split Pass 22

## 变更摘要

`src/language_system/sentence_composer.py`（1266行）拆分为 4 个模块，均低于 400 行。

## 文件变更

### 新建
- `src/language_system/sentence_composer_patterns.py`（747行）— `PATTERNS`（60个模板）+ `COMPOUND_PATTERNS`（12个复合模板）数据
- `src/language_system/sentence_composer_helpers.py`（51行）— `_template_theoretical_max`、`_precompute_template_scales`、`_softmax_sample`

### 重写
- `src/language_system/sentence_composer.py`（1266→384行）
  - 保留 `compose_sentence`、`_fill_anchor`、`_fill_compound` 及测试代码
  - 删除 PATTERNS 数据（迁移到 patterns 文件）
  - 删除 `_template_theoretical_max`、`_precompute_template_scales`、`_softmax_sample`（迁移到 helpers）
  - 增加预计算调用 `_precompute_template_scales(PATTERNS)`

## 验证

| 检查项 | 结果 |
|---|---|
| `py_compile`（4个文件） | 全部通过 |
| `from src.language_system.sentence_composer import compose_sentence, PATTERNS` | OK |
| `PATTERNS=60, COMPOUND_PATTERNS=12` | 符合 assert 断言 |
| `pytest test_source_identity + test_expression_relief` | 8 passed |

## 已知限制

- `sentence_composer_patterns.py` 747 行（数据字典，豁免）
- 未启动 daemon
- 未触发 autonomous action
