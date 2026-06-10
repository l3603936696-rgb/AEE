# Task Package: large-file-split-pass-2

## Goal

Continue reducing `tick_engine.py` with a behavior-preserving extraction. This
pass moves environment-vector maintenance out of the daemon tick loop.

## Background

- Why this matters: `tick_engine.py` still mixes orchestration with small state
  maintenance routines.
- Current behavior: tick startup decays semantic residue and raises social
  prediction tension inline; later input handling injects semantic residue and
  resets that tension inline.
- Desired behavior: `tick_engine.py` keeps the same timing and call flow while
  environment-vector mechanics live in a focused helper module.

## Non-Goals

- Do not change pipeline order.
- Do not change decay rates, pruning threshold, tension cap, or residue
  increment.
- Do not modify live runtime state or generated logs.
- Do not combine this with other tick-engine refactors.

## Constraints

- Follow `AGENTS.md` and existing daemon boundaries.
- Use graph tools first when available; current session did not expose the
  code-review-graph MCP tools.
- Keep the extraction mechanical and reviewable.

## Expected Files or Areas

- `src/daemon/tick_engine.py`
- `src/daemon/environment_vector.py`
- `src/daemon/README.md`
- `XIA_SYSTEMS.md`

## Acceptance Criteria

- [ ] `tick_engine.py` calls environment-vector helpers at the old locations.
- [ ] Helper behavior preserves old default vector, decay, pruning, tension,
  and input residue semantics.
- [ ] `python -m py_compile` passes for changed daemon files.
- [ ] Focused relevant tests pass or failures are documented.
- [ ] No unrelated formatting churn.
