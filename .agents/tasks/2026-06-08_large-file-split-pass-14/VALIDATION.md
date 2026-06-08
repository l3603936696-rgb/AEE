# Validation

Commands run from `E:\XIA`:

```powershell
python -m py_compile src\language_training.py src\language_anchor_match.py
python -c "from src.language_training import run_language_training_tick; from src.language_anchor_match import match_anchor_expression; print(run_language_training_tick.__name__, match_anchor_expression.__name__)"
```

Results:
- Compile passed.
- Import smoke printed `run_language_training_tick match_anchor_expression`.
