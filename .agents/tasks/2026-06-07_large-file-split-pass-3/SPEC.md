# Task Package: large-file-split-pass-3

## Goal

Continue reducing `tick_engine.py` with a behavior-preserving extraction. This
pass moves output-causal observation open/close logic out of the daemon tick
loop.

## Background

- Why this matters: `tick_engine.py` still mixes orchestration with small causal
  observation bookkeeping routines.
- Current behavior: tick startup closes the previous output-causal observation
  inline; later output handling records the current output snapshot inline.
- Desired behavior: `tick_engine.py` keeps the same timing while output-causal
  bookkeeping lives in a focused helper module.

## Non-Goals

- Do not change which state dimensions are tracked.
- Do not change observation payload shape.
- Do not change tick order.
- Do not modify live runtime state or generated logs.

## Constraints

- Keep the extraction mechanical and reviewable.
- Preserve exception swallowing around both observation paths.

## Expected Files or Areas

- `src/daemon/tick_engine.py`
- `src/daemon/output_causal_observation.py`
- `src/daemon/README.md`
- `XIA_SYSTEMS.md`

## Acceptance Criteria

- [ ] `tick_engine.py` calls output-causal helpers at the old locations.
- [ ] Helper behavior preserves old observation dimensions and payloads.
- [ ] `python -m py_compile` passes for changed daemon files.
- [ ] Focused relevant tests pass or failures are documented.
