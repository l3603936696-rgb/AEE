# CURSOR_PROMPT.md - large-file-split-pass-1

No Cursor implementation was requested for this pass.

Codex performed a small mechanical extraction:

- Move autonomous action memory write-back from `tick_engine.py` into
  `src/daemon/autonomous_action_memory.py`.
- Keep daemon tick behavior unchanged.
- Keep the extracted helper connected through `TickEngine`.
- Update daemon documentation and system index.

Future Cursor follow-up should preserve this boundary and avoid adding new
episode/snapshot construction logic back into `tick_engine.py`.
