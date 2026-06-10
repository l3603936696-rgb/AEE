# CURSOR_PROMPT.md — Pass 30: Large File Split

## 任务概述

拆分 5 个超过 400 行的文件。按 PLAN.md 顺序执行。

## 关键约束

1. **不改变 public API**：所有 `__all__` 导出不变，函数/类名不变
2. **同步接回调用点**：每拆分一个文件，立即更新所有 import 调用点
3. **不改变行为**：只做模块拆分，不修改任何逻辑
4. **新文件 < 400 行**：每个新文件也必须低于 400 行

## 执行顺序

1. `s04b_emerge.py` → `s04b_self_mapping.py`（SelfBodyMap + NarrativeGenerator + coherence_meta）
2. `s05_behavior.py` → `s05b_pattern_feedback.py`（BP feedback loop ~92L）
3. `s06a_candidates.py` → `s06a_training_mode.py`（training mode ~80L）
4. `s07a_state_update.py` → `s07a_integrity_tick.py`（integrity tick ~32L）
5. `parameters.py` → `parameters_schema.py`（常量表 ~120L）

## 每步必须完成

1. 读取原文件，找到要提取的函数/类
2. 创建新 helper 文件
3. 修改原文件（删除内容，改为 import）
4. 更新所有调用点的 import 语句
5. 运行验证：py_compile + smoke test + pytest + git diff --check

## 验证标准

```bash
python -m py_compile <new_file.py> <modified_original.py>
python -c "from src.pipeline_runner.stages.<stage> import run_stage; print('OK')"
python -m pytest tests\test_source_identity.py tests\test_expression_relief.py -q
git diff --check -- <changed files>
```

## 完成后

在任务目录写入 `CURSOR_RESULT.md`：改了哪些文件、最终行数、跑了哪些验证。
