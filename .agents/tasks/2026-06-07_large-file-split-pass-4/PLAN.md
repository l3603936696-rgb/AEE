# PLAN.md - large-file-split-pass-4

## Plan

1. Identify duplicated causal observation blocks in `tick_engine.py`.
2. Move state-delta calculation and rolling retention into
   `src/daemon/causal_observation.py`.
3. Replace train-only and normal tick blocks with helper calls.
4. Update daemon documentation and system index.
5. Run focused compile/tests and record results.

## Review Focus

- Confirm train-only source remains `"none"`.
- Confirm normal tick source remains `_input_source`.
- Confirm observed dimensions, precision, and window size match old behavior.
