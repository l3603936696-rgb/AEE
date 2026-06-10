# Validation

Commands run from `E:\XIA`:

```powershell
python -m py_compile src\action_system\tools.py src\action_system\tools_nl_extractors.py
python -c "from src.action_system.tools import extract_tool_calls; print(extract_tool_calls('SEARCH: test'))"
python -m pytest tests\test_source_identity.py tests\test_expression_relief.py -q
git diff --check -- src\action_system\tools.py src\action_system\tools_nl_extractors.py
```

Results:
- Compile passed.
- Smoke test returned `[('web_search', {'query': 'test'})]`.
- Target tests passed: `8 passed`.
- Diff check passed with CRLF warnings only.
