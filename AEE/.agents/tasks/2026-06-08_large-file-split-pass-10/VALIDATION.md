# Validation

Commands run from `E:\XIA`:

```powershell
$files = Get-ChildItem -Path .\src\daemon -Filter *.py | ForEach-Object { $_.FullName }; python -m py_compile @files
python -m pytest tests\test_source_identity.py tests\test_expression_relief.py -q
git diff --check -- src\daemon\daemon.py src\daemon\http_server.py src\daemon\ipc_chat_handler.py src\daemon\README.md XIA_SYSTEMS.md
```

Results:
- Daemon Python compile passed.
- Target tests passed: `8 passed`.
- Diff check passed with CRLF warnings only.
