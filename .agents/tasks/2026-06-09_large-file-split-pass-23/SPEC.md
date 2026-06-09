# Task Package: Large File Split Pass 23

## Goal

继续大文件拆分，将 `src/language_system/somatic_concept_map.py`（599行）拆分为 400 行以下，保持原功能不变。

## Background

- 上轮 Pass 22 已将 `sentence_composer.py` 拆至 384 行
- `stereotype_tree.py` 已通过 helpers 辅助降至 386 行
- `somatic_concept_map.py` 仍有 599 行，超出 400 行限制
- 文件功能已通过 `somatic_anchors.py` 数据分离，逻辑层可进一步按函数簇拆分

## Non-Goals

- 不要改动 `somatic_anchors.py`（已是数据模块）
- 不要改动 `bge_analyzer.py`（已有外部依赖）
- 不要启动 daemon 或触发 autonomous action
- 不重构无关逻辑

## Constraints

- 遵循 AGENTS.md / CLAUDE.md 规则
- 不使用 if-else 做逻辑决策
- 每个 magic number 提取为命名常量
- 硬上限 400 行

## Expected Files

- 源文件：`src/language_system/somatic_concept_map.py`（599行）
- 拆分目标：
  - `somatic_concept_map.py`（主模块，核心 API 入口 + 简短辅助，< 400 行）
  - `somatic_concept_map_helpers.py`（BGE 传播层 + 聚类辅助函数，< 400 行）
- 测试文件：无新增测试（功能未变）
- 文档：`XIA_SYSTEMS.md` 更新 language_system 子模块列表

## Acceptance Criteria

- [ ] somatic_concept_map.py < 400 行
- [ ] somatic_concept_map_helpers.py < 400 行
- [ ] `python -m py_compile` 两个文件均通过
- [ ] import smoke test 通过
- [ ] `pytest tests\test_source_identity.py tests\test_expression_relief.py -q` 通过
- [ ] `git diff --check` 无问题
- [ ] XIA_SYSTEMS.md 更新完成

## Open Questions

- 无
