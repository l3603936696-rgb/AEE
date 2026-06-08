# CURSOR_PROMPT.md - large-file-split-pass-6

No Cursor implementation was requested for this pass.

Codex performed a small mechanical extraction:

- Move expression post-processing from `tick_engine.py` into
  `src/daemon/expression_postprocess.py`.
- Keep daemon tick behavior unchanged.
- Keep the helper call connected at the original point in `TickEngine.tick_now()`.
- Update daemon documentation and system index.
