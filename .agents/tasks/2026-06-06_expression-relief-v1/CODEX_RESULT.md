# CODEX_RESULT.md - expression-relief-v1

## Implemented

- Added `src/language_system/expression_relief.py`.
- Hooked expression relief into `s07c_language_finalize.py` as L3c.
- Added `tests/test_expression_relief.py`.
- Added shared diagnostic probe:
  `scripts/diagnostics/source_relief_validation.py`.

## Important Review Fix

Initial implementation let `logic` words contribute to both structure and
accuracy. That allowed strings such as `because/therefore/but` in Chinese to
earn too much relief.

Fix: accuracy now only scans content/somatic categories:

- `body`
- `emotion`
- `social`
- `cognitive`
- `existential`
- `micro`

Logic/time/degree/question words can still shape structure, but cannot make an
expression look accurate by themselves.

## Files

- `src/language_system/expression_relief.py`
- `src/pipeline_runner/stages/s07c_language_finalize.py`
- `tests/test_expression_relief.py`
- `scripts/diagnostics/source_relief_validation.py`

## Residual Risk

v1 still uses connector and length heuristics. It is good enough to test the
forward-relief path, but not good enough to judge real causal understanding.
Do not use it as evidence that XIA understands causal propositions.
