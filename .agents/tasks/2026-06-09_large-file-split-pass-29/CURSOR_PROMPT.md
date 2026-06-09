# CURSOR_PROMPT.md — Pass 29: Large File Split

## 任务概述

拆分 `src/language_system/` 下 6 个超过 400 行的文件，按 PLAN.md 顺序执行。

## 关键约束

1. **不改变 public API**：所有 `__all__` 导出不变，函数/类名不变
2. **同步接回调用点**：每拆分一个文件，立即更新所有 import 调用点
3. **不改变行为**：只做模块拆分，不修改任何逻辑
4. **新文件 < 400 行**：每个新文件也必须低于 400 行
5. **禁止 if-else 决策**：遵守项目 no-if-else 规则（但数据拆分不受此限）

## 执行顺序

1. `somatic_anchors.py` → `somatic_anchors_data.py`（数据抽离，thin re-export）
2. `state_pattern_memory.py` → `state_pattern_memory_schema.py` + `state_pattern_memory_helpers.py`
3. `five_rights.py` → `five_rights_schema.py` + `five_rights_helpers.py`
4. `quenching.py` → `quenching_schema.py`
5. `word_warmup.py` → `word_warmup_helpers.py` + `word_warmup_rest.py`
6. `stereotype_tree.py` → `stereotype_tree_nodes.py`

## 每步必须完成

1. 读取原文件
2. 创建新 helper 文件
3. 修改原文件（删内容，改为 import）
4. 更新所有调用点的 import 语句
5. 运行验证：`python -m py_compile` + smoke test + `git diff --check`
6. 更新 `XIA_SYSTEMS.md` submodule 列表

## 不要做

- 不要启动 daemon
- 不要触发 autonomous action
- 不要改与拆分无关的代码
- 不要引入新的 if-else 决策逻辑
- 不要删除任何注释或 docstring

## 验证标准

```bash
# 每个文件拆分后
python -m py_compile <new_file.py> <modified_original.py>
python -c "from src.language_system import <OriginalClass>; print('OK')"
python -m pytest tests\test_source_identity.py tests\test_expression_relief.py -q
git diff --check -- <changed files>
```

## 完成后

在任务目录写入 `CURSOR_RESULT.md`：
- 改了哪些文件
- 最终行数
- 跑了哪些验证
- 未做哪些 live 测试
