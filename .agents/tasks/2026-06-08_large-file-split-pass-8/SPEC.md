# Task Package: large-file-split-pass-8

## Goal

Accelerate `tick_engine.py` reduction with a grouped behavior-preserving
extraction. This pass moves source/profile post-pipeline handling out of the
daemon tick loop.

## Background

- Why this matters: `tick_engine.py` still contains source-profile, reply-drive,
  semantic-residue, and familiarity suppression logic inline.
- Current behavior: each tick updates source profile state inline after the
  pipeline result.
- Desired behavior: `tick_engine.py` calls one focused helper and keeps the
  returned `source_id` for downstream logic.

## Non-Goals

- Do not change source identity resolution.
- Do not change reply-drive injection.
- Do not change environment semantic residue injection.
- Do not change familiarity decay or loneliness suppression constants.
- Do not modify live runtime state or generated logs.

## Acceptance Criteria

- [ ] Helper returns the same `_src_id` value expected by `tick_engine.py`.
- [ ] Source profile update, residue injection, reply drive, and familiarity
  suppression happen in the old order.
- [ ] `python -m py_compile` passes for changed daemon files.
- [ ] Focused relevant tests pass or failures are documented.
