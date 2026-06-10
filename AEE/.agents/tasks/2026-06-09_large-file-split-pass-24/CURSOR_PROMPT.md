# Cursor Handoff: Large File Split Pass 24

你已完成拆分。

## 已实现的变更

1. `src/state_update/update_engine_helpers.py`（316行）已创建
2. `src/state_update/update_engine_test.py`（184行）已创建
3. `src/state_update/update_engine.py`（271行）已重写
4. `XIA_SYSTEMS.md` 已更新

## 验证命令

```powershell
python -m py_compile src/state_update/update_engine.py
python -m py_compile src/state_update/update_engine_helpers.py
python -m py_compile src/state_update/update_engine_test.py
python -c "from src.state_update.update_engine import update_state; print('OK')"
python -m src.state_update.update_engine_test
python -m pytest tests\test_source_identity.py tests\test_expression_relief.py -q
```

## 边界

- 不要改动 info_queue.py, compute_load.py, dopamine_tone.py
- 不要启动 daemon
