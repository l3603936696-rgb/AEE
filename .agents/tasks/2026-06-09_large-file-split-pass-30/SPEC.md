# SPEC.md — Pass 30: Large File Split

## 背景

源码中仍有多个文件超过 400 行。本轮 pass-30 专注拆分 pipeline stages 和 parameter_system。

## 目标文件与拆分方案

| 文件 | 当前行数 | 方案 | 提取到 | 预期行数 |
| --- | --- | --- | --- | --- |
| `pipeline_runner/stages/s04b_emerge.py` | 438 | 提取 self-mapping | `s04b_self_mapping.py` ~45L | ~393 |
| `pipeline_runner/stages/s05_behavior.py` | 423 | 提取 pattern feedback | `s05b_pattern_feedback.py` ~92L | ~331 |
| `pipeline_runner/stages/s06a_candidates.py` | 406 | 提取 training mode | `s06a_training_mode.py` ~80L | ~326 |
| `pipeline_runner/stages/s07a_state_update.py` | 410 | 提取 integrity tick | `s07a_integrity_tick.py` ~32L | ~378 |
| `parameter_system/parameters.py` | 437 | 提取常量表 | `parameters_schema.py` ~120L | ~317 |
| `parameter_system/governance.py` | 401 | 保持不分（边界不清晰） | — | 401（豁免） |

## 约束

- 不改变 public API 名称
- 所有调用点同步接回
- 不改变行为，只按函数/概念边界拆模块
- 新文件也低于 400 行
- 不触动 memory、runtime data、logs、cache、.env

## 验证要求

每批拆分后：
- `python -m py_compile <changed python files>`
- 相关 import smoke test
- `python -m pytest tests\test_source_identity.py tests\test_expression_relief.py -q`
- `git diff --check -- <changed files>`
