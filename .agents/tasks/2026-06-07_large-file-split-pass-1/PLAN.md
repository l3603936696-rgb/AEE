# PLAN.md - large-file-split-pass-1

## Plan

1. Identify a low-coupling extraction boundary in `tick_engine.py`.
2. Move the autonomous action memory write-back helper into a new daemon module.
3. Replace the old local helper call with the imported helper.
4. Update daemon documentation and system index.
5. Run focused compile/tests and record results.

## Review Focus

- Confirm this is a move-only behavior-preserving extraction.
- Confirm relative imports are correct.
- Confirm the autonomous action write-back payload is unchanged.
- Confirm no live daemon/runtime data was modified.
