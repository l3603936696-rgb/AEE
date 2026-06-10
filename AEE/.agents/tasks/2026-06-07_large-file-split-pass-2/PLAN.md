# PLAN.md - large-file-split-pass-2

## Plan

1. Identify environment-vector maintenance code in `tick_engine.py`.
2. Move per-tick decay and input-source residue injection into a new daemon
   helper module.
3. Replace inline blocks with helper calls at the same points in the tick flow.
4. Update daemon documentation and system index.
5. Run focused compile/tests and record results.

## Review Focus

- Confirm timing is unchanged: decay before pipeline, injection after source
  profile update.
- Confirm numeric constants match the old inline behavior.
- Confirm helper failures are swallowed as before.
- Confirm no live daemon/runtime data was modified.
