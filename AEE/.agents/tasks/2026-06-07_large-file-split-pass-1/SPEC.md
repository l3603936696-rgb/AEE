# Task Package: large-file-split-pass-1

## Goal

Begin reducing oversized legacy files with a low-risk mechanical extraction.
This pass extracts autonomous action memory write-back from `tick_engine.py`
without changing daemon tick behavior.

## Background

- Why this matters: `tick_engine.py` is oversized and mixes tick orchestration
  with episode/snapshot construction details.
- Current behavior: autonomous action results are recorded by a top-level helper
  inside `tick_engine.py`.
- Desired behavior: `tick_engine.py` keeps the same call flow while memory
  write-back lives in a focused daemon helper module.

## Non-Goals

- Do not change daemon tick order.
- Do not change autonomous action trigger conditions.
- Do not change episode, snapshot, or behavior-rule payloads.
- Do not touch live runtime state or generated logs.

## Constraints

- Follow `AGENTS.md` and existing daemon module boundaries.
- Use graph tools first when available; current session did not expose the
  code-review-graph MCP tools.
- Keep the extraction mechanical and reviewable.

## Expected Files or Areas

- `src/daemon/tick_engine.py`
- `src/daemon/autonomous_action_memory.py`
- `src/daemon/README.md`
- `XIA_SYSTEMS.md`

## Acceptance Criteria

- [ ] `tick_engine.py` imports and calls the extracted helper.
- [ ] Extracted helper preserves the previous write-back behavior.
- [ ] `python -m py_compile` passes for changed daemon files.
- [ ] Focused relevant tests pass or failures are documented.
- [ ] No unrelated formatting churn.
