# VALIDATION.md - expression-relief-v1

## Commands

```powershell
python -m pytest tests/test_expression_relief.py -q
python -m pytest tests/test_source_identity.py tests/test_expression_relief.py tests/test_proposition_frame.py tests/test_clarification_memory.py tests/test_clarification_learning.py tests/test_clarification_attribution.py -q
python -m py_compile src/language_system/expression_relief.py src/pipeline_runner/stages/s07c_language_finalize.py scripts/diagnostics/source_relief_validation.py
python scripts/diagnostics/source_relief_validation.py
git diff --check
```

## Results

```text
tests/test_expression_relief.py
4 passed

source + expression + proposition + clarification subset
62 passed, 1 warning

py_compile
passed

diagnostic script
failed: []

git diff --check
passed, CRLF warnings only
```

The warning is from `jieba/pkg_resources` deprecation in existing tests.

## Key Numeric Probe

From `python scripts/diagnostics/source_relief_validation.py`:

| Expression class | accuracy | structure | novelty | relief | boredom_delta | unresolved_delta |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| pure connectors | 0.0500 | 0.7385 | 1.0000 | 0.0369 | -0.00143 | -0.00131 |
| plain naming | 0.9500 | 0.1253 | 1.0000 | 0.1190 | -0.00462 | -0.00072 |
| causal naming | 0.9500 | 0.7385 | 1.0000 | 0.7016 | -0.02722 | -0.02487 |
| repeated causal | 0.9500 | 0.7385 | 0.2000 | 0.1403 | -0.00544 | -0.00497 |

## Acceptance

- Causal structure beats plain naming.
- Repetition discount reduces relief.
- Pure connector strings cannot produce large relief.
- No `loneliness_delta` is returned or applied.
- The hook is after old quenching record, so v1 stays independent from old
  quenching efficiency.

## Live Status

No XIA daemon process was running during this validation. I did not restart or
touch live runtime state. This validation is offline and repeatable.
