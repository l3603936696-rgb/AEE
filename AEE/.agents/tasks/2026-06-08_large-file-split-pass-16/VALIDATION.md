# Validation

## 编译检查

```bash
python -m py_compile src/core/drive_tables.py src/core/drive_vector_field.py
python -m py_compile src/memory_hub/insights_db.py src/memory_hub/insights_schema.py src/memory_hub/insights_api.py src/memory_hub/insights.py
```

## Import Smoke Test

```bash
python -c "from src.core.drive_vector_field import compute_drive_field, DriveFieldResult, DRIVE_DIMS; print('drive_vector_field OK')"
python -c "from src.memory_hub.insights import write_insight, recall_insights, get_insight_count; print('insights OK')"
python -c "from src.core.behavior_vector import DRIVE_DIMS; print('behavior_vector OK')"
```

## 测试

```bash
python -m pytest tests/test_source_identity.py tests/test_expression_relief.py -q
```

## Diff Check

```bash
git diff --check -- src/core/drive_vector_field.py src/memory_hub/insights.py
```
