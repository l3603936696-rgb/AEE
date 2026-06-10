# Task Package: Large File Split Pass 24

## Goal

继续大文件拆分，将 `src/state_update/update_engine.py`（716行）拆分，主模块保留 < 400 行。

## Background

- `update_engine.py` 包含一个 168 行的内联测试（`if __name__ == "__main__"`）和 342 行的主函数
- 内联测试可以提取到独立文件
- 主函数本身是单入口函数（`update_state`），已通过子模块（`info_queue`, `compute_load`, `dopamine_tone` 等）拆解过，剩余是入口编排逻辑

## Non-Goals

- 不改动子模块（`info_queue.py`, `compute_load.py`, `dopamine_tone.py`, `compute_coherence.py`）
- 不改动 `world_model_update/resolve.py`
- 不启动 daemon
- 不重构逻辑

## Expected Files

- `src/state_update/update_engine.py` → 约 300 行（主模块，删除内联测试）
- `src/state_update/update_engine_test.py` → 约 168 行（内联测试提取）
- 测试文件：可选 `tests/test_update_engine.py`

## Acceptance Criteria

- [ ] update_engine.py < 400 行
- [ ] `python -m py_compile` 通过
- [ ] import smoke test 通过
- [ ] `pytest tests\test_source_identity.py tests\test_expression_relief.py -q` 通过
- [ ] `git diff --check` 无问题
