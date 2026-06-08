# CURSOR_PROMPT — Pass 20

## 目标

继续大文件拆分，处理 Pass 19 未完成的两个文件：

1. `src/language_system/stereotype_tree.py`（~1158行）
2. `src/language_system/somatic_concept_map.py`（~1143行）

## 约束

- 不改变任何 public API 名称和签名
- 原文件 re-export 子模块内容
- 新模块均低于 400 行（数据字典例外）
- 不使用 if/else 做逻辑分支
- surgical changes only

## 参考

查看 `.agents/tasks/2026-06-08_large-file-split-pass-19/SPEC.md` 了解之前已完成的工作。
