# CURSOR_PROMPT.md - large-file-split-pass-4

No Cursor implementation was requested for this pass.

Codex performed a small mechanical extraction:

- Move tick-level causal observation recording from `tick_engine.py` into
  `src/daemon/causal_observation.py`.
- Keep daemon tick behavior unchanged.
- Keep helper calls connected at the original points in `TickEngine.tick_now()`.
- Update daemon documentation and system index.

Future Cursor follow-up should preserve this boundary and avoid adding
tick-level causal observation bookkeeping back into `tick_engine.py`.
