# Review

## 变更概览

1. `src/core/drive_vector_field.py` (550行) → `drive_tables.py` + 瘦入口
2. `src/memory_hub/insights.py` (580行) → `insights_db.py` + `insights_schema.py` + `insights_api.py` + `insights_test.py` + 瘦入口

## 检查项

- [ ] 每个新模块 < 400 行
- [ ] 原文件保留公共 API 入口（向后兼容）
- [ ] 所有 `import` 能正常解析
- [ ] `py_compile` 通过
- [ ] `pytest tests/test_source_identity.py tests/test_expression_relief.py -q` 通过
- [ ] 无新增 if/else 逻辑决策
- [ ] 无行为改变（只拆不重构）
- [ ] 文档已更新
