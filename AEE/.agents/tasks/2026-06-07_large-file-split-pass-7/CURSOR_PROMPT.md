# CURSOR_PROMPT.md - large-file-split-pass-7

No Cursor implementation was requested for this pass.

Codex performed a grouped mechanical extraction:

- Move covariance tracker update into `src/daemon/covariance_update.py`.
- Move reading intake and reading-derived sentence extraction into
  `src/daemon/reading_cycle.py`.
- Move StatePatternMemory tick into `src/daemon/state_pattern_tick.py`.
- Keep daemon tick behavior unchanged.
- Update daemon documentation and system index.
