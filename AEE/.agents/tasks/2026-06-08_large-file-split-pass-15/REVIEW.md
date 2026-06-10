# Review

## 变更概览

本批将 3 个超 400 行文件拆分至 400 行以下：

1. `src/quenching_system.py` (556行) → `src/quenching/` 子模块包
2. `src/thinking_system/semantic_base.py` (477行) → `semantic_tables.py` + 瘦入口
3. `src/memory_hub/tetramem_adapter.py` (532行) → `tetramem_persistence.py` + 瘦入口

## 检查项

- [ ] 每个新模块 < 400 行
- [ ] 原文件保留公共 API 入口（向后兼容）
- [ ] 所有 `import` 能正常解析
- [ ] `py_compile` 通过
- [ ] `pytest tests/test_source_identity.py tests/test_expression_relief.py -q` 通过
- [ ] 无新增 if/else 逻辑决策
- [ ] 无行为改变（只拆不重构）
- [ ] 文档已更新
