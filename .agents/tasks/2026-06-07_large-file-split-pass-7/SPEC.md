# Task Package: large-file-split-pass-7

## Goal

Accelerate `tick_engine.py` reduction with a grouped behavior-preserving
extraction. This pass moves several low-coupling post-pipeline helpers out of
the daemon tick loop.

## Background

- Why this matters: `tick_engine.py` still contains small post-pipeline
  bookkeeping and learning steps inline.
- Current behavior: covariance update, reading intake, reading sentence
  extraction, and StatePatternMemory tick run inline.
- Desired behavior: `tick_engine.py` keeps the same order while calling focused
  daemon helpers.

## Non-Goals

- Do not change reading selection or candidate thresholds.
- Do not change covariance tracker data shape.
- Do not change sentence extraction behavior.
- Do not change StatePatternMemory behavior.
- Do not modify live runtime state or generated logs.

## Acceptance Criteria

- [ ] Helper calls occur in the old order.
- [ ] Old exception logging and swallowing behavior is preserved.
- [ ] `python -m py_compile` passes for changed daemon files.
- [ ] Focused relevant tests pass or failures are documented.
