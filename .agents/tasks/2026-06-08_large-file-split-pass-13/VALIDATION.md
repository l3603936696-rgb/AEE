# Validation

Commands run from `E:\XIA`:

```powershell
python -m py_compile src\language_system\narrative_fragments.py src\language_system\narrative_context.py
python -c "from src.language_system.narrative_fragments import try_narrative_expression; print(try_narrative_expression.__name__)"
```

Results:
- Compile passed.
- Import smoke printed `try_narrative_expression`.
