# PLAN.md - large-file-split-pass-6

## Plan

1. Identify expression post-processing calls in `tick_engine.py`.
2. Move them into `src/daemon/expression_postprocess.py`.
3. Replace inline blocks with one helper call.
4. Update daemon documentation and system index.
5. Run focused compile/tests and record results.
