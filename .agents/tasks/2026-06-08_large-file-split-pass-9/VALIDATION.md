# Validation

Commands run from `E:\XIA`:

```powershell
$files = Get-ChildItem -Path .\src\daemon -Filter *.py | ForEach-Object { $_.FullName }; python -m py_compile @files
python -m pytest tests\test_source_identity.py tests\test_expression_relief.py -q
git diff --check -- src\daemon\tick_engine.py src\daemon\action_execution.py src\daemon\async_updates.py src\daemon\periodic_maintenance.py src\daemon\reflection_jepa_tick.py src\daemon\sibling_tick.py src\daemon\tick_input.py src\daemon\tick_status.py src\daemon\world_model_tick.py src\daemon\README.md XIA_SYSTEMS.md
```

Results:
- Daemon Python compile passed.
- Target tests passed: `8 passed`.
- Diff check passed with CRLF warnings only.
