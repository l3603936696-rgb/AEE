# Task Package: large-file-split-pass-5

## Goal

Continue reducing `tick_engine.py` with a behavior-preserving extraction. This
pass moves response-cache pre-warming out of the daemon tick loop.

## Background

- Why this matters: `tick_engine.py` still contains small cache bookkeeping
  routines inside the main tick flow.
- Current behavior: normal ticks inline-update `_response_cache` from the
  pipeline result's drive vector and output text.
- Desired behavior: `tick_engine.py` calls a focused helper while preserving the
  old continuous store/skip selection.

## Non-Goals

- Do not change cache matching or cache storage semantics.
- Do not change response generation.
- Do not modify live runtime state or generated logs.

## Constraints

- Keep the extraction mechanical and reviewable.
- Preserve exception logging around cache update failures.

## Expected Files or Areas

- `src/daemon/tick_engine.py`
- `src/daemon/response_prewarm.py`
- `src/daemon/README.md`
- `XIA_SYSTEMS.md`

## Acceptance Criteria

- [ ] `tick_engine.py` calls `update_response_cache()` at the old pre-warm point.
- [ ] Helper behavior preserves drive-vector/text/tick extraction.
- [ ] Helper behavior preserves continuous store/skip weighting.
- [ ] `python -m py_compile` passes for changed daemon files.
- [ ] Focused relevant tests pass or failures are documented.
