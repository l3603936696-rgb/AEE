# SPEC.md — Pass 29: Large File Split

## 背景

源码中多个文件超过 400 行硬限制。本轮 pass-29 拆分 6 个文件，全部位于 `src/language_system/`。

## 目标文件与拆分方案

| 文件 | 当前行数 | 方案 | 新文件 | 预期行数 |
| --- | --- | --- | --- | --- |
| `somatic_anchors.py` | 560 | 数据抽离 | `somatic_anchors_data.py` | ~545 |
| `state_pattern_memory.py` | 453 | 抽离 schema+helpers | `state_pattern_memory_schema.py` ~120L + `state_pattern_memory_helpers.py` ~120L | ~220 |
| `five_rights.py` | 448 | 抽离 helpers | `five_rights_helpers.py` ~80L + `five_rights_schema.py` ~100L | ~280 |
| `quenching.py` | 427 | 抽离 schema | `quenching_schema.py` ~100L | ~330 |
| `word_warmup.py` | 410 | 抽离 helpers+rest | `word_warmup_helpers.py` ~180L + `word_warmup_rest.py` ~100L | ~130 |
| `stereotype_tree.py` | 386 | 抽离 nodes | `stereotype_tree_nodes.py` ~70L | ~320 |

## 约束

- 不改变 public API 名称
- 所有调用点同步接回
- 新文件也低于 400 行
- 不改变行为，只按函数/概念边界拆模块
- 不触动 memory、runtime data、logs、cache、.env

## 验证要求

每批拆分后：
- `python -m py_compile <changed python files>`
- 相关 import smoke test
- `python -m pytest tests\test_source_identity.py tests\test_expression_relief.py -q`
- `git diff --check -- <changed files>`

## 不做事项

- 不启动 daemon
- 不触发真实 autonomous action
- 不做 live 测试
