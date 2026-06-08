# CURSOR_PROMPT.md - large-file-split-pass-2

No Cursor implementation was requested for this pass.

Codex performed a small mechanical extraction:

- Move environment-vector decay and source residue injection from
  `tick_engine.py` into `src/daemon/environment_vector.py`.
- Keep daemon tick behavior unchanged.
- Keep helper calls connected at the original points in `TickEngine.tick_now()`.
- Update daemon documentation and system index.

Future Cursor follow-up should preserve this boundary and avoid adding ambient
environment-vector mechanics back into `tick_engine.py`.
