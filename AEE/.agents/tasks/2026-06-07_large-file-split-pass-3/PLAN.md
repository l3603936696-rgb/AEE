# PLAN.md - large-file-split-pass-3

## Plan

1. Identify output-causal observation blocks in `tick_engine.py`.
2. Move close/open bookkeeping into `src/daemon/output_causal_observation.py`.
3. Replace inline blocks with helper calls at the same points.
4. Update daemon documentation and system index.
5. Run focused compile/tests and record results.

## Review Focus

- Confirm closure happens before `run_pipeline()`.
- Confirm new pending output snapshots are recorded after pipeline output.
- Confirm payload dimensions and exception behavior are unchanged.
