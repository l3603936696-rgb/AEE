# REVIEW.md - large-file-split-pass-1

## Review Checklist

- [ ] `tick_engine.py` still calls autonomous memory write-back after tool action execution.
- [ ] `record_autonomous_action()` preserves the old episode payload.
- [ ] `record_autonomous_action()` preserves the old snapshot payload.
- [ ] `record_autonomous_action()` preserves the old behavior-rule update call.
- [ ] `record_autonomous_action()` preserves the old forget-right negative-delta logic.
- [ ] Daemon docs and `XIA_SYSTEMS.md` mention the new helper module.

## Review Notes

This pass intentionally does not review or alter existing source-identity and
observability changes already present in the working tree.
