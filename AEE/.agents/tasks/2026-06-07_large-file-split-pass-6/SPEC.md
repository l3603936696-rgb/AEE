# Task Package: large-file-split-pass-6

## Goal

Continue reducing `tick_engine.py` with a behavior-preserving extraction. This
pass moves post-output expression processing out of the daemon tick loop.

## Background

- Why this matters: `tick_engine.py` still contains language-system
  post-processing calls inline.
- Current behavior: each tick tags expression intent, applies self-counsel, and
  settles epistemic credit inline.
- Desired behavior: `tick_engine.py` calls one focused helper while preserving
  call order and failure handling.

## Non-Goals

- Do not change expression feedback logic.
- Do not change self-counsel behavior.
- Do not change epistemic credit settlement.
- Do not modify live runtime state or generated logs.

## Acceptance Criteria

- [ ] Helper preserves `tag_intent`, `apply_self_counsel`, and
  `settle_epistemic_credit` call order.
- [ ] Helper preserves old expression/tick extraction.
- [ ] `python -m py_compile` passes for changed daemon files.
- [ ] Focused relevant tests pass or failures are documented.
