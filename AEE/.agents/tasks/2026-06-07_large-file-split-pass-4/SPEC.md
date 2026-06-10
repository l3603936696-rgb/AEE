# Task Package: large-file-split-pass-4

## Goal

Continue reducing `tick_engine.py` with a behavior-preserving extraction. This
pass moves tick-level causal observation recording out of the daemon tick loop.

## Background

- Why this matters: `tick_engine.py` still contains repeated state-delta
  observation bookkeeping.
- Current behavior: train-only and normal ticks both compute state deltas inline
  and append to `_causal_observations`.
- Desired behavior: `tick_engine.py` calls a shared helper while preserving the
  old dimensions, rounding, source labels, and rolling window.

## Non-Goals

- Do not change causal learning.
- Do not change which dimensions are observed.
- Do not change the 200-observation rolling window.
- Do not modify live runtime state or generated logs.

## Constraints

- Keep the extraction mechanical and reviewable.
- Preserve exception swallowing around observation recording.

## Expected Files or Areas

- `src/daemon/tick_engine.py`
- `src/daemon/causal_observation.py`
- `src/daemon/README.md`
- `XIA_SYSTEMS.md`

## Acceptance Criteria

- [ ] Train-only ticks record source `"none"` through the helper.
- [ ] Normal ticks record `_input_source` through the helper.
- [ ] Helper behavior preserves dimensions, rounding, and retention.
- [ ] `python -m py_compile` passes for changed daemon files.
- [ ] Focused relevant tests pass or failures are documented.
