# Task Package: expression-relief-v1

## Goal

Give XIA's own expression a small forward-computed relief effect.

The old quenching path measures state movement after speaking. That signal is
too weak for a single utterance because boredom and unresolved are slow
variables. v1 adds a separate forward estimate: an expression that accurately
names the current state, is not too repetitive, and has some logical structure
can slightly reduce boredom and unresolved immediately.

## Scope

- New module: `src/language_system/expression_relief.py`
- Pipeline hook: `src/pipeline_runner/stages/s07c_language_finalize.py`
- Tests: `tests/test_expression_relief.py`
- Diagnostics: `scripts/diagnostics/source_relief_validation.py`

## Mechanism

`compute_relief(expression, state, novelty, param_snapshot)` returns:

- `boredom_delta <= 0`
- `unresolved_delta <= 0`
- diagnostics for audit

Core formula:

```text
structure_score = connector_structure_score * length_shape_score
relief = accuracy * novelty * structure_score
boredom_delta = -relief * boredom * expression_relief.boredom_gain
unresolved_delta = -relief * unresolved * structure_score * expression_relief.unresolved_gain
```

`novelty` directly uses `repetition_discount`: `1.0` means fresh, lower values
mean repeated.

## Guardrails

- Loneliness is never changed by self-expression relief.
- v1 does not use `proposition_frame`.
- v1 does not mix into old quenching efficiency or strategy-map efficiency.
- Pure logical connector strings must not gain large relief.
- Logic words can increase structure, but only content/somatic words contribute
  to accuracy.

## Non-Goals

- No processing-depth logic.
- No world-model changes.
- No LLM calls.
- No direct learning of causal templates from relief.
- No daemon restart required for offline validation.

## Constants

Seed values, deliberately small:

| Constant | Value | Meaning |
| --- | ---: | --- |
| `_BOREDOM_RELIEF_GAIN` | 0.04 | max immediate boredom relief scale |
| `_UNRESOLVED_RELIEF_GAIN` | 0.06 | max immediate unresolved relief scale |
| `_BASE_STRUCTURE` | 0.15 | weak relief from naming without structure |
| `_ACCURACY_FLOOR` | 0.05 | floor for no content/somatic match |
| `_LEN_MU` | 8.0 | length-shape peak |
| `_LEN_SIGMA` | 5.0 | length-shape softness |

Both gains are overridable through `param_snapshot` keys:

- `expression_relief.boredom_gain`
- `expression_relief.unresolved_gain`

## Open Questions

- Whether v2 should add `proposition_frame` confidence as structure-quality
  calibration.
- Whether causal connectors should be split into finer classes once more online
  samples exist.
- Whether expression relief should later feed construction learning, and if so
  through an explicit audit gate rather than the old quenching signal.
