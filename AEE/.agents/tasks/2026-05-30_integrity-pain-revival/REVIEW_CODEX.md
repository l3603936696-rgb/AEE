# Review: integrity-pain-revival

## Reviewer

- Name: Codex
- Date: 2026-05-30
- Diff reviewed: task package plus implementation files listed in `CURSOR_RESULT.md`.

## Context Used

- Graph tools used: requested, but code-review-graph tools were not available in
  this Codex session.
- Files inspected:
  - `.agents/tasks/2026-05-30_integrity-pain-revival/*`
  - `src/core/self_binding.py`
  - `src/core/integrity_signal.py`
  - `src/pipeline_runner/stages/s07a_state_update.py`
  - `src/pipeline_runner/stages/s04b_emerge.py`
  - `tests/test_integrity_pain.py`
- Tests run by Codex:
  - `python -m pytest tests/test_integrity_pain.py -q` -> 7 passed.
  - `python -m pytest tests/test_50_ticks.py -q` -> timed out after 124s.

## Findings

### High Risk

- None found in the narrow review.

### Medium Risk

- Harm decay can keep feeding pain for a long time after one event.
  `src/core/integrity_signal.py` multiplies stored `zone_harms` by
  `(1.0 - healing * HEAL_RATE)` and never drops small values to zero. Then
  `src/pipeline_runner/stages/s07a_state_update.py` adds
  `active_harm * _HARM_TO_PAIN` to `entity.pain` every tick. If healing is low
  or snapshots are insufficient, one file-change event can continue adding pain
  for many ticks and may saturate pain before the normal `s04a` decay catches up.
  Add a floor/epsilon cutoff or a regression test proving the total pain impulse
  stays bounded within the intended range.

- Daemon-level validation is still missing. The implementation is plausible and
  the unit tests pass, but the actual lifecycle depends on `s04b` reading the
  previous tick's `integrity_behavior_bias`, `s07a` writing the next bias, and
  `s04a` decaying pain. This remains unverified in a live daemon run.

### Low Risk

- The task package is complete and honestly marks this as a backfilled task
  after Claude Code implementation. That is acceptable, but it should remain
  clear that `REVIEW.md` is implementer self-review and this file is the
  independent Codex review.

- The new constants are named and documented in the task package. `_WITHDRAW_FLOOR`
  still needs Owner confirmation as already noted.

- Several implementation comments/docstrings render as mojibake in PowerShell.
  This does not appear to affect execution, but it makes future agent review
  harder. Consider an encoding cleanup pass for touched source files after the
  behavior is accepted.

## Test Coverage

- Covered by existing new unit tests:
  - nonzero binding floor,
  - monotonic binding with access,
  - perturbation history cap,
  - event-to-harm conversion,
  - no event/no new harm,
  - harm scales with magnitude.

- Missing or incomplete:
  - long-run harm decay cutoff / bounded pain accumulation,
  - end-to-end daemon restart and file-change observation,
  - direct assertion that `s04b` suppression changes the selected behavior or
    drive vector in the intended direction.

## Merge Recommendation

Revise before merge.

The core idea is sound and the focused unit tests pass. Before merging, add one
bounded-decay test or explicit cutoff for residual harm, confirm
`_WITHDRAW_FLOOR=0.40` with the Owner, and complete a daemon-level validation
when restart is allowed.
